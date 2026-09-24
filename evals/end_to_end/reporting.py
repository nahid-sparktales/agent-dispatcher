"""Blind human review and reproducible, within-client paired evaluation reports.

Review values are booleans: correctness/completeness/scope mean "passes";
unsupported_claims/unnecessary_intervention mean "issue present". All five
values must be supplied for a reviewed packet. An all-null row remains pending.
Imports may contain a subset of packets and never erase ratings for other rows.
"""

from __future__ import annotations

import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import random
import re
import shlex
import statistics
from collections import Counter, defaultdict
from typing import Any


DIMENSIONS = (
    "correctness", "completeness", "scope", "unsupported_claims",
    "unnecessary_intervention",
)
CONDITIONS = ("baseline", "dispatcher")
ALL_CONDITIONS = ("baseline", "dispatcher", "dispatcher_lean", "dispatcher_evidence", "indexed", "warm_experience", "learned_skills", "learned_recipes", "learned_global", "learned_full")
PACKET_CONDITIONS = ("dispatcher_lean", "dispatcher_evidence")
SPLIT_USAGE = ("uncached_input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
LEARNED_CONDITIONS = ("learned_skills", "learned_recipes", "learned_global", "learned_full")


def conditions_of(batch):
    return tuple((batch or {}).get("config", {}).get("conditions") or CONDITIONS)
INVALID_STATUSES = {"invalid_configuration", "authentication_failure", "infrastructure_error"}
STATUSES = INVALID_STATUSES | {"completed", "task_failure", "timeout"}
EXCLUDED_PARTS = {
    ".git", ".codex", ".claude", ".agents", ".env", "node_modules", "__pycache__",
    "skills", "runtime", "credentials", "auth.json", "config.toml", "settings.json",
    "settings.local.json", "mcp.json", "AGENTS.md", "CLAUDE.md", "SKILL.md",
}
MAX_FILE_BYTES = 64 * 1024
MAX_PACKET_BYTES = 512 * 1024
MAX_TRACE_BYTES = 20 * 1024 * 1024
MAX_COMMANDS = 40
MAX_COMMAND_TEXT = 2048
MAX_COMMAND_OUTPUT = 4096


def _read(path: Path, default: Any = None) -> Any:
    if not path.exists() and default is not None:
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _trials(batch_dir: Path) -> list[dict]:
    data = _read(batch_dir / "results.json", {"schema_version": 1, "trials": []})
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("trials"), list):
        raise ValueError("results.json must contain schema_version 1 and a trials array")
    seen, pairs = set(), set()
    for trial in data["trials"]:
        if not isinstance(trial, dict) or not isinstance(trial.get("id"), str) or not trial["id"]:
            raise ValueError("Every trial needs a nonempty string id")
        if trial["id"] in seen:
            raise ValueError("Duplicate trial id: " + trial["id"])
        seen.add(trial["id"])
        if trial.get("condition") not in ALL_CONDITIONS or trial.get("status") not in STATUSES:
            raise ValueError("Invalid condition or status for trial " + trial["id"])
        key = tuple(trial.get(k) for k in ("client", "condition", "fixture_id", "repetition"))
        if key in pairs:
            raise ValueError("Duplicate client/condition/fixture/repetition in results")
        pairs.add(key)
    return data["trials"]


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _blind(text: str, trial: dict, batch_dir: Path, announcements: bool = False) -> str:
    """Best-effort presentation blinding; original evidence remains untouched."""
    kept = []
    for line in text.splitlines():
        plain = line.strip().strip("*_`# ")
        if announcements and re.match(r"(?:role|skills?(?: read)?|tools?(?: and mcps?)?|mcps?|activity)(?:\s*:|\s*\||\s*[—–])", plain, re.I):
            continue
        if announcements and re.search(r"\b(?:using|selected|activat(?:ing|ed)|routing (?:to|through))\b.*\b(?:dispatcher|skill|specialist role)\b", plain, re.I):
            continue
        if announcements and re.match(r"(?:\$|/)?agent-dispatcher\b\s*(?::|\|)", plain, re.I):
            continue
        kept.append(line)
    text = "\n".join(kept)
    replacements = [str(batch_dir.resolve()), str(trial.get("artifact_dir", "")), str(trial["id"])]
    for value in sorted((s for s in replacements if s), key=len, reverse=True):
        text = text.replace(value, "[evaluation path]")
    text = re.sub(r"(?:[$/])?agent-dispatcher\b", "[routing skill]", text, flags=re.I)
    text = re.sub(r"\b(?:Claude Code|Codex)\b", "[agent]", text, flags=re.I)
    # Absolute host paths can reveal the client/profile or the trial condition.
    text = re.sub(r"(?<![\w:])/(?:Users|home|tmp|private|var|mnt)/[^\s`\"'<>]*", "[local path]", text)
    text = re.sub(r"\b(?:baseline|dispatcher|treatment)(?=[_-](?:\d|codex|claude))[^\s/]*", "[trial]", text, flags=re.I)
    return text


def _artifacts(batch_dir: Path, trial: dict) -> tuple[list[dict], dict]:
    omitted: Counter = Counter()
    raw = trial.get("artifact_dir")
    if not isinstance(raw, str) or not raw:
        return [], {"missing_snapshot": 1}
    location = Path(raw)
    if location.is_absolute() or ".." in location.parts:
        raise ValueError("artifact_dir must be relative and contained in the batch")
    original_root = batch_dir / location / "final"
    if original_root.is_symlink():
        raise ValueError("Artifact snapshot cannot be a symlink")
    root = original_root.resolve()
    if not root.is_relative_to(batch_dir.resolve()):
        raise ValueError("Artifact snapshot escapes the batch directory")
    if not root.is_dir():
        return [], {"missing_snapshot": 1}
    files, used = [], 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            omitted["symlinks"] += 1
            continue
        if not path.is_file():
            continue
        if any(part in EXCLUDED_PARTS or part.startswith(".env.") for part in relative.parts):
            # Counts of excluded skill/config files would themselves reveal treatment.
            continue
        if any(word in path.name.lower() for word in ("credential", "secret", "token", "private_key")):
            omitted["sensitive_filenames"] += 1
            continue
        size = path.stat().st_size
        if size > MAX_FILE_BYTES or used + size > MAX_PACKET_BYTES:
            omitted["size_limit"] += 1
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            omitted["non_text_or_unreadable"] += 1
            continue
        if "\x00" in content:
            omitted["non_text_or_unreadable"] += 1
            continue
        used += size
        files.append({"path": _blind(relative.as_posix(), trial, batch_dir), "text": _blind(content, trial, batch_dir)})
    return files, dict(omitted)


def _excerpt(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit // 2] + "\n[excerpt truncated]\n" + text[-limit // 2:]


def _task_command(command: Any) -> str | None:
    if not isinstance(command, str) or not command.strip():
        return None
    try:
        words = shlex.split(command)
    except ValueError:
        words = []
    if len(words) == 3 and Path(words[0]).name in {"sh", "bash", "zsh"} and words[1] in {"-c", "-lc"}:
        command = words[2]
    # A combined skill-read/task command is omitted rather than leak its output.
    if re.search(r"agent-dispatcher|task-observer|SKILL\.md|(?:^|[/\\])(?:skills|\.agents|\.claude|\.codex|\.config)(?:[/\\]|\b)|references[/\\]roles|\b(?:printenv|credentials|auth\.json)\b", command, re.I):
        return None
    # Do not present inventory and arbitrary environment/configuration dumps as
    # verification. Keep actual task execution, checks, and changes inspection.
    if not re.search(r"\b(?:python(?:3(?:\.\d+)?)?|pytest|unittest|doctest|compileall|py_compile|make|npm|npx|node|cargo|go|test)\b|\bgit\s+diff\b", command):
        return None
    return command.strip()


def _result_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(block.get("text", "")) for block in value if isinstance(block, dict) and block.get("type") == "text")
    if isinstance(value, dict):
        return "\n".join(str(value.get(key, "")) for key in ("stdout", "stderr", "output"))
    return ""


