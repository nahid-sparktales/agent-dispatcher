"""Task experience: bounded events from real task lifecycles, corrections, forgetting, and a transparent memory retriever.

An event records what happened, not what was proven: which files were retrieved, inspected and
edited, what the scoped checks reported, and an outcome category whose definition is fixed below.
Recording is explicit (a host or harness hands the lifecycle artifacts to `record`); nothing here
observes a session, reads model output or captures conversations. Using experience at query time
is a separate switch, so events can be recorded for shadow evaluation without influencing anything.

Associations are what was observed (`changed_in_checked_task`), never a causal label. A passing
suite says the final state passed those checks; it does not say every edited file was needed.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import time

VERSION = 1
OUTCOMES = {
    "checked_success": "scoped checks passed on the final state and their receipt was still current",
    "accepted": "the user explicitly accepted the result",
    "grader_passed": "an external harness grader passed the final state; oracle-adjacent, eligible only by harness decision",
    "exit_code_only": "a command exited 0 without a recognized test summary; not a verified success",
    "zero_tests": "the check ran no tests; not a verified success",
    "stale_checks": "checks passed but files changed afterwards; not a verified success",
    "unresolved": "the task ended without a checked or accepted result",
    "failed_checks": "scoped checks failed on the final state",
    "infrastructure_error": "the run or its checks could not complete for reasons unrelated to the task",
    "cancelled": "the task was interrupted",
    "insufficient_evidence": "no check, acceptance or failure evidence was supplied",
    "reverted_or_invalidated": "a later revert, correction or refactor invalidated the recorded result",
}
# The repository-memory vocabulary maps onto these categories; nothing here can assert a verified success.
ALIASES = {"unknown": "insufficient_evidence", "in_progress": "unresolved", "partial": "unresolved", "abandoned": "cancelled",
           "failed_verification": "failed_checks", "user_accepted": "accepted"}
ASSERTABLE = tuple(sorted((set(OUTCOMES) | set(ALIASES)) - {"checked_success", "grader_passed", "verified_scoped_success"}))
ELIGIBLE = ("checked_success", "accepted")
MAX_NOTES = 8
MAX_NOTE = 200
MAX_FILES = 200
MAX_SUMMARY = 240
MAX_TERMS = 200


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


def _safe_path(value):
    return (isinstance(value, str) and 0 < len(value) <= 1024 and not PurePosixPath(value).is_absolute()
            and ".." not in PurePosixPath(value).parts and PurePosixPath(value).as_posix() == value
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def task_representation(task, scrub):
    """A sanitized, bounded stand-in for the request: weighted terms, named things, a short summary. No raw prose retained."""
    if not isinstance(task, str) or not task.strip():
        raise ExperienceError("Experience needs the task text to derive a representation.")
    text = scrub(task)[:16000]
    query = _sibling("retrieval")["analyze_query"](text)
    terms = dict(sorted(query["terms"].items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_TERMS])
    return {"digest": hashlib.sha256(text.encode("utf-8")).hexdigest(), "terms": terms,
            "symbols": (query["symbols"] + query["identifiers"])[:40], "paths": query["paths"][:12],
            "summary": " ".join(text.split())[:MAX_SUMMARY]}


def outcome_from_receipt(inspection):
    """Map a verification.py inspection (observations with freshness) to an outcome category, conservatively."""
    observations = [o for o in (inspection or {}).get("observations", []) if o.get("provenance") == "observed_execution"]
    if not observations:
        return "insufficient_evidence", "no observed check execution in the receipt"
    last = observations[-1]
    outcome, freshness = last.get("outcome"), last.get("freshness")
    if outcome == "tests_passed":
        if freshness == "current":
            return "checked_success", "tests passed and the receipt is current"
        return "stale_checks", f"tests passed but receipt freshness is {freshness}"
    if outcome in ("tests_failed", "command_failed"):
        return "failed_checks", outcome
    if outcome == "zero_tests":
        return "zero_tests", "the recognized runner ran no tests"
    if outcome in ("command_succeeded", "executed_unknown"):
        return "exit_code_only", outcome
    if outcome in ("timeout", "denied", "launch_failed", "not_run"):
        return "infrastructure_error", outcome
    return "insufficient_evidence", str(outcome)


def normalize_outcome(value):
    """An asserted outcome in either vocabulary -> canonical category; verified success is never assertable."""
    if value in ("checked_success", "grader_passed", "verified_scoped_success"):
        raise ExperienceError("Verified success cannot be asserted; supply a verification receipt instead.")
    outcome = ALIASES.get(value, value)
    if outcome not in OUTCOMES:
        raise ExperienceError("Unknown outcome category.")
    return outcome


def file_hashes(project, paths):
    """Current content fingerprints of edited files through the helper's policy reader; withheld files get None."""
    context = _sibling("context")
    root = Path(project).resolve()
    out = {}
    for path in paths:
        if not _safe_path(path) or context["_skip"](path):
            out[path] = None
            continue
        text, _, reason = context["_read"](root, path, 256 * 1024)
        out[path] = None if reason else hashlib.sha256(text.encode("utf-8")).hexdigest()
    return out


