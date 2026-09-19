"""Blind human review and reproducible, within-client paired evaluation reports.

Review values are booleans: correctness/completeness/scope mean "passes";
unsupported_claims/unnecessary_intervention mean "issue present". All five
values must be supplied for a reviewed packet. An all-null row remains pending.
Imports may contain a subset of packets and never erase ratings for other rows.
"""

from __future__ import annotations

import hashlib
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
        if trial.get("condition") not in CONDITIONS or trial.get("status") not in STATUSES:
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


def _packet(batch_dir: Path, trial: dict) -> dict:
    files, omissions = _artifacts(batch_dir, trial)
    rubric = trial.get("rubric", {})
    # Round-trip sanitization handles both prose and per-dimension rubric structures.
    blinded_rubric = json.loads(_blind(json.dumps(rubric, ensure_ascii=False), trial, batch_dir))
    return {
        "prompt": _blind(re.sub(r"^\s*[$/]agent-dispatcher\b\s*", "", str(trial.get("prompt", ""))), trial, batch_dir),
        "acceptance": [_blind(str(item), trial, batch_dir) for item in trial.get("acceptance", [])],
        "rubric": blinded_rubric,
        "final_answer": _blind(str(trial.get("final_answer", "")), trial, batch_dir, announcements=True),
        "artifacts": files,
        "omissions": omissions,
        "verification_evidence": _verification(batch_dir, trial),
    }


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


def _measurement(values: list[Any]) -> dict:
    observed = [value for value in values if _number(value)]
    return {
        "observed": len(observed), "missing": len(values) - len(observed),
        "median": statistics.median(observed) if observed else None,
        "total_observed": sum(observed) if observed else None,
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
        "treatment_compliance": _rate([trial.get("treatment_invoked") for trial in trials if trial["condition"] == "dispatcher"]),
        "elapsed_seconds": _measurement([trial.get("elapsed_seconds") for trial in trials]),
        "usage": {name: _measurement([(trial.get("usage") or {}).get(name) for trial in trials]) for name in ("input_tokens", "output_tokens", "cached_input_tokens", "cost_usd")},
    }


def _pairs(trials: list[dict], ratings: dict, schedule: list[dict]) -> dict:
    pairs: dict[tuple, dict] = defaultdict(dict)
    for trial in trials:
        pairs[(trial.get("fixture_id"), trial.get("repetition"))][trial["condition"]] = trial
    for entry in schedule:
        pairs[(entry.get("fixture_id"), entry.get("repetition"))]
    totals = Counter()
    details, deltas = [], defaultdict(list)
    for (fixture_id, repetition), pair in sorted(pairs.items(), key=lambda item: str(item[0])):
        baseline, treatment = pair.get("baseline"), pair.get("dispatcher")
        left = _outcome(baseline, ratings.get(baseline["id"])) if baseline else None
        right = _outcome(treatment, ratings.get(treatment["id"])) if treatment else None
        if not baseline or not treatment:
            classification = "missing_attempt"
        elif baseline["status"] in INVALID_STATUSES or treatment["status"] in INVALID_STATUSES:
            classification = "invalid"
        elif left is None or right is None:
            classification = "pending"
        else:
            classification = "both_pass" if left and right else "both_fail" if not left and not right else "improved" if right else "regressed"
            for name in ("elapsed_seconds", "input_tokens", "output_tokens", "cached_input_tokens", "cost_usd"):
                lhs = baseline.get(name) if name == "elapsed_seconds" else (baseline.get("usage") or {}).get(name)
                rhs = treatment.get(name) if name == "elapsed_seconds" else (treatment.get("usage") or {}).get(name)
                if _number(lhs) and _number(rhs):
                    deltas[name].append(rhs - lhs)
        totals[classification] += 1
        details.append({"fixture_id": fixture_id, "repetition": repetition, "classification": classification, "baseline_success": left, "dispatcher_success": right})
    comparable = sum(totals[name] for name in ("improved", "regressed", "both_pass", "both_fail"))
    return {
        "total": len(pairs), "comparable": comparable,
        **{name: totals[name] for name in ("improved", "regressed", "both_pass", "both_fail", "missing_attempt", "invalid", "pending")},
        "deltas_dispatcher_minus_baseline": {name: {"observed_pairs": len(deltas[name]), "missing_pairs": comparable - len(deltas[name]), "median": statistics.median(deltas[name]) if deltas[name] else None} for name in ("elapsed_seconds", "input_tokens", "output_tokens", "cached_input_tokens", "cost_usd")},
        "details": details,
    }


def _display(value: Any) -> str:
    return "unavailable" if value is None else format(value, ".3f") if isinstance(value, float) else str(value)