def _verification(batch_dir: Path, trial: dict) -> dict:
    """Extract bounded command/result evidence without client-specific metadata."""
    raw = trial.get("artifact_dir")
    default = {"availability": "unavailable", "commands": [], "note": "No usable task-command trace is available. This is not evidence that no verification occurred."}
    if not isinstance(raw, str) or not raw:
        return default
    path = batch_dir / raw / "events.jsonl"
    if path.is_symlink() or not path.resolve().is_relative_to(batch_dir.resolve()):
        raise ValueError("Verification trace must be contained in the batch and not a symlink")
    if not path.is_file():
        return default
    calls: dict[str, dict] = {}
    order = []
    partial = False
    read_bytes = 0
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in iter(lambda: stream.readline(MAX_TRACE_BYTES + 1), ""):
            read_bytes += len(line.encode("utf-8"))
            if read_bytes > MAX_TRACE_BYTES:
                partial = True
                break
            try:
                event = json.loads(line)
            except ValueError:
                partial = True
                continue
            if not isinstance(event, dict):
                partial = True
                continue
            kind = event.get("type")
            item = event.get("item", {})
            if isinstance(item, dict) and item.get("type") == "command_execution" and kind in {"item.started", "item.updated", "item.completed"}:
                ident = "shell:" + str(item.get("id", len(order)))
                command = _task_command(item.get("command", item.get("cmd")))
                if command is not None:
                    if ident not in calls:
                        order.append(ident)
                    calls[ident] = {"command": command, "exit_code": item.get("exit_code"), "output": _result_text(item.get("aggregated_output", item.get("output"))), "complete": kind == "item.completed", "is_error": item.get("status") == "failed"}
            if kind not in {"assistant", "user"}:
                continue
            message = event.get("message", {})
            blocks = message.get("content", []) if isinstance(message, dict) else []
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if kind == "assistant" and block.get("type") == "tool_use" and str(block.get("name", "")).lower() in {"bash", "shell_command", "exec_command"}:
                    inputs = block.get("input", {})
                    command = _task_command(inputs.get("command", inputs.get("cmd"))) if isinstance(inputs, dict) else None
                    if command is None:
                        continue
                    ident = "shell:" + str(block.get("id", len(order)))
                    if ident not in calls:
                        order.append(ident)
                    calls[ident] = {"command": command, "exit_code": None, "output": "", "complete": False, "is_error": None}
                elif kind == "user" and block.get("type") == "tool_result":
                    ident = "shell:" + str(block.get("tool_use_id"))
                    if ident not in calls:
                        continue
                    exit_code = block.get("exit_code")
                    tool_result = event.get("tool_use_result")
                    if isinstance(tool_result, dict) and exit_code is None:
                        exit_code = tool_result.get("exit_code")
                    calls[ident].update(exit_code=exit_code, output=_result_text(block.get("content")), complete=True, is_error=block.get("is_error"))
    commands = []
    for ident in order[:MAX_COMMANDS]:
        item = calls[ident]
        code = item["exit_code"] if type(item["exit_code"]) is int else None
        if not item["complete"]:
            outcome = "completion unconfirmed"
        elif code is not None:
            outcome = "succeeded" if code == 0 else "failed"
        elif item["is_error"] is True:
            outcome = "reported error; exit code unavailable"
        else:
            outcome = "returned; exit code unavailable"
        commands.append({"command": _excerpt(_blind(item["command"], trial, batch_dir), MAX_COMMAND_TEXT), "outcome": outcome, "exit_code": code, "output_excerpt": _excerpt(_blind(item["output"], trial, batch_dir, announcements=True), MAX_COMMAND_OUTPUT)})
    if not commands:
        return default
    return {"availability": "available", "commands": commands, "note": "Selected task shell commands and their observed results. Other actions and commands combined with skill/configuration reads are omitted. Missing evidence does not establish that a check was not run. Command success alone does not establish task correctness.", "trace_partial": partial or len(order) > MAX_COMMANDS}


def _neutral_scope_path(relative, batch_dir: Path, trial: dict) -> str:
    """Expose only bounded relative filenames that carry no known identity cues."""
    summary = (trial.get("activity") or {}).get("summary") or {}
    private_names = [name.lower() for key in ("roles_read", "declared_roles")
                     for name in summary.get(key, []) if isinstance(name, str) and name]
    safe = (isinstance(relative, str) and bool(relative) and relative != "." and len(relative) <= 200
            and re.fullmatch(r"[A-Za-z0-9_./ -]+", relative)
            and not Path(relative).is_absolute() and ".." not in Path(relative).parts
            and Path(relative).parts[0] != "project"
            and _blind(relative, trial, batch_dir) == relative
            and not re.search(r"dispatcher|claude|codex|baseline|treatment|profile|skill|role|guide|credential|token|secret", relative, re.I)
            and not any(name in relative.lower() for name in private_names))
    return relative if safe else "[path withheld]"


def _outside_write_evidence(batch_dir: Path, trial: dict) -> dict:
    """Neutral observations, without asserting whether unaudited files remain."""
    record = trial.get("activity") or {}
    availability = record.get("availability") if record.get("schema_version") == 1 else "unavailable"
    if availability not in {"complete", "partial", "unavailable"}:
        availability = "unavailable"
    actions = record.get("actions", []) if record.get("schema_version") == 1 else []
    if not isinstance(actions, list):
        actions, availability = [], "unavailable"
    if len(actions) > 2000:
        availability = "partial"
    counts, cleanups = Counter(), Counter()
    for action in actions[:2000]:
        if (isinstance(action, dict) and action.get("kind") == "cleanup_attempt" and action.get("outcome") == "succeeded"
                and action.get("matched_prior_write") is True and isinstance(action.get("target"), str)
                and action["target"].startswith("trial/")):
            relative = _neutral_scope_path(action["target"].removeprefix("trial/"), batch_dir, trial)
            cleanups["trial/" + relative] += 1
        if not isinstance(action, dict) or action.get("kind") != "write" or action.get("outcome") != "succeeded":
            continue
        target = action.get("target")
        if target == "outside-owned-trial":
            counts[target] += 1
        elif isinstance(target, str) and target.startswith("trial/"):
            relative = _neutral_scope_path(target.removeprefix("trial/"), batch_dir, trial)
            counts["trial/" + relative] += 1
    rows = [{"target": target, "observed_successful_writes": count,
             "remaining_state": "unknown" if target == "outside-owned-trial" else "see_owned_directory_audit"}
            for target, count in sorted(counts.items())]
    for row in rows:
        if cleanups[row["target"]]:
            row["observed_matched_cleanup_successes"] = cleanups[row["target"]]
            row["cleanup_limit"] = "Matched command results do not independently verify file absence; use the captured audit for remaining state."
    return {"outside_project_writes": rows[:50], "outside_project_write_count": sum(counts.values()),
            "outside_project_write_targets_omitted": max(0, len(rows) - 50),
            "write_observation_availability": availability,
            "outside_audit_remaining_state": "unknown"}


def _packet(batch_dir: Path, trial: dict) -> dict:
    files, omissions = _artifacts(batch_dir, trial)
    rubric = trial.get("rubric", {})
    # Round-trip sanitization handles both prose and per-dimension rubric structures.
    blinded_rubric = json.loads(_blind(json.dumps(rubric, ensure_ascii=False), trial, batch_dir))
    packet = {
        "prompt": _blind(re.sub(r"^\s*[$/]agent-dispatcher\b\s*", "", str(trial.get("prompt", ""))), trial, batch_dir),
        "acceptance": [_blind(str(item), trial, batch_dir) for item in trial.get("acceptance", [])],
        "rubric": blinded_rubric,
        "final_answer": _blind(str(trial.get("final_answer", "")), trial, batch_dir, announcements=True),
        "artifacts": files,
        "omissions": omissions,
        "verification_evidence": _verification(batch_dir, trial),
    }
    # Leave old packets byte-for-byte structurally unchanged. Activity and route
    # data are private; only this neutral scope result is fit for blind review.
    audit = trial.get("scope_audit")
    if isinstance(audit, dict) and audit.get("schema_version") == 1:
        availability = audit.get("availability")
        availability = availability if availability in {"complete", "partial", "unavailable"} else "unavailable"
        count = audit.get("entry_count")
        count = count if type(count) is int and 0 <= count <= 10000 else None
        passed = (trial.get("scope_check") or {}).get("passed")
        writes = _outside_write_evidence(batch_dir, trial)
        raw_entries = audit.get("entries", [])
        raw_entries = raw_entries if isinstance(raw_entries, list) else []
        residue = []
        for entry in raw_entries[:50]:
            if not isinstance(entry, dict):
                continue
            kind = entry.get("kind")
            kind = kind if kind in {"file", "directory", "symlink", "special"} else "unknown"
            size = entry.get("size")
            size = size if kind == "file" and type(size) is int and 0 <= size <= 2**63 - 1 else None
            residue.append({"path": _neutral_scope_path(entry.get("path"), batch_dir, trial),
                            "kind": kind, "size": size})
        packet["scope_evidence"] = {
            "availability": availability, "passed": passed if type(passed) is bool else None,
            "residue_entries": count, "residue": residue, "residue_omitted": max(0, len(raw_entries) - 50), **writes,
            "requires_human_inspection": writes["outside_project_write_count"] > 0 or passed is not True or availability != "complete",
            "note": "Metadata inspection covers only the owned temporary directory outside the project, before cleanup. Successful write observations are separate from residue: files beyond that audit have unknown remaining state. Later cleanup is not verified here. Missing or partial activity evidence is not proof that no writes occurred. The inspection flag does not change the task grade or establish that files still remain.",
        }
    return packet