def build_event(*, project, task_id, task, scrub, role=None, config_id=None, baseline=None, retrieved=(), inspected=(),
                edited=(), checks=None, outcome=None, source="explicit", resources=None, corrections=(), notes=None):
    """Assemble one bounded event. `edited` paths are fingerprinted now; `checks` is a verification inspection.

    `notes` carries bounded, scrubbed assertions (`hypotheses`, `assertions`, `limitations`); they are what someone
    reported, kept apart from the observed checks, and never enter retrieval terms.
    """
    if not isinstance(task_id, str) or not 0 < len(task_id) <= 200:
        raise ExperienceError("A task id of at most 200 characters is required.")
    if outcome is None and checks is not None:
        outcome, reason = outcome_from_receipt(checks)
    elif outcome is None:
        outcome, reason = "insufficient_evidence", "no outcome or checks supplied"
    else:
        reason = "outcome supplied explicitly"
    if outcome not in OUTCOMES:
        raise ExperienceError("Unknown outcome category.")
    clean = lambda values: [scrub(p) for p in dict.fromkeys(values) if _safe_path(p)][:MAX_FILES]  # noqa: E731
    edited_paths = clean(edited)
    hashes = file_hashes(project, edited_paths)
    association = "changed_in_checked_task" if outcome in ("checked_success", "grader_passed") else \
        "changed_in_accepted_task" if outcome == "accepted" else "changed_in_task"
    receipt = None
    if checks is not None:
        receipt = {"observations": [{"outcome": o.get("outcome"), "freshness": o.get("freshness"), "kind": (o.get("execution") or {}).get("kind"),
                                     "runner": (o.get("execution") or {}).get("runner"), "test_counts": (o.get("execution") or {}).get("test_counts")}
                                    for o in checks.get("observations", [])[:20]]}
    final = {"files": {path: hashes[path] for path in edited_paths}, "digest": _digest({path: hashes[path] for path in edited_paths})}
    event = {"version": VERSION, "task_id": task_id, "recorded": int(time.time()), "task": task_representation(task, scrub),
             "role": role, "config_id": config_id, "baseline": baseline, "final": final,
             "retrieved": clean(retrieved), "inspected": clean(inspected) if inspected is not None else None,  # None: reads not observed.
             "edited": [{"path": path, "sha256": hashes[path], "association": association} for path in edited_paths],
             "checks": receipt, "outcome": outcome, "outcome_reason": reason, "source": source,
             "resources": dict(list({k: v for k, v in resources.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}.items())[:20])
             if isinstance(resources, dict) else None}
    if isinstance(notes, dict):
        event["notes"] = {key: [scrub(str(v))[:MAX_NOTE] for v in values[:MAX_NOTES] if isinstance(v, str) and v.strip()]
                          for key, values in notes.items() if key in ("hypotheses", "assertions", "limitations") and isinstance(values, list)}
        event["tests_changed"] = any(_sibling("repo_index")["is_test"](path) for path in edited_paths)
    event["id"] = _digest({"task": task_id, "final": final["digest"], "outcome": outcome})
    return event