def report(batch_dir: Path) -> dict:
    """Write JSON and Markdown without pooling clients or selecting best attempts."""
    batch_dir = Path(batch_dir)
    batch = _read(batch_dir / "batch.json")
    trials = _trials(batch_dir)
    ratings = _read(batch_dir / "review-ratings.json", {"ratings": {}})["ratings"]
    if ratings:
        mapping = _read(batch_dir / "review-map.json")["packets"]
        by_id = {trial["id"]: trial for trial in trials}
        for trial_id, rating in ratings.items():
            evidence = mapping.get(rating.get("packet_id"), {})
            trial = by_id.get(trial_id)
            if not trial or evidence.get("trial_id") != trial_id or evidence.get("digest") != _digest(_packet(batch_dir, trial)):
                raise ValueError("Reviewed evidence is missing or changed; cannot report stale ratings")
    schedule = batch.get("schedule", [])
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
    lines = ["# Agent dispatcher end-to-end evaluation", "", f"Suite: {batch.get('suite', 'unknown')}. Randomization seed: {batch.get('seed', 'unknown')}.", "", *["- " + item for item in result["limitations"]], ""]
    for client in clients:
        subset = [trial for trial in trials if trial["client"] == client]
        client_schedule = [entry for entry in schedule if entry["client"] == client]
        groups = {condition: _group([trial for trial in subset if trial["condition"] == condition], ratings, sum(entry.get("condition") == condition for entry in client_schedule)) for condition in CONDITIONS}
        pairs = _pairs(subset, ratings, client_schedule)
        fixture_categories = {trial["fixture_id"]: trial.get("category", "unknown") for trial in subset}
        categories = {category: {condition: _group([trial for trial in subset if trial.get("category", "unknown") == category and trial["condition"] == condition], ratings, sum(entry.get("condition") == condition and fixture_categories.get(entry.get("fixture_id")) == category for entry in client_schedule)) for condition in CONDITIONS} for category in sorted(set(fixture_categories.values()))}
        result["clients"][client] = {"conditions": groups, "pairs": pairs, "categories": categories}
        lines.extend(["## " + client, "", "| Metric | Baseline | Dispatcher |", "| --- | ---: | ---: |"])
        rows = [("Scheduled", "scheduled"), ("Attempted", "attempted"), ("Unattempted", "unattempted"), ("Invalid attempts", "invalid"), ("Evaluable attempts", "evaluable_attempts"), ("Graded outcomes", "graded"), ("Successful outcomes", "successful"), ("Pending outcomes", "pending_outcomes"), ("Required reviews pending", "required_reviews_pending"), ("Success rate among graded outcomes", "graded_success_rate"), ("Complete success rate", "complete_success_rate")]
        for title, key in rows:
            lines.append(f"| {title} | {_display(groups['baseline'][key])} | {_display(groups['dispatcher'][key])} |")
        for status in sorted(STATUSES):
            lines.append(f"| Status: {status} | {groups['baseline']['statuses'][status]} | {groups['dispatcher']['statuses'][status]} |")
        for title, key in (("Automated artifact acceptance", "artifact_acceptance"), ("Claim accuracy", "claim_accuracy"), ("Unnecessary intervention", "unnecessary_intervention"), ("Treatment compliance", "treatment_compliance")):
            cells = [f"{groups[condition][key]['numerator']}/{groups[condition][key]['denominator']} observed; {groups[condition][key]['missing']} missing" for condition in CONDITIONS]
            lines.append(f"| {title} | {cells[0]} | {cells[1]} |")
        for name in ("elapsed_seconds", "input_tokens", "output_tokens", "cached_input_tokens", "cost_usd"):
            measurements = [groups[condition][name] if name == "elapsed_seconds" else groups[condition]["usage"][name] for condition in CONDITIONS]
            cells = [f"{_display(value['median'])} ({value['observed']} observed; {value['missing']} missing)" for value in measurements]
            lines.append(f"| Median {name} | {cells[0]} | {cells[1]} |")
        lines.extend(["", f"Paired outcomes: {pairs['comparable']}/{pairs['total']} comparable; {pairs['improved']} improved, {pairs['regressed']} regressed, {pairs['both_pass']} both passed, {pairs['both_fail']} both failed. Incomplete: {pairs['missing_attempt']} missing attempts, {pairs['invalid']} invalid pairs, {pairs['pending']} pending.", "", "| Paired metric (dispatcher − baseline) | Median difference | Observed pairs | Missing pairs |", "| --- | ---: | ---: | ---: |"])
        for name, measurement in pairs["deltas_dispatcher_minus_baseline"].items():
            lines.append(f"| {name} | {_display(measurement['median'])} | {measurement['observed_pairs']} | {measurement['missing_pairs']} |")
        lines.extend(["", "### Each paired outcome", "", "| Fixture | Repetition | Result |", "| --- | ---: | --- |"])
        for detail in pairs["details"]:
            lines.append(f"| {detail['fixture_id']} | {detail['repetition']} | {detail['classification']} |")
        lines.append("")
    _write(batch_dir / "report.json", result)
    (batch_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result