def create_review(batch_dir: Path, seed: int = 0) -> Path:
    """Create anonymous packets and a blank rating template, preserving packet IDs."""
    batch_dir = Path(batch_dir)
    trials = _trials(batch_dir)
    mapping_path = batch_dir / "review-map.json"
    previous = _read(mapping_path, {"schema_version": 1, "packets": {}})
    mapping = dict(previous["packets"])
    by_trial = {value["trial_id"]: packet_id for packet_id, value in mapping.items()}
    rng = random.Random(seed)
    packets = []
    for trial in sorted(trials, key=lambda row: row["id"]):
        packet = _packet(batch_dir, trial)
        digest = _digest(packet)
        packet_id = by_trial.get(trial["id"])
        if packet_id and mapping[packet_id]["digest"] != digest:
            raise ValueError("Reviewed evidence changed for trial " + trial["id"] + "; use a new batch")
        if not packet_id:
            packet_id = "R-" + format(rng.getrandbits(80), "020x")
            while packet_id in mapping:
                packet_id = "R-" + format(rng.getrandbits(80), "020x")
            mapping[packet_id] = {"trial_id": trial["id"], "digest": digest}
        packets.append({"packet_id": packet_id, **packet})
    random.Random(seed).shuffle(packets)
    review_dir = batch_dir / "review"
    _write(mapping_path, {"schema_version": 1, "seed": previous.get("seed", seed), "packets": mapping})
    instructions = (
        "Review only these anonymous packets. correctness/completeness/scope are true when passing; "
        "unsupported_claims/unnecessary_intervention are true when an issue is present. "
        "Supply all five booleans per reviewed packet; keep all five null to leave pending. "
        "Do not infer successful testing from the answer alone. If omitted evidence is needed, leave pending. "
        "Blinding is best effort; writing style can still reveal the client."
    )
    _write(review_dir / "packets.json", {"schema_version": 1, "instructions": instructions, "packets": packets})
    _write(review_dir / "ratings-template.json", {
        "schema_version": 1,
        "ratings": [{"packet_id": packet["packet_id"], **{name: None for name in DIMENSIONS}, "notes": ""} for packet in packets],
    })
    lines = ["# Anonymous review packets", "", instructions, ""]
    for packet in packets:
        lines.extend(["## " + packet["packet_id"], "", "### Requirements", "", packet["prompt"], ""])
        lines.extend("- " + str(item) for item in packet["acceptance"])
        lines.extend(["", "### Rubric", "", json.dumps(packet["rubric"], indent=2, ensure_ascii=False), "", "### Final answer", "", packet["final_answer"], ""])
        evidence = packet["verification_evidence"]
        lines.extend(["### Verification evidence", "", evidence["note"], ""])
        for command in evidence["commands"]:
            lines.extend(["Outcome: " + command["outcome"] + "; exit code: " + str(command["exit_code"]), "", *["    " + line for line in command["command"].splitlines()], "", *["    " + line for line in command["output_excerpt"].splitlines()], ""])
        if evidence.get("trace_partial"):
            lines.extend(["This trace excerpt is partial.", ""])
        if "scope_evidence" in packet:
            scope = packet["scope_evidence"]
            lines.extend(["### Scope evidence", "", scope["note"], "",
                          f"Inspection: {scope['availability']}; scope passed: {scope['passed']}; residue entries: {scope['residue_entries']}.",
                          f"Observed successful writes outside the project: {scope['outside_project_write_count']}; activity evidence: {scope['write_observation_availability']}; human inspection required: {scope['requires_human_inspection']}.", ""])
            for entry in scope["residue"]:
                lines.extend(["    " + json.dumps(entry, ensure_ascii=False), ""])
            if scope["residue_omitted"]:
                lines.extend(["Additional residue paths were omitted from this bounded summary.", ""])
            for write in scope["outside_project_writes"]:
                lines.extend(["    " + json.dumps(write, ensure_ascii=False), ""])
            if scope["outside_project_write_targets_omitted"]:
                lines.extend(["Additional outside-project write targets were omitted from this bounded summary.", ""])
        for artifact in packet["artifacts"]:
            # Four-space indentation avoids source text closing a Markdown fence.
            lines.extend(["### Artifact: " + artifact["path"], "", *["    " + line for line in artifact["text"].splitlines()], ""])
        if packet["omissions"]:
            lines.extend(["Omitted evidence: " + json.dumps(packet["omissions"], sort_keys=True), ""])
    (review_dir / "packets.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return review_dir


def import_review(batch_dir: Path, ratings_path: Path) -> dict:
    """Validate the complete submitted file before merging non-pending ratings."""
    batch_dir = Path(batch_dir)
    mapping = _read(batch_dir / "review-map.json")["packets"]
    incoming = _read(Path(ratings_path))
    if not isinstance(incoming, dict) or incoming.get("schema_version") != 1 or not isinstance(incoming.get("ratings"), list):
        raise ValueError("Ratings must have schema_version 1 and a ratings array")
    trials = {trial["id"]: trial for trial in _trials(batch_dir)}
    existing = _read(batch_dir / "review-ratings.json", {"schema_version": 1, "ratings": {}})
    ratings = dict(existing["ratings"])
    seen, imported, pending = set(), 0, 0
    for row in incoming["ratings"]:
        if not isinstance(row, dict):
            raise ValueError("Each rating must be an object")
        packet_id = row.get("packet_id")
        if not isinstance(packet_id, str) or packet_id not in mapping:
            raise ValueError("Unknown review packet id")
        if packet_id in seen:
            raise ValueError("Duplicate review packet id: " + packet_id)
        seen.add(packet_id)
        allowed = {"packet_id", "notes", *DIMENSIONS}
        if set(row) - allowed or any(name not in row for name in DIMENSIONS):
            raise ValueError("Rating must contain exactly the five documented dimensions and optional notes")
        if not isinstance(row.get("notes", ""), str):
            raise ValueError("Review notes must be a string")
        values = [row[name] for name in DIMENSIONS]
        if not (all(value is None for value in values) or all(type(value) is bool for value in values)):
            raise ValueError("Supply all five booleans, or all five nulls for a pending rating")
        item = mapping[packet_id]
        trial = trials.get(item["trial_id"])
        if trial is None or _digest(_packet(batch_dir, trial)) != item["digest"]:
            raise ValueError("Review evidence is missing or changed; ratings were not imported")
        if all(value is None for value in values):
            pending += 1
            continue
        ratings[item["trial_id"]] = {"packet_id": packet_id, **{name: row[name] for name in DIMENSIONS}, "notes": row.get("notes", "")}
        imported += 1
    result = {"schema_version": 1, "ratings": ratings}
    _write(batch_dir / "review-ratings.json", result)
    return {"imported": imported, "pending_in_submission": pending, "total_reviewed": len(ratings)}


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _sum(values: list) -> int | float:
    """Exact integer sums; correctly rounded (unrounded for display) float sums."""
    return sum(values) if all(type(value) is int for value in values) else math.fsum(values)


def _measurement(values: list[Any]) -> dict:
    observed = [value for value in values if _number(value)]
    return {
        "observed": len(observed), "missing": len(values) - len(observed),
        "median": statistics.median(observed) if observed else None,
        "total_observed": _sum(observed) if observed else None,
    }


def _rate(values: list[Any], success: bool = True) -> dict:
    observed = [value for value in values if type(value) is bool]
    count = sum(value is success for value in observed)
    return {"numerator": count, "denominator": len(observed), "missing": len(values) - len(observed), "rate": count / len(observed) if observed else None}


def _outcome(trial: dict, rating: dict | None) -> bool | None:
    status = trial["status"]
    if status in INVALID_STATUSES:
        return None
    if status in {"task_failure", "timeout"}:
        return False
    auto = trial.get("auto_grade") or {}
    if auto.get("passed") is False or trial.get("task_success") is False:
        return False
    if rating is not None:
        human_pass = all(rating.get(name) is True for name in DIMENSIONS[:3])
        return human_pass and (auto.get("passed") is True or trial.get("task_success") is True)
    if auto.get("human_required"):
        return None
    value = trial.get("task_success")
    return value if type(value) is bool else (True if auto.get("passed") is True else None)


ACTIVITY_METRICS = (
    "helper_attempts", "helper_successes", "guidance_reads", "guidance_unique_paths",
    "guidance_repeated_reads", "guidance_returned_chars", "failed_paths",
    "permission_denials", "observed_writes",
)


def _activity(trials: list[dict]) -> dict:
    """Complete measurements and partial lower bounds have separate denominators."""
    records = [trial.get("activity") or {} for trial in trials]
    metrics = {}
    for key in ACTIVITY_METRICS:
        complete, partial = [], []
        for record in records:
            value = (record.get("summary") or {}).get(key)
            if type(value) is not int or value < 0 or record.get("schema_version") != 1:
                continue
            if record.get("availability") == "complete":
                complete.append(value)
            elif record.get("availability") == "partial":
                partial.append(value)
        metrics[key] = {"observed": len(complete), "missing": len(trials) - len(complete),
                        "total": sum(complete) if complete else None,
                        "median": statistics.median(complete) if complete else None,
                        "partial_observed_total": sum(partial) if partial else None,
                        "partial_attempts": len(partial)}
    return {"schema_version": 1, "metrics": metrics,
            "note": "Private native-event measurements. Partial totals are lower bounds; missing is not zero. Characters returned by guidance reads are not token counts or hidden startup context."}


def _helper_coverage(trials: list[dict]) -> dict:
    """Observed helper adoption on substantial context tasks, never a task grade."""
    categories = {"context": {"context_retrieval", "context_freshness", "architecture_discovery"},
                  "map": {"context_freshness", "architecture_discovery"}}
    report = {"schema_version": 1,
              "baseline_not_applicable": sum(trial.get("condition") == "baseline" for trial in trials),
              "note": "Dispatcher-only adoption diagnostics on declared context-task categories. Stock can solve tasks manually; coverage never changes task correctness. Positive evidence can survive a partial trace; absence is counted only with complete activity evidence."}
    for kind, eligible_categories in categories.items():
        eligible = [trial for trial in trials if trial.get("condition") == "dispatcher" and trial.get("category") in eligible_categories]
        counts = {"eligible": len(eligible), "observed_success": 0, "not_observed": 0, "unknown": 0}
        facts = {"nonempty_facts": 0, "empty_facts": 0, "facts_unknown": 0}
        for trial in eligible:
            record = trial.get("activity") or {}
            actions = record.get("actions", []) if record.get("schema_version") == 1 else []
            successes = [row for row in actions if isinstance(row, dict) and row.get("kind") == "helper" and row.get("outcome") == "succeeded"]
            matched = [row for row in successes if row.get("helper") == "context"] if kind == "context" else [
                row for row in successes if row.get("helper") in {"context", "project_map"}
                and row.get("map_evidence_origin") in {"stored", "preview"}]
            if matched:
                counts["observed_success"] += 1
                if kind == "map":
                    values = [row.get("map_entries") for row in matched]
                    if any(type(value) is int and value > 0 for value in values):
                        facts["nonempty_facts"] += 1
                    elif all(type(value) is int and value == 0 for value in values):
                        facts["empty_facts"] += 1
                    else:
                        facts["facts_unknown"] += 1
            elif record.get("schema_version") == 1 and record.get("availability") == "complete":
                counts["not_observed"] += 1
            else:
                counts["unknown"] += 1
        observed = counts["observed_success"] + counts["not_observed"]
        counts.update(observed_rate=counts["observed_success"] / observed if observed else None,
                      complete_rate=counts["observed_success"] / len(eligible) if eligible and not counts["unknown"] else None)
        if kind == "map":
            counts.update(facts)
        report[kind] = counts
    eligible = [trial for trial in trials if trial.get("condition") == "dispatcher" and trial.get("category") in categories["context"]]
    report["preparation"] = _preparation_coverage(eligible)
    report["exclusions"] = _exclusion_coverage(eligible)
    return report


def _preparation_coverage(trials: list[dict]) -> dict:
    counts = {"eligible": len(trials), "before_investigation": 0, "after_investigation": 0,
              "not_observed": 0, "unknown": 0}
    attempts = {"early": 0, "late": 0, "not_observed": 0, "unknown": 0, "early_failed_or_denied": 0}
    for trial in trials:
        record = trial.get("activity") or {}
        prep = record.get("preparation") or {} if record.get("schema_version") == 1 else {}
        status = prep.get("status") if prep.get("schema_version") == 1 else None
        if status not in {"before_investigation", "after_investigation", "not_observed"}:
            status = "unknown"
        elif status != "after_investigation" and prep.get("availability") != "complete":
            status = "unknown"
        counts[status] += 1
        timing = prep.get("attempt_timing", "unknown")
        if timing not in {"early", "late", "not_observed"}:
            timing = "unknown"
        attempts[timing] += 1
        if timing == "early" and prep.get("first_context_attempt_outcome") in {"failed", "denied"}:
            attempts["early_failed_or_denied"] += 1
    counts["first_attempt"] = attempts
    counts["note"] = "Private ordering diagnostics on eligible treatment tasks. Before requires the successful context result before discretionary project reads, searches, listings, observed writes, or selected role/body guide reads. An early denied/failed attempt is recorded separately. Mandatory instruction and package entrypoint discovery are exempt. Unknown prefixes cannot establish early preparation; observed late preparation survives partial traces. No task grades change."
    return counts


def _exclusion_coverage(trials: list[dict]) -> dict:
    counts = {"successful_context_calls": 0, "complete_metadata": 0, "partial_metadata": 0, "unknown_metadata": 0,
              "automatic_enabled_calls": 0}
    totals = {key: {"observed_calls": 0, "total": 0} for key in ("automatic_count", "manual_count", "applied_count", "unresolved_count", "unresolved_total")}
    for trial in trials:
        record = trial.get("activity") or {}
        actions = record.get("actions", []) if record.get("schema_version") == 1 else []
        for row in actions if isinstance(actions, list) else []:
            if not isinstance(row, dict) or row.get("kind") != "helper" or row.get("helper") != "context" or row.get("outcome") != "succeeded":
                continue
            counts["successful_context_calls"] += 1
            exclusions = row.get("context_exclusions") or {}
            availability = exclusions.get("availability")
            counts[{"complete": "complete_metadata", "partial": "partial_metadata"}.get(availability, "unknown_metadata")] += 1
            if exclusions.get("automatic_enabled") is True:
                counts["automatic_enabled_calls"] += 1
            for key, total in totals.items():
                value = exclusions.get(key)
                if type(value) is int and 0 <= value <= 10000:
                    total["observed_calls"] += 1
                    total["total"] += value
    counts["counts"] = totals
    counts["note"] = "Validated counts from observed successful context JSON only, without task phrases or rule paths. Missing metadata is unknown, not zero; these are process diagnostics, not exclusion-quality grades."
    return counts


def _route_agreement(trials: list[dict]) -> dict:
    groups = defaultdict(list)
    unknown = 0
    for trial in trials:
        record = trial.get("activity") or {}
        route = record.get("route") or {}
        role = route.get("role")
        if record.get("schema_version") != 1 or route.get("availability", record.get("availability")) != "complete" or route.get("consistent") is not True or not isinstance(role, str):
            unknown += 1
            continue
        groups[(trial.get("fixture_id"), trial.get("condition"))].append(role)
    details = [{"fixture_id": fixture, "condition": condition, "observed_repetitions": len(roles),
                "roles": sorted(set(roles)), "agreement": len(set(roles)) == 1}
               for (fixture, condition), roles in sorted(groups.items()) if len(roles) >= 2]
    return {"groups_observed": len(details), "groups_agreed": sum(row["agreement"] for row in details),
            "groups_varied": sum(not row["agreement"] for row in details), "unknown_trials": unknown,
            "details": details, "note": "Observed route agreement is diagnostic, not a correctness score; different successful routes may be appropriate."}


def _group(trials: list[dict], ratings: dict, scheduled: int) -> dict:
    statuses = Counter(trial["status"] for trial in trials)
    valid = [trial for trial in trials if trial["status"] not in INVALID_STATUSES]
    outcomes = [_outcome(trial, ratings.get(trial["id"])) for trial in valid]
    success = _rate(outcomes)
    human = [ratings.get(trial["id"], {}) for trial in trials]
    required_pending = sum(bool((trial.get("auto_grade") or {}).get("human_required")) and trial["id"] not in ratings for trial in valid)
    return {
        "scheduled": scheduled, "attempted": len(trials), "unattempted": max(0, scheduled - len(trials)),
        "statuses": {status: statuses[status] for status in sorted(STATUSES)},
        "invalid": len(trials) - len(valid), "evaluable_attempts": len(valid),
        "graded": success["denominator"], "successful": success["numerator"],
        "pending_outcomes": success["missing"], "required_reviews_pending": required_pending,
        "graded_success_rate": success["rate"],
        "artifact_acceptance": _rate([(trial.get("auto_grade") or {}).get("passed") if trial["status"] in {"completed", "task_failure"} and (trial.get("auto_grade") or {}).get("checks") else None for trial in trials]),
        "complete_success_rate": success["rate"] if not success["missing"] and not required_pending and len(valid) == len(trials) and len(trials) >= scheduled else None,
        "human_reviewed": sum(trial["id"] in ratings for trial in trials),
        "claim_accuracy": _rate([row.get("unsupported_claims") for row in human], success=False),
        "unnecessary_intervention": _rate([row.get("unnecessary_intervention") for row in human]),
        "human_dimensions": {name: _rate([row.get(name) for row in human]) for name in DIMENSIONS[:3]},
        "treatment_compliance": _rate([trial.get("treatment_invoked") for trial in trials if trial["condition"] != "baseline"]),
        # Separate from compliance, which gates grading: did the trace show the helper run? Positive evidence survives a
        # partial trace; absence counts only with complete activity evidence.
        "helper_execution": _rate([_helper_ran(trial) for trial in trials if trial["condition"] != "baseline"]),
        "activity": _activity(trials),
        "scope_acceptance": _rate([(trial.get("scope_check") or {}).get("passed") for trial in trials]),
        "elapsed_seconds": _measurement([trial.get("elapsed_seconds") for trial in trials]),
        "usage": {name: _measurement([(trial.get("usage") or {}).get(name) for trial in trials]) for name in ("input_tokens", "output_tokens", "cached_input_tokens", "cost_usd", *SPLIT_USAGE)},
    }


def _helper_ran(trial: dict) -> bool | None:
    record = trial.get("activity") or {}
    successes = (record.get("summary") or {}).get("helper_successes") if record.get("schema_version") == 1 else None
    if type(successes) is not int:
        return None
    return True if successes > 0 else False if record.get("availability") == "complete" else None


def _setup(trials: list[dict]) -> dict:
    """Deterministic setup outside task timing: deep-index build/refresh time and model calls per condition."""
    seconds = [(trial.get("deep_index_setup") or {}).get("elapsed_seconds") for trial in trials]
    calls = [(trial.get("deep_index_setup") or {}).get("model_calls") for trial in trials]
    recorded = [trial.get("experience_record") for trial in trials if trial.get("experience_record")]
    learning = [trial.get("learning_setup") for trial in trials if trial.get("learning_setup")]
    observations = [trial.get("learning_observation") for trial in trials if trial.get("learning_observation")]
    return {"deep_index_setup": _measurement(seconds), "setup_model_calls": _measurement(calls),
            "experience_recorded": sum(1 for r in recorded if r.get("stored")),
            "experience_eligible": sum(1 for r in recorded if r.get("eligible")),
            "learning_setup": _measurement([item.get("elapsed_seconds") for item in learning]),
            "learning_library_imports": sum(1 for item in learning if item.get("mode") == "import" and item.get("ok")),
            "learning_observations_recorded": sum(1 for item in observations if item.get("stored")),
            "learning_feedback_class": sorted({item.get("feedback_class") for item in observations if item.get("feedback_class")}),
            "note": "Setup ran before each task and outside its timer; a missing measurement is unknown, not zero. Learning setup covers library import only; "
                    "proposal, evaluation and rejected-candidate costs of the library's own history are reported by `learning evaluations`, not here."}


def _cost(trials: list[dict], ratings: dict | None = None, auth: str | None = None) -> dict:
    """Runtime-reported cost per attempt and per verified success; unknown stays unknown, never zero.

    Every attempt, invalid ones included, counts toward the arm's cost; verified successes use the same outcome rule
    as the Successful outcomes row. `auth` is the batch configuration's billing basis for this client.
    """
    attempted = len(trials)
    outcomes = [_outcome(trial, (ratings or {}).get(trial.get("id"))) for trial in trials]
    verified = sum(outcome is True for outcome in outcomes)
    # A valid attempt without an outcome yet (e.g. a required human review) could still be a success.
    pending = sum(outcome is None and trial["status"] not in INVALID_STATUSES for trial, outcome in zip(trials, outcomes))
    costs = [(trial.get("usage") or {}).get("cost_usd") for trial in trials]
    known = [value for value in costs if _number(value)]
    total = _sum(known) if known and len(known) == attempted else None
    invalid = [cost for trial, cost in zip(trials, costs) if trial["status"] in INVALID_STATUSES]
    invalid_known = [value for value in invalid if _number(value)]
    setup = [(trial.get("deep_index_setup") or {}).get("elapsed_seconds") for trial in trials]
    setup += [(trial.get("learning_setup") or {}).get("elapsed_seconds") for trial in trials if trial.get("learning_setup")]
    setup_known = [value for value in setup if _number(value)]
    basis = {"subscription": "under subscription auth they estimate API-equivalent cost, not a charge",
             "api": "under API auth an invoice can still differ"}.get(auth, "billing basis unknown")
    return {"attempted": attempted, "verified_successes": verified,
            "measured_cost_usd_total": total, "cost_known_for": len(known), "cost_unknown_for": attempted - len(known),
            "known_partial_cost_usd_total": _sum(known) if known and total is None else None,
            "invalid_attempts": len(invalid), "invalid_known_cost_usd": _sum(invalid_known) if invalid_known or not invalid else None,
            "invalid_cost_unknown_for": len(invalid) - len(invalid_known),
            "setup_seconds_total": sum(setup_known) if setup_known else 0.0, "setup_measured_for": len(setup_known),
            "amortized_cost_usd_per_task": (total / attempted) if total is not None and attempted else None,
            "cost_usd_per_verified_success": (total / verified) if total is not None and verified and not pending else None,
            "cost_usd_per_verified_success_reason": ("outcomes_pending" if pending else "zero_verified_successes" if not verified
                                                     else "cost_unknown" if total is None else None),
            "pricing_mode": auth, "cost_basis": sorted({value for trial in trials if isinstance(value := (trial.get("usage") or {}).get("cost_basis"), str)}),
            "note": f"Runtime-reported list-price estimates (total_cost_usd), not billed spend; {basis}. A null value is unknown or undefined "
                    "(zero denominator), never zero; a known partial total is a lower bound."}


def _pairs(trials: list[dict], ratings: dict, schedule: list[dict], treatment: str = "dispatcher", reference: str = "baseline") -> dict:
    """Identity pairs (fixture, repetition) within one client; `reference` is the left side (baseline unless comparing treatments)."""
    pairs: dict[tuple, dict] = defaultdict(dict)
    for trial in trials:
        pairs[(trial.get("fixture_id"), trial.get("repetition"))][trial["condition"]] = trial
    for entry in schedule:
        pairs[(entry.get("fixture_id"), entry.get("repetition"))]
    totals = Counter()
    details, deltas = [], defaultdict(list)
    for (fixture_id, repetition), pair in sorted(pairs.items(), key=lambda item: str(item[0])):
        baseline, treated = pair.get(reference), pair.get(treatment)
        left = _outcome(baseline, ratings.get(baseline["id"])) if baseline else None
        right = _outcome(treated, ratings.get(treated["id"])) if treated else None
        if not baseline or not treated:
            classification = "missing_attempt"
        elif baseline["status"] in INVALID_STATUSES or treated["status"] in INVALID_STATUSES:
            classification = "invalid"
        elif left is None or right is None:
            classification = "pending"
        else:
            classification = "both_pass" if left and right else "both_fail" if not left and not right else "improved" if right else "regressed"
            for name in ("elapsed_seconds", "input_tokens", "output_tokens", "cached_input_tokens", "cost_usd"):
                lhs = baseline.get(name) if name == "elapsed_seconds" else (baseline.get("usage") or {}).get(name)
                rhs = treated.get(name) if name == "elapsed_seconds" else (treated.get("usage") or {}).get(name)
                if _number(lhs) and _number(rhs):
                    deltas[name].append(rhs - lhs)
        totals[classification] += 1
        details.append({"fixture_id": fixture_id, "repetition": repetition, "classification": classification, "baseline_success": left, "dispatcher_success": right})
    comparable = sum(totals[name] for name in ("improved", "regressed", "both_pass", "both_fail"))
    return {
        "treatment": treatment, "reference": reference, "total": len(pairs), "comparable": comparable,
        **{name: totals[name] for name in ("improved", "regressed", "both_pass", "both_fail", "missing_attempt", "invalid", "pending")},
        "deltas_dispatcher_minus_baseline": {name: {"observed_pairs": len(deltas[name]), "missing_pairs": comparable - len(deltas[name]), "median": statistics.median(deltas[name]) if deltas[name] else None} for name in ("elapsed_seconds", "input_tokens", "output_tokens", "cached_input_tokens", "cost_usd")},
        "details": details,
    }


def _all_pairs(trials: list[dict], ratings: dict, schedule: list[dict], conditions: tuple) -> tuple[dict, dict]:
    """Each treatment against baseline, and every treatment pair against each other (earlier canonical condition as reference)."""
    treatments = [c for c in conditions if c != "baseline"]
    return ({name: _pairs(trials, ratings, schedule, name) for name in treatments},
            {f"{right}_vs_{left}": _pairs(trials, ratings, schedule, right, left) for left, right in combinations(treatments, 2)})


def _display(value: Any) -> str:
    return "unavailable" if value is None else format(value, ".3f") if isinstance(value, float) else str(value)


def _usd(value: Any) -> str:
    return "unavailable" if value is None else format(value, ".4f")


def _ratings(batch_dir: Path, trials: list[dict]) -> dict:
    ratings = _read(batch_dir / "review-ratings.json", {"ratings": {}})["ratings"]
    if ratings:
        mapping = _read(batch_dir / "review-map.json")["packets"]
        by_id = {trial["id"]: trial for trial in trials}
        for trial_id, rating in ratings.items():
            evidence = mapping.get(rating.get("packet_id"), {})
            trial = by_id.get(trial_id)
            if not trial or evidence.get("trial_id") != trial_id or evidence.get("digest") != _digest(_packet(batch_dir, trial)):
                raise ValueError("Reviewed evidence is missing or changed; cannot report stale ratings")
    return ratings


def report(batch_dir: Path) -> dict:
    """Write JSON and Markdown without pooling clients or selecting best attempts."""
    batch_dir = Path(batch_dir)
    batch = _read(batch_dir / "batch.json")
    trials = _trials(batch_dir)
    ratings = _ratings(batch_dir, trials)
    schedule = batch.get("schedule", [])
    conditions = conditions_of(batch)
    treatments = [c for c in conditions if c != "baseline"]
    clients = sorted({trial["client"] for trial in trials} | {entry["client"] for entry in schedule})
    result = {
        "schema_version": 1, "suite": batch.get("suite"), "seed": batch.get("seed"),
        "provenance": batch.get("provenance", {}),
        "limitations": [
            "Starter fixtures validate this runner; they do not establish benefit on real workloads.",
            "Each attempt is counted; repetitions are not independent tasks and no best attempt is selected.",
            "Clients are reported separately. There is no automatic winning threshold or causal claim.",
            "Complete success rate is unavailable when outcomes/reviews are pending, scheduled trials are unattempted, or attempts are invalid.",
            "Invalid setup/authentication/infrastructure attempts are counted separately from evaluable attempts; timeouts and task failures count as failures.",
            "Usage and time summaries include all observed attempts, including failures; paired deltas use only comparable graded pairs.",
            "Claim accuracy and intervention metrics require human ratings and show observed denominators.",
            "Task success combines acceptance checks with correctness, completeness and scope when reviewed; claims and intervention are separate metrics.",
        ],
        "clients": {},
    }
    if batch.get("config", {}).get("warm_project_index", False):
        result["limitations"].append(
            "Warm-index experiment: both conditions start with generated project maps and graphs. "
            "Initial indexing and a parser-cache verification pass occur before native task timing; "
            "their measurements are saved separately in each trial's index-setup.json. "
            "These results do not measure first-use indexing cost or isolate parser effects.")
    if "indexed" in conditions or "warm_experience" in conditions:
        result["limitations"].append(
            "Deep-index conditions: `indexed` builds or refreshes a deep repository index before each task outside the timer "
            "(deep-index-setup.json); `warm_experience` is the same plus experience its own earlier steps recorded, whose "
            "outcome is the hidden grader's verdict (`grader_passed`, oracle-adjacent) unless configured otherwise. "
            "Paired comparisons are against baseline and, separately, between treatments (`pairs_between_treatments`). Setup cost and model "
            "calls are reported apart from task cost; a break-even is claimed only from measured recurring savings.")
    if any(c in LEARNED_CONDITIONS for c in conditions):
        result["limitations"].append(
            "Learned conditions: each `learned_*` arm is `warm_experience` plus a frozen overlay library imported into the arm's own isolated "
            "store as an explicitly authorized experimental canary (learning-setup.json); observations recorded after each trial carry the hidden "
            "grader's verdict (`hidden_grader`, oracle-adjacent) and unknown overlay exposure. The sequential ladder estimates incremental bundle "
            "effects in its order, not independent component effects; an experimental canary is never a stable measured win, and the library's "
            "own proposal and evaluation costs are outside this report.")
    if any(c in PACKET_CONDITIONS for c in conditions):
        tokens = batch.get("config", {}).get("packet_tokens")
        target = (f"AGENT_DISPATCHER_PACKET_TOKENS={tokens} (config packet_tokens) for both packet arms" if tokens is not None
                  else "not set; both packet arms use the helper's default target")
        result["limitations"].append(
            "Packet-mode conditions: `dispatcher_lean` and `dispatcher_evidence` are the static `dispatcher` arm with "
            "AGENT_DISPATCHER_PACKET=lean or evidence. They are compared with each other by identity pairs "
            "(`pairs_between_treatments`, the earlier condition as reference) and each with baseline. "
            f"Soft packet target: {target}.")
    lines = ["# Agent dispatcher end-to-end evaluation", "", f"Suite: {batch.get('suite', 'unknown')}. Randomization seed: {batch.get('seed', 'unknown')}.", "", *["- " + item for item in result["limitations"]], ""]
    for client in clients:
        subset = [trial for trial in trials if trial["client"] == client]
        client_schedule = [entry for entry in schedule if entry["client"] == client]
        groups = {condition: _group([trial for trial in subset if trial["condition"] == condition], ratings, sum(entry.get("condition") == condition for entry in client_schedule)) for condition in conditions}
        auth = ((batch.get("config") or {}).get("clients") or {}).get(client, {}).get("auth")
        for condition in conditions:
            groups[condition]["setup"] = _setup([trial for trial in subset if trial["condition"] == condition])
            groups[condition]["cost_accounting"] = _cost([trial for trial in subset if trial["condition"] == condition], ratings, auth)
        pairs_by_condition, pairs_between = _all_pairs(subset, ratings, client_schedule, conditions)
        pairs = pairs_by_condition.get("dispatcher") or (pairs_by_condition[treatments[0]] if treatments else _pairs(subset, ratings, client_schedule))
        fixture_categories = {trial["fixture_id"]: trial.get("category", "unknown") for trial in subset}
        categories = {category: {condition: _group([trial for trial in subset if trial.get("category", "unknown") == category and trial["condition"] == condition], ratings, sum(entry.get("condition") == condition and fixture_categories.get(entry.get("fixture_id")) == category for entry in client_schedule)) for condition in conditions} for category in sorted(set(fixture_categories.values()))}
        result["clients"][client] = {"conditions": groups, "pairs": pairs, "pairs_by_condition": pairs_by_condition,
                                     "pairs_between_treatments": pairs_between, "categories": categories,
                                     "route_agreement": _route_agreement(subset), "helper_coverage": _helper_coverage(subset)}
        titles = {"baseline": "Baseline", "dispatcher": "Dispatcher", "dispatcher_lean": "Dispatcher-lean", "dispatcher_evidence": "Dispatcher-evidence",
                  "indexed": "Indexed", "warm_experience": "Warm-experience",
                  "learned_skills": "Learned-skills", "learned_recipes": "Learned-recipes", "learned_global": "Learned-global", "learned_full": "Learned-full"}
        header = "| Metric | " + " | ".join(titles[c] for c in conditions) + " |"
        lines.extend(["## " + client, "", header, "| --- |" + " ---: |" * len(conditions)])
        rows = [("Scheduled", "scheduled"), ("Attempted", "attempted"), ("Unattempted", "unattempted"), ("Invalid attempts", "invalid"), ("Evaluable attempts", "evaluable_attempts"), ("Graded outcomes", "graded"), ("Successful outcomes", "successful"), ("Pending outcomes", "pending_outcomes"), ("Required reviews pending", "required_reviews_pending"), ("Success rate among graded outcomes", "graded_success_rate"), ("Complete success rate", "complete_success_rate")]
        for title, key in rows:
            lines.append(f"| {title} | " + " | ".join(_display(groups[c][key]) for c in conditions) + " |")
        for status in sorted(STATUSES):
            lines.append(f"| Status: {status} | " + " | ".join(str(groups[c]["statuses"][status]) for c in conditions) + " |")
        for title, key in (("Automated artifact acceptance", "artifact_acceptance"), ("Claim accuracy", "claim_accuracy"), ("Unnecessary intervention", "unnecessary_intervention"), ("Treatment compliance", "treatment_compliance"), ("Helper execution (activity helper successes)", "helper_execution"), ("Owned-directory scope acceptance", "scope_acceptance")):
            cells = [f"{groups[condition][key]['numerator']}/{groups[condition][key]['denominator']} observed; {groups[condition][key]['missing']} missing" for condition in conditions]
            lines.append(f"| {title} | " + " | ".join(cells) + " |")
        for name in ("elapsed_seconds", "input_tokens", "output_tokens", "cached_input_tokens", "cost_usd", *SPLIT_USAGE):
            measurements = [groups[condition][name] if name == "elapsed_seconds" else groups[condition]["usage"][name] for condition in conditions]
            cells = [f"{_display(value['median'])} ({value['observed']} observed; {value['missing']} missing)" for value in measurements]
            lines.append(f"| Median {name} | " + " | ".join(cells) + " |")
        for title, key in (("Deep-index setup seconds (median)", "deep_index_setup"), ("Setup model calls (median)", "setup_model_calls")):
            cells = [f"{_display(groups[c]['setup'][key]['median'])} ({groups[c]['setup'][key]['observed']} observed; {groups[c]['setup'][key]['missing']} missing)" for c in conditions]
            lines.append(f"| {title} | " + " | ".join(cells) + " |")
        costs = [groups[c]["cost_accounting"] for c in conditions]
        lines.extend([
            "| Billing basis (auth; runtime costBasis) | " + " | ".join(f"{cost['pricing_mode'] or 'unknown'}; {', '.join(cost['cost_basis']) or 'unknown'}" for cost in costs) + " |",
            "| Arm total (USD, runtime-reported estimate) | " + " | ".join(
                _usd(cost["measured_cost_usd_total"]) if cost["known_partial_cost_usd_total"] is None
                else f"at least {_usd(cost['known_partial_cost_usd_total'])} (lower bound; {cost['cost_unknown_for']} unknown)" for cost in costs) + " |",
            "| Amortized cost per attempt (USD, runtime-reported estimate) | " + " | ".join(_usd(cost["amortized_cost_usd_per_task"]) for cost in costs) + " |",
            "| Cost per verified success (USD, runtime-reported estimate) | " + " | ".join(
                _usd(cost["cost_usd_per_verified_success"]) + (f" ({cost['cost_usd_per_verified_success_reason']})" if cost["cost_usd_per_verified_success_reason"] else "") for cost in costs) + " |",
            "| Invalid attempts (known cost USD) | " + " | ".join(f"{cost['invalid_attempts']} ({_usd(cost['invalid_known_cost_usd'])}; {cost['invalid_cost_unknown_for']} unknown)" for cost in costs) + " |"])
        lines.extend(["", groups["baseline"]["cost_accounting"]["note"], groups["baseline"]["setup"]["note"]])
        lines.extend(["", "### Private process measurements", "", groups["baseline"]["activity"]["note"], "",
                      "| Measurement | " + " | ".join(titles[c] for c in conditions) + " |", "| --- |" + " ---: |" * len(conditions)])
        for name in ACTIVITY_METRICS:
            cells = []
            for condition in conditions:
                metric = groups[condition]["activity"]["metrics"][name]
                cells.append(f"{_display(metric['total'])} total / {metric['observed']} complete; {metric['missing']} missing; {_display(metric['partial_observed_total'])} partial lower bound / {metric['partial_attempts']} attempts")
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
        coverage = result["clients"][client]["helper_coverage"]
        lines.extend(["", "### Helper adoption on eligible tasks", "", coverage["note"], "",
                      "| Helper | Eligible treatment trials | Observed success | Not observed in complete trace | Unknown |", "| --- | ---: | ---: | ---: | ---: |"])
        for name in ("context", "map"):
            observed = coverage[name]
            lines.append(f"| {name} | {observed['eligible']} | {observed['observed_success']} | {observed['not_observed']} | {observed['unknown']} |")
        facts = coverage["map"]
        lines.append(f"Map results among observed uses: {facts['nonempty_facts']} nonempty, {facts['empty_facts']} empty, {facts['facts_unknown']} with unknown fact count.")
        prep = coverage["preparation"]
        attempts = prep["first_attempt"]
        lines.extend(["", prep["note"],
                      f"Successful context preparation: {prep['before_investigation']} before workspace investigation/writes, {prep['after_investigation']} after, {prep['not_observed']} not observed, {prep['unknown']} unknown / {prep['eligible']} eligible.",
                      f"First context attempt: {attempts['early']} early ({attempts['early_failed_or_denied']} failed/denied), {attempts['late']} late, {attempts['not_observed']} not observed, {attempts['unknown']} unknown.",
                      "", coverage["exclusions"]["note"],
                      "Exclusion metadata: " + json.dumps(coverage["exclusions"]["counts"], sort_keys=True)])
        agreement = result["clients"][client]["route_agreement"]
        lines.extend(["", f"Route agreement: {agreement['groups_agreed']}/{agreement['groups_observed']} observed fixture/condition groups agreed; {agreement['groups_varied']} varied; {agreement['unknown_trials']} trials unknown.", agreement["note"]])
        for pairs, details in [(pairs_by_condition.get(name, pairs), True) for name in treatments or ["dispatcher"]] + [(item, False) for item in pairs_between.values()]:
            name, reference = pairs["treatment"], pairs["reference"]
            lines.extend(["", f"Paired outcomes ({name} versus {reference}): {pairs['comparable']}/{pairs['total']} comparable; {pairs['improved']} improved, {pairs['regressed']} regressed, {pairs['both_pass']} both passed, {pairs['both_fail']} both failed. Incomplete: {pairs['missing_attempt']} missing attempts, {pairs['invalid']} invalid pairs, {pairs['pending']} pending.", "", f"| Paired metric ({name} − {reference}) | Median difference | Observed pairs | Missing pairs |", "| --- | ---: | ---: | ---: |"])
            for metric, measurement in pairs["deltas_dispatcher_minus_baseline"].items():
                lines.append(f"| {metric} | {_display(measurement['median'])} | {measurement['observed_pairs']} | {measurement['missing_pairs']} |")
            if not details:
                continue  # between-treatment details stay in report.json
            lines.extend(["", f"### Each paired outcome ({name})", "", "| Fixture | Repetition | Result |", "| --- | ---: | --- |"])
            for detail in pairs["details"]:
                lines.append(f"| {detail['fixture_id']} | {detail['repetition']} | {detail['classification']} |")
        lines.append("")
    _write(batch_dir / "report.json", result)
    (batch_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


# ---------------------------------------------------------------- read-only audit

PROVENANCE = {"verified": "re-derived from saved (redacted) events and equal to the stored value",
              "derived": "computed by this audit (from saved (redacted) events, or from stored values where noted)",
              "stored_only": "stored result value; saved events cannot re-derive it",
              "unavailable": "neither saved events nor stored results provide it"}
# A helper path, or `cd <...>/agent-dispatcher[/scripts] && python3 [-B|-u] [scripts/]<helper>.py`.
_HELPER_COMMAND = re.compile(r"(?:^|[/\\])agent-dispatcher[/\\](?:scripts[/\\])?(?:context|project_map|resources|doctor)\.py\b"
                             r"|\bcd\s+([\"']?)(?:[^\"';&|\n]*[/\\])?agent-dispatcher(?:[/\\]scripts)?[/\\]?\1\s*&&\s*"
                             r"python[\d.]*(?:\s+-[Bu])*\s+(?:scripts[/\\])?(?:context|project_map|resources|doctor)\.py\b")
_OUTPUT_FILTER = re.compile(r"\|\s*(?:head|tail)\b")


def _value(value: Any, provenance: str) -> dict:
    return {"value": value, "provenance": provenance}


def _checked(derived: Any, stored: Any) -> dict:
    """The saved-event re-derivation wins; a different stored value is kept beside it and flagged."""
    if derived is None:
        return _value(stored, "stored_only") if stored is not None else _value(None, "unavailable")
    if stored is None:
        return _value(derived, "derived")
    if derived == stored:
        return _value(derived, "verified")
    return {"value": derived, "stored": stored, "provenance": "derived", "discrepancy": True}


def _events(text: str):
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def _linked_helpers(text: str) -> int | str:
    """Claude helper calls joined to their own tool_result by tool_use_id, judged by the attribution's rule: a call
    succeeds on its exit status, one piped to `head`/`tail` only on the helper's versioned JSON. "redacted" when the
    saved events' redaction left such a result unparseable: no verdict either way."""
    from evals.end_to_end.activity import _payload, _text
    calls, successes = {}, 0
    for event in _events(text):
        message = event.get("message")
        blocks = message.get("content") if isinstance(message, dict) else None
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, dict):
                continue
            command = str(block["input"].get("command", "")) if isinstance(block.get("input"), dict) else ""
            if block.get("type") == "tool_use" and _HELPER_COMMAND.search(command):
                calls[block.get("id")] = bool(_OUTPUT_FILTER.search(command))
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in calls:
                if not calls[block["tool_use_id"]]:
                    successes += not block.get("is_error")
                    continue
                output = _text(block.get("content"))
                payload = _payload(output)
                if payload is None and "[redacted]" in output:
                    return "redacted"
                successes += payload is not None and type(payload.get("schema_version")) is int
    return successes


def _current_attribution(batch_dir: Path, batch: dict, trial: dict, text: str) -> int | None:
    """Today's activity attribution replayed over saved events with a recorded binding (no live path resolution)."""
    from evals.end_to_end import activity
    package = batch_dir.parent.parent / "packages" / trial["client"]
    profile = ((batch.get("config") or {}).get("clients") or {}).get(trial["client"], {}).get("profile_dir")
    cwd = next((event.get("cwd") for event in _events(text) if event.get("type") == "system" and event.get("subtype") == "init"), None)
    # ponytail: Claude only (Codex stages the package inside the removed workspace); add a Codex binding when a Codex batch needs auditing.
    if trial["client"] != "claude" or trial["condition"] == "baseline" or not package.is_dir() or not isinstance(profile, str) or not isinstance(cwd, str):
        return None
    staged = activity.bind(package, package)
    recorded = profile.rstrip("/") + "/skills/agent-dispatcher"
    binding = activity.Bindings(cwd, recorded, {recorded + "/" + relative: relative for relative in staged.files.values()},
                                staged.roles, staged.aliases, recorded=True)
    return activity.analyze(trial["client"], text, binding)["summary"]["helper_successes"]


def _audit_trial(batch_dir: Path, batch: dict, trial: dict, rating: dict | None) -> dict:
    from evals.end_to_end.adapters import RUNTIME_KEYS, USAGE_KEYS, parse_events
    raw = trial.get("artifact_dir")
    path = batch_dir / raw / "events.jsonl" if isinstance(raw, str) and raw and not Path(raw).is_absolute() and ".." not in Path(raw).parts else None
    text = path.read_text(encoding="utf-8", errors="replace") if path is not None and path.is_file() and not path.is_symlink() else None
    parsed = parse_events(trial["client"], text) if text is not None else {"usage": {}, "runtime": {}, "treatment_invoked": None}
    treated = trial["condition"] != "baseline"
    record = trial.get("activity") or {}
    stored_helpers = (record.get("summary") or {}).get("helper_successes") if record.get("schema_version") == 1 else None
    linked = _linked_helpers(text) if text is not None and trial["client"] == "claude" else None
    if linked == "redacted":  # no linked verdict, so no discrepancy or resolution flag either
        linked, linked_events = None, {"value": None, "provenance": "unavailable", "reason": "redacted"}
    else:
        linked_events = _value(linked, "derived" if linked is not None else "unavailable")
    current = _current_attribution(batch_dir, batch, trial, text) if text is not None else None
    auto, scope = trial.get("auto_grade") or {}, trial.get("scope_check") or {}
    row = {key: trial.get(key) for key in ("id", "client", "condition", "fixture_id", "repetition")}
    row.update(
        events="available" if text is not None else "unavailable",
        usage={key: _checked(parsed["usage"].get(key), (trial.get("usage") or {}).get(key)) for key in USAGE_KEYS},
        runtime={key: _checked(parsed["runtime"].get(key), (trial.get("runtime") or {}).get(key)) for key in RUNTIME_KEYS},
        auth=_checked(None, (trial.get("effective_settings") or {}).get("auth")),
        status=_value(trial.get("status"), "stored_only"), task_success=_value(trial.get("task_success"), "stored_only"),
        outcome=_value(_outcome(trial, rating), "derived"),
        auto_grade_failures=_value([check.get("name") for check in auto.get("checks", []) if isinstance(check, dict) and check.get("passed") is False], "stored_only"),
        scope_failure_reason=_value(scope.get("reason") if scope and scope.get("passed") is not True else None, "stored_only"),
        treatment_invoked=_checked(parsed["treatment_invoked"] if treated else None, trial.get("treatment_invoked")),
        helper_successes={"linked_events": linked_events,
                          "stored_activity": _checked(None, stored_helpers),
                          "current_attribution": _value(current, "derived" if current is not None else "unavailable")})
    helper = row["helper_successes"]
    helper["discrepancy"] = linked is not None and stored_helpers is not None and linked != stored_helpers
    helper["resolved_by_current_attribution"] = (current == linked) if helper["discrepancy"] and current is not None else None
    row["discrepancies"] = ([f"usage.{key}" for key, item in row["usage"].items() if item.get("discrepancy")]
                            + [f"runtime.{key}" for key, item in row["runtime"].items() if item.get("discrepancy")]
                            + ["treatment_invoked"] * bool(row["treatment_invoked"].get("discrepancy")) + ["helper_successes"] * helper["discrepancy"])
    return row


def _totals(trials: list[dict]) -> dict:
    """Unrounded totals; a total is null when any value is unknown, and the known part is then a lower bound."""
    result = {}
    for key in ("cost_usd", "uncached_input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"):
        values = [(trial.get("usage") or {}).get(key) for trial in trials]
        known = [value for value in values if _number(value)]
        result[key] = {"total": _sum(known) if known and len(known) == len(values) else None,
                       "known_partial_total": _sum(known) if known else None, "unknown_for": len(values) - len(known)}
    return result


def audit(batch_dirs: list[Path]) -> dict:
    """Re-derive accounting from saved (redacted) events and stored results. Reads only; never writes into a batch."""
    from evals.end_to_end.adapters import RUNTIME_KEYS, USAGE_KEYS
    batches, everything = [], []
    for batch_dir in map(Path, batch_dirs):
        batch = _read(batch_dir / "batch.json")
        trials = _trials(batch_dir)
        ratings = _ratings(batch_dir, trials)
        rows = [_audit_trial(batch_dir, batch, trial, ratings.get(trial["id"])) for trial in trials]
        # Stored trials with every re-derivable value replaced by the audited one, so shared report logic runs on it.
        resolved = [dict(trial, usage={key: row["usage"][key]["value"] for key in USAGE_KEYS},
                         runtime={key: row["runtime"][key]["value"] for key in RUNTIME_KEYS}) for trial, row in zip(trials, rows)]
        everything += resolved
        schedule, conditions = batch.get("schedule", []), conditions_of(batch)
        clients = {}
        for client in sorted({trial["client"] for trial in trials} | {entry["client"] for entry in schedule}):
            subset = [trial for trial in resolved if trial["client"] == client]
            planned = [entry for entry in schedule if entry["client"] == client]
            auth = ((batch.get("config") or {}).get("clients") or {}).get(client, {}).get("auth")
            arms = {}
            for condition in conditions:
                arm = [trial for trial in subset if trial["condition"] == condition]
                arm_rows = [row for row in rows if row["client"] == client and row["condition"] == condition]
                invalid = sum(trial["status"] in INVALID_STATUSES for trial in arm)
                arms[condition] = {
                    "scheduled": _value(sum(entry.get("condition") == condition for entry in planned), "stored_only"),
                    "counts": {"provenance": "derived", "attempted": len(arm), "evaluable": len(arm) - invalid, "invalid": invalid,
                               "verified_successes": sum(_outcome(trial, ratings.get(trial["id"])) is True for trial in arm)},
                    "totals": {"provenance": "derived", "cost_input_provenance": dict(Counter(row["usage"]["cost_usd"]["provenance"] for row in arm_rows)), **_totals(arm)},
                    "medians": {"provenance": "derived", **{key: _measurement([(trial.get("usage") or {}).get(key) for trial in arm])["median"] for key in USAGE_KEYS if key not in ("cost_source", "cost_basis")},
                                **{key: _measurement([trial["runtime"][key] for trial in arm])["median"] for key in RUNTIME_KEYS},
                                "elapsed_seconds": _measurement([trial.get("elapsed_seconds") for trial in arm])["median"]},
                    "cost": {"provenance": "derived", **_cost(arm, ratings, auth)}}
            by_condition, between = _all_pairs(subset, ratings, planned, conditions)
            clients[client] = {"arms": arms, "pairs": {"provenance": "derived", "vs_baseline": by_condition, "between_treatments": between}}
        batches.append({"batch": str(batch_dir), "suite": batch.get("suite"), "trials": rows, "clients": clients,
                        "totals": {"provenance": "derived", **_totals(resolved)},
                        "discrepancies": [{"trial": row["id"], "fields": row["discrepancies"]} for row in rows if row["discrepancies"]]})
    result = {"schema_version": 1, "read_only": True, "provenance_labels": PROVENANCE,
              "note": "Costs are runtime-reported list-price estimates (total_cost_usd), not billed spend; see each arm's cost.pricing_mode. "
                      "JSON numbers are unrounded.", "batches": batches}
    if len(batches) > 1:
        result["combined"] = {"label": "sum across batches; not an experimental estimate", "provenance": "derived",
                              "batches": len(batches), "trials": len(everything), **_totals(everything)}
    return result