def record(store, event, eligible=ELIGIBLE):
    with store.transaction():
        stored = store.add_event(event)
    return {"id": event["id"], "stored": stored, "outcome": event["outcome"], "eligible": event["outcome"] in eligible,
            "reason": "duplicate task/state/outcome ignored" if not stored else event["outcome_reason"]}


def correct(store, event_id, path, verdict, note, scrub):
    if verdict not in ("relevant", "irrelevant"):
        raise ExperienceError("A correction verdict is relevant or irrelevant.")
    if not _safe_path(path):
        raise ExperienceError("Correction path must be a safe relative path.")
    with store.transaction():
        store.correct(event_id, scrub(path), verdict, scrub(str(note or ""))[:240])
    return {"event": event_id, "path": path, "verdict": verdict}


def recorrect(store, event_id, outcome, note, scrub):
    """A record-level correction: a new event with the corrected outcome supersedes the old one, which keeps its text."""
    old = store.get_event(event_id)
    if old is None:
        raise ExperienceError("Unknown experience event.")
    outcome = normalize_outcome(outcome)
    fixed = {k: v for k, v in old.items() if k not in ("status", "superseded_by")}
    fixed.update(outcome=outcome, outcome_reason="corrected by the user", source="user_correction", recorded=int(time.time()),
                 supersedes=event_id, notes=dict(old.get("notes") or {}, corrections=[scrub(str(note or ""))[:MAX_NOTE]]))
    fixed["id"] = _digest({"task": old["task_id"], "final": old["final"]["digest"], "outcome": outcome, "supersedes": event_id})
    with store.transaction():
        stored = store.add_event(fixed)
        if stored:
            store.supersede(event_id, fixed["id"])
    return {"id": fixed["id"], "supersedes": event_id, "outcome": outcome, "stored": stored}


def forget(store, *, event_id=None, task_id=None, everything=False):
    """Remove an event (and the corrections that superseded it), a task's events, or everything."""
    if not (event_id or task_id or everything):
        raise ExperienceError("Say what to forget: an event id, a task id, or everything.")
    with store.transaction():
        if everything:
            return {"removed": store.forget()}
        if task_id is not None:
            return {"removed": store.forget(task_id=task_id)}
        removed, pending = 0, [event_id]
        while pending:
            current = pending.pop()
            event = store.get_event(current)
            if event is None:
                continue
            if event.get("superseded_by"):
                pending.append(event["superseded_by"])
            removed += store.forget(event_id=current)
    return {"removed": removed}


def prune(store, *, max_age_days=None, now=None):
    """Forget events older than the age (any status); the store's own retention cap already retires the oldest."""
    now = now if now is not None else time.time()
    old = [e["id"] for e in store.events(status=None) if max_age_days is not None and now - e["recorded"] > max_age_days * 86400]
    removed = 0
    with store.transaction():
        for ident in old:
            removed += store.forget(event_id=ident)
    return {"removed": removed}


def prepare(events, corrections, eligible=ELIGIBLE):
    """Events a retriever may use, with user corrections applied. Aggregates are recomputed here every time."""
    by_event = defaultdict(list)
    for item in corrections:
        by_event[item["event_id"]].append(item)
    prepared = []
    for event in events:
        if event.get("status", "current") != "current" or event.get("outcome") not in eligible:
            continue
        files = {row["path"]: dict(row) for row in event.get("edited", []) if row.get("sha256")}
        for fix in by_event.get(event["id"], ()):
            if fix["verdict"] == "irrelevant":
                files.pop(fix["path"], None)
            elif fix["verdict"] == "relevant" and fix["path"]:
                files[fix["path"]] = {"path": fix["path"], "sha256": None, "association": "user_correction"}
        if files:
            prepared.append({"id": event["id"], "task_id": event["task_id"], "recorded": event["recorded"], "outcome": event["outcome"],
                             "terms": event["task"]["terms"], "summary": event["task"]["summary"], "files": list(files.values())})
    return prepared


def attach(index, events, corrections, eligible=ELIGIBLE):
    """Hand the index its eligible experience; with nothing eligible the index is exactly the indexed-only index."""
    prepared = prepare(events, corrections, eligible)
    index.experience = prepared or None
    return len(prepared)


