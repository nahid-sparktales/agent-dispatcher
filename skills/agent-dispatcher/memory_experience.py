"""Experience memory: attributable task observations, scoped outcomes, corrections and forgetting.

A record says what was observed about one task, never what was proven: which files were
retrieved, delivered, read (when the host exposes reads), modified, which hypotheses were tried,
what a verification receipt actually recorded, and an outcome from a fixed vocabulary.
`verified_scoped_success` is reachable only through a trusted verification receipt whose
observed test run passed and is still current; an agent or user saying "tests passed" stays an
assertion. Recording is passive and explicit (a caller hands in observations); nothing here
watches a session, runs a command or reads model output.

Retrieval is a separate switch. Corrections are new records that supersede older ones; forgetting
removes a record and the records that superseded it. Both are logical deletions in a local file,
not secure erasure from backups.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import time

SCHEMA = 1
OUTCOMES = ("unknown", "in_progress", "abandoned", "partial", "failed_verification", "verified_scoped_success",
            "reverted_or_invalidated")
ASSERTABLE = ("unknown", "in_progress", "abandoned", "partial", "failed_verification", "reverted_or_invalidated")
POSITIVE = {"verified_scoped_success": 1.0, "partial": 0.6, "unknown": 0.35, "in_progress": 0.2}
CATEGORIES = ("bug", "feature", "refactor", "test", "docs", "performance", "security", "investigation", "other")
MAX_TASK_CHARS = 600
MAX_PATHS = 50
MAX_HYPOTHESES = 8
MAX_TEXT = 200
MAX_EVENTS = 2000
MAX_ASSERTIONS = 8
RECORD_ID = re.compile(r"[0-9a-f]{24}\Z")
HEX = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class ExperienceError(ValueError):
    """Bounded diagnostic; never echoes task text or file contents."""


_SIBLINGS = {}


def _sibling(name):
    if name not in _SIBLINGS:
        path = Path(__file__).resolve().with_name(name + ".py")
        namespace = {"__name__": "_dispatcher_experience_" + name, "__file__": str(path)}
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
        _SIBLINGS[name] = namespace
    return _SIBLINGS[name]


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _text(value, scrub, limit):
    if not isinstance(value, str):
        return ""
    clean = "".join(c for c in value if c == "\n" or ord(c) >= 32 and ord(c) != 127)
    return scrub(re.sub(r"[ \t]+", " ", clean)).strip()[:limit]


def _paths(values, admit, *, limit=MAX_PATHS):
    """Admitted, safe, deduplicated project paths; the count of what was dropped, never the names."""
    if values is None:
        return None, 0
    if not isinstance(values, (list, tuple)):
        raise ExperienceError("Path lists must be lists of project-relative paths.")
    history = _sibling("repo_history")
    kept, dropped = [], 0
    for value in values:
        if isinstance(value, str) and history["safe_path"](value) and admit(value) is None and value not in kept:
            kept.append(value)
        else:
            dropped += 1
    return kept[:limit], dropped + max(0, len(kept) - limit)


def fingerprint(task):
    return hashlib.sha256(re.sub(r"\s+", " ", (task or "").strip().lower()).encode("utf-8")).hexdigest()[:16]


def outcome_from_receipt(inspection):
    """What a verification receipt actually observed -> (outcome, observed, limitations).

    Only an observed execution whose tests passed and whose snapshot is still current proves a
    scoped success; a stale or partial receipt is `partial`, a failed run `failed_verification`,
    and a receipt with notes only is `unknown`.
    """
    observations = [o for o in inspection.get("observations", []) if o.get("provenance") == "observed_execution"]
    if not observations:
        return "unknown", None, ["receipt contains no observed execution"]
    latest = observations[-1]
    execution = latest.get("execution") or {}
    observed = {"label": latest.get("label"), "outcome": latest.get("outcome"), "freshness": latest.get("freshness"),
                "runner": execution.get("runner"), "exit_code": execution.get("exit_code"),
                "test_counts": execution.get("test_counts"), "command": (execution.get("command") or {}).get("argv", [])[:12],
                "output_sha256": execution.get("output_sha256"), "recorded_at_unix": latest.get("recorded_at_unix"),
                "changed_during_check": latest.get("changed_during_check")}
    limitations = ["counts are runner reports, not behavioral coverage"]
    if latest.get("outcome") in {"tests_failed", "command_failed", "timeout", "launch_failed"}:
        return "failed_verification", observed, limitations
    if latest.get("outcome") == "tests_passed":
        if latest.get("freshness") == "current":
            return "verified_scoped_success", observed, limitations + ["scoped to the checked command and snapshot"]
        return "partial", observed, limitations + [f"receipt freshness is {latest.get('freshness')}; files changed after the check"]
    return "partial", observed, limitations + ["the check ran but reported no passing test count"]


def new_record(observation, *, admit, scrub, hashes, snapshot_commit=None, inspection=None, now=None):
    """Validate one ingested observation into a bounded, sanitized record."""
    if not isinstance(observation, dict):
        raise ExperienceError("An observation must be a JSON object.")
    task = _text(observation.get("task"), scrub, MAX_TASK_CHARS)
    if not task:
        raise ExperienceError("An observation needs task text.")
    category = observation.get("category", "other")
    if category not in CATEGORIES:
        raise ExperienceError("Unknown task category.")
    record = {"schema": SCHEMA, "kind": "task", "recorded_at": int(now if now is not None else time.time()),
              "task": task, "task_fingerprint": fingerprint(task), "category": category,
              "snapshot_commit": snapshot_commit if isinstance(snapshot_commit, str) and HEX.fullmatch(snapshot_commit) else None}
    dropped = {}
    for field in ("retrieved", "delivered", "read", "modified"):
        record[field], dropped[field] = _paths(observation.get(field), admit)
        if field != "read" and record[field] is None:
            record[field] = []
    record["withheld_paths"] = {k: v for k, v in dropped.items() if v}
    record["modified_fingerprints"] = {path: hashes[path] for path in record["modified"] if path in hashes}
    hypotheses = observation.get("hypotheses") or []
    if not isinstance(hypotheses, list):
        raise ExperienceError("Hypotheses must be a list of short strings.")
    record["hypotheses"] = [h for h in (_text(v, scrub, MAX_TEXT) for v in hypotheses[:MAX_HYPOTHESES]) if h]
    assertions = observation.get("assertions") or []
    if not isinstance(assertions, list):
        raise ExperienceError("Assertions must be a list.")
    record["assertions"] = [{"by": a.get("by") if a.get("by") in {"user", "agent", "host"} else "agent",
                             "claim": _text(a.get("claim"), scrub, MAX_TEXT)}
                            for a in assertions[:MAX_ASSERTIONS] if isinstance(a, dict) and _text(a.get("claim"), scrub, MAX_TEXT)]
    asserted = observation.get("outcome", "unknown")
    if asserted not in ASSERTABLE:
        raise ExperienceError("Outcome must be one of the assertable outcomes; verified success needs a receipt.")
    limitations = [l for l in (_text(v, scrub, MAX_TEXT) for v in (observation.get("limitations") or [])[:8]) if l]
    if inspection is not None:
        outcome, observed, notes = outcome_from_receipt(inspection)
        record["verification"] = {"source": "receipt", "observed": observed}
        limitations += notes
        if asserted in {"abandoned", "reverted_or_invalidated"}:
            outcome = asserted
    else:
        outcome = asserted
        record["verification"] = {"source": "asserted" if record["assertions"] or asserted != "unknown" else "none", "observed": None}
        if any(a["by"] == "user" for a in record["assertions"]):
            record["verification"]["source"] = "user_asserted"
    record["outcome"] = outcome
    tests = [p for p in record["modified"] if _sibling("repo_index")["is_test"](p)]
    record["tests_changed"] = bool(tests)
    if tests and outcome == "verified_scoped_success":
        limitations.append("verification tests were modified in this task; passing them is not independent evidence")
    record["limitations"] = limitations[:12]
    linked = observation.get("linked_commit")
    record["linked_commit"] = linked if isinstance(linked, str) and HEX.fullmatch(linked) else None
    record["supersedes"], record["superseded_by"] = None, None
    record["record_id"] = _digest({k: v for k, v in record.items() if k not in {"record_id"}})[:24]
    return record


def valid_record(record):
    keys = {"schema", "kind", "recorded_at", "task", "task_fingerprint", "category", "snapshot_commit", "retrieved", "delivered",
            "read", "modified", "withheld_paths", "modified_fingerprints", "hypotheses", "assertions", "verification", "outcome",
            "tests_changed", "limitations", "linked_commit", "supersedes", "superseded_by", "record_id"}
    if (not isinstance(record, dict) or not keys <= set(record) or record["schema"] != SCHEMA or record["kind"] not in {"task", "correction"}
            or record["outcome"] not in OUTCOMES or not isinstance(record["task"], str) or len(record["task"]) > MAX_TASK_CHARS
            or not RECORD_ID.fullmatch(record["record_id"]) or type(record["recorded_at"]) is not int):
        return False
    history = _sibling("repo_history")
    for field in ("retrieved", "delivered", "read", "modified"):
        value = record[field]
        if value is None and field == "read":
            continue
        if not isinstance(value, list) or len(value) > MAX_PATHS or any(not history["safe_path"](p) for p in value):
            return False
    for field in ("supersedes", "superseded_by"):
        if record[field] is not None and not RECORD_ID.fullmatch(str(record[field])):
            return False
    return True


def correction(records, record_id, *, outcome, note, scrub, now=None):
    """A superseding record: the prior observation stays; the correction explains what changed."""
    target = next((r for r in records if r["record_id"] == record_id), None)
    if target is None:
        raise ExperienceError("Unknown experience record.")
    if outcome not in ASSERTABLE:
        raise ExperienceError("A correction must use an assertable outcome.")
    fixed = dict(target, kind="correction", recorded_at=int(now if now is not None else time.time()), outcome=outcome,
                 supersedes=record_id, superseded_by=None, assertions=(target["assertions"] + [{"by": "user", "claim": _text(note, scrub, MAX_TEXT)}])[-MAX_ASSERTIONS:],
                 verification={"source": "user_asserted", "observed": target["verification"].get("observed")},
                 limitations=(target["limitations"] + ["corrected by the user; earlier outcome superseded"])[-12:])
    fixed["record_id"] = _digest({k: v for k, v in fixed.items() if k != "record_id"})[:24]
    target["superseded_by"] = fixed["record_id"]
    return fixed


def forget(records, record_id):
    """Remove a record and every correction that superseded it -> (remaining, removed ids)."""
    if not any(r["record_id"] == record_id for r in records):
        raise ExperienceError("Unknown experience record.")
    removed, remaining = set(), []
    pending = {record_id}
    while pending:
        current = pending.pop()
        removed.add(current)
        pending.update(r["record_id"] for r in records if r.get("supersedes") == current and r["record_id"] not in removed)
    for record in records:
        if record["record_id"] in removed:
            continue
        if record.get("superseded_by") in removed:
            record = dict(record, superseded_by=None)
        remaining.append(record)
    return remaining, sorted(removed)


def prune(records, *, max_events=MAX_EVENTS, max_age_days=None, now=None):
    now = int(now if now is not None else time.time())
    kept = [r for r in records if max_age_days is None or now - r["recorded_at"] <= max_age_days * 86400]
    kept.sort(key=lambda r: r["recorded_at"])
    kept = kept[-max_events:]
    ids = {r["record_id"] for r in kept}
    kept = [dict(r, superseded_by=r["superseded_by"] if r.get("superseded_by") in ids else None) for r in kept
            if r.get("supersedes") is None or r["supersedes"] in ids]
    return kept, len(records) - len(kept)


# ---------------------------------------------------------------- retrieval


def _terms(text):
    index = _sibling("repo_index")
    counts = Counter()
    for identifier in index["IDENT"].findall(text or ""):
        for term in index["expand"](identifier):
            counts[term] += 1
    return counts


def search(query, records, index, *, top_k=5, k1=1.2, b=0.75):
    """BM25 over sanitized task text and hypotheses, weighted by outcome quality and source freshness.

    Superseded records vote through their correction. A failed or reverted record can still match
    (its files are listed as caution), but it never lends a file positive support.
    """
    live = [r for r in records if not r.get("superseded_by")]
    if not live or not query.get("terms"):
        return []
    docs = {r["record_id"]: _terms(r["task"] + " " + " ".join(r.get("hypotheses", []))) for r in live}
    lengths = {rid: sum(c.values()) for rid, c in docs.items()}
    average = sum(lengths.values()) / len(lengths) or 1.0
    df = Counter(term for counts in docs.values() for term in counts)
    size = len(live)
    hashes = getattr(index, "hashes", {})
    current = set(index.paths)
    items = []
    for record in live:
        counts, matched, score = docs[record["record_id"]], [], 0.0
        for term, weight in query["terms"].items():
            frequency = counts.get(term)
            if not frequency:
                continue
            idf = math.log(1 + (size - df[term] + 0.5) / (df[term] + 0.5))
            norm = frequency + k1 * (1 - b + b * lengths[record["record_id"]] / average)
            score += weight * idf * frequency * (k1 + 1) / norm
            matched.append(term)
        if score <= 0:
            continue
        prints = record.get("modified_fingerprints", {})
        fresh = sum(1 for p, h in prints.items() if hashes.get(p) == h)
        freshness = "compatible" if prints and fresh == len(prints) else "partially_changed" if fresh else "changed" if prints else "unknown"
        files = [p for p in record["modified"] if p in current]
        observed = [p for p in (record.get("read") or []) if p in current and p not in files]
        weight = POSITIVE.get(record["outcome"], 0.0) * {"compatible": 1.0, "partially_changed": 0.7, "changed": 0.4, "unknown": 0.6}[freshness]
        items.append({"record_id": record["record_id"], "kind": record["kind"], "score": round(score, 4), "matched": matched[:8],
                      "outcome": record["outcome"], "verification": record["verification"]["source"], "freshness": freshness,
                      "files": files, "read": observed[:10], "weight": round(weight, 4), "category": record["category"],
                      "hypotheses": record.get("hypotheses", [])[:3], "tests_changed": record.get("tests_changed"),
                      "task_fingerprint": record["task_fingerprint"], "caution": weight == 0.0, "supersedes": record.get("supersedes")})
    items.sort(key=lambda item: (-item["score"], item["record_id"]))
    return items[:top_k]


def candidates(items, *, max_records=5, max_files=8):
    """Fusion rows from positive experiences: one vote per file per incident, never per repeated narrative."""
    best = defaultdict(dict)
    for rank, item in enumerate(items[:max_records], 1):
        if item["caution"]:
            continue
        for path in item["files"][:max_files]:
            gain = item["weight"] * item["score"] / (1 + rank)
            group = item["task_fingerprint"]
            if gain > best[path].get(group, 0.0):
                best[path][group] = gain
    scores = {path: sum(groups.values()) for path, groups in best.items()}
    rows = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"file": path, "rank": rank, "score": round(score, 4), "source": "memory_experience",
             "reason": "modified in a recorded task with a compatible outcome (experience, not proof of relevance)", "value": path}
            for rank, (path, score) in enumerate(rows, 1)]