def _cosine(query_terms, event_terms):
    shared = set(query_terms) & set(event_terms)
    if not shared:
        return 0.0
    dot = sum(query_terms[t] * event_terms[t] for t in shared)
    norm = math.sqrt(sum(v * v for v in query_terms.values())) * math.sqrt(sum(v * v for v in event_terms.values()))
    return dot / norm if norm else 0.0


def matches(query, index, events, tuning, *, top_k=5):
    """Events resembling the request, best first: what a packet can show and a gate can judge."""
    floor = 3.0  # retrieval.DEFAULTS query_weights identifier/symbol level
    identifiers = {t for t, w in query["terms"].items() if w >= floor}
    now, items = time.time(), []
    for event in events:
        similarity = _cosine(query["terms"], event["terms"])
        if similarity < tuning["min_similarity"]:
            continue
        shared = set(query["terms"]) & set(event["terms"])
        files = [row for row in event["files"] if row["path"] in index.kinds]
        known = [row for row in files if row.get("sha256") is not None]  # A user-asserted path carries no fingerprint to compare.
        changed = [row["path"] for row in known if index.hashes.get(row["path"]) != row["sha256"]]
        age_days = max(0.0, (now - event["recorded"]) / 86400)
        recency = 0.5 ** (age_days / tuning["half_life_days"]) if tuning.get("half_life_days") else 1.0
        items.append({"id": event["id"], "task_id": event["task_id"], "score": round(similarity, 4), "similarity": round(similarity, 4),
                      "matched": sorted(shared, key=lambda t: -query["terms"][t])[:8], "identifier_support": len(shared & identifiers),
                      "concept_matches": len(shared - identifiers), "outcome": event["outcome"], "summary": event.get("summary", ""),
                      "files": [row["path"] for row in files], "changed": changed,
                      "freshness": "unknown" if not known else "compatible" if not changed else "partially_changed" if len(changed) < len(known) else "changed",
                      "weight": round(similarity * tuning["outcome_weights"].get(event["outcome"], 0.0) * recency, 4),
                      "resolved": [{"path": row["path"], "label": "exact"} for row in files[:6]]})
    items.sort(key=lambda item: (-item["score"], item["id"]))
    return items[:top_k]


def scores(query, index, events, tuning):
    """(scores, reasons) for the experience retriever: similarity x outcome weight x recency, capped and counted."""
    now = time.time()
    totals, support, best = defaultdict(float), Counter(), {}
    for event in events:
        similarity = _cosine(query["terms"], event["terms"])
        if similarity < tuning["min_similarity"]:
            continue
        age_days = max(0.0, (now - event["recorded"]) / 86400)
        recency = 0.5 ** (age_days / tuning["half_life_days"]) if tuning.get("half_life_days") else 1.0
        weight = similarity * tuning["outcome_weights"].get(event["outcome"], 0.0) * recency
        if weight <= 0:
            continue
        for row in event["files"]:
            path = row["path"]
            if path not in index.kinds:
                continue  # Deleted, excluded or otherwise outside this task's universe: never resurrected.
            changed = row.get("sha256") is not None and index.hashes.get(path) != row["sha256"]
            gain = weight * (tuning["changed_file_factor"] if changed else 1.0)
            totals[path] += gain
            support[path] += 1
            if path not in best or gain > best[path][0]:
                best[path] = (gain, similarity, changed, event["task_id"], row.get("association"))
    reasons = {}
    for path in list(totals):
        if support[path] < tuning["min_support"]:
            del totals[path]
            continue
        gain, similarity, changed, task_id, association = best[path]
        note = f"{association} in {support[path]} earlier task{'s' if support[path] != 1 else ''} resembling this request" \
               f" (similarity {similarity:.2f}{'; file changed since' if changed else ''}; experience, not a repository fact)"
        reasons[path] = (note, task_id, gain, None)
    return totals, reasons


def log_exposure(location, query_digest, rows, chosen):
    """Local analysis only: which experience candidates were offered and which the final ranking kept. Paths and hashes only."""
    try:
        with Path(location).expanduser().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"time": int(time.time()), "task_sha256": query_digest,
                                     "offered": [row["file"] for row in rows], "kept": [p for p in chosen if p in {r["file"] for r in rows}]}) + "\n")
    except OSError:
        pass
