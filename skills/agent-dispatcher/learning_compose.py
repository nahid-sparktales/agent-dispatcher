"""Procedural learning, pure part: strict candidate schemas, structural/security validation, slot contracts,
applicability and deterministic composition of learned overlays onto bundled guidance.

Nothing here reads a file, opens a store or calls a model. The lifecycle module (learning.py) hands in the
revision records and the base artifact bodies; this module says whether a candidate is well-formed under the
tested controls and what the effective guidance for one request is. Passing these checks means the artifact
is structurally sound. It does not mean the prose is harmless or that it improves anything: prose lint is a
signal, human approval and the host's permission layer stay in place, and utility is measured separately
(learning_eval.py).

An overlay never edits the bundled text. Composition keeps the base body byte-for-byte and appends one
clearly labeled derived block per artifact, anchored to a section the contract names; a missing or
ambiguous anchor, a changed base digest, a same-slot conflict or an unmet dependency fails closed to the
pristine base with an explained state.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re

SCHEMA = 1
KINDS = ("skill_overlay", "recipe_overlay", "role_method_overlay", "retrieval_profile", "verification_hint")
OPERATIONS = ("create", "refine", "specialize", "generalize", "merge", "split", "deprecate")
SCOPES = ("repo", "global")
PRIVACY = ("repo_private", "sanitized_general", "never_global")
CREATORS = ("deterministic_review", "host_assisted", "provider_assisted", "human")
# Explain states a request can see for one overlay, or for the layer as a whole.
STATES = ("disabled", "shadow", "not_applicable", "not_approved", "insufficient_evidence", "stale_base", "revoked",
          "conflict", "budget_omitted", "capability_unavailable", "active")
MAX_TEXT = 1200
MAX_LINE = 240
MAX_TERMS = 24
MAX_IDS = 40
MAX_EVENTS = 400
MAX_ADDED_STEPS = 4
MAX_DOCUMENT_BYTES = 64 * 1024
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,79}\Z")
TERM = re.compile(r"[a-z][a-z0-9_]{1,39}\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
REVISION = re.compile(r"[0-9a-f]{16,64}\Z")
DERIVED_MARK = "<!-- agent-dispatcher:derived-guidance -->"

# Slot contracts: which section of which artifact kind may receive a derived block. The anchor must occur exactly
# once in the base body. Identity, authority, deliverables, definition of done, boundaries and tool posture have no
# slot at all, so no candidate can name them.
SLOTS = {
    "skill_overlay": {
        "repository_procedure": {"anchor": r"^## (?:Procedure|Steps)\s*$", "title": "Repository procedure"},
        "failure_branch": {"anchor": r"^## Failure handling\s*$", "title": "Additional failure handling"},
        "applicability_note": {"anchor": r"^## When (?:this|it) fires\s*$", "title": "Narrower applicability"},
        "retrieval_hint": {"anchor": r"^## (?:Procedure|Steps)\s*$", "title": "Retrieval hint"},
    },
    "role_method_overlay": {
        "method_advice": {"anchor": r"^WORKING METHOD\s*$", "title": "Learned method notes"},
    },
    "recipe_overlay": {
        "workflow": {"anchor": r"^## Steps\s*$", "title": "Learned workflow additions"},
    },
}
PROTECTED_ROLE_SECTIONS = ("ROLE:", "WHEN TO USE", "DELIVERABLE", "DEFINITION OF DONE", "ROLE BOUNDARIES", "## Tool posture")

# Retrieval profiles: only strategies that call no model and parameters that already exist in retrieval.DEFAULTS,
# each inside a trusted range. The effective profile is the intersection of this and the caller's own settings.
PROFILE_STRATEGIES = ("full", "full+deep", "full+experience", "full+inference", "full-git", "full-graph", "hybrid", "hybrid+graph")
PROFILE_BOUNDS = {
    "rrf_weights": {"sources": ("git", "experience", "inference", "memory_git", "memory_semantic"), "range": (0.0, 2.0)},
    "graph.max_hops": (0, 2), "graph.max_candidates": (5, 30), "graph.max_neighbors_per_seed": (2, 12),
    "seed_count": (3, 8), "git.max_candidates": (0, 20), "git.min_support": (1, 5),
    "context.max_excerpts_per_file": (1, 3), "context.radius": (3, 10), "context.max_test_share": (0.2, 0.6),
    "kind_weights.test": (0.25, 1.0), "kind_weights.doc": (0.25, 1.0), "tie_tolerance": (0.0, 0.1),
    "experience.min_similarity": (0.1, 0.6), "experience.max_candidates": (1, 10),
}

# Machine-checkable text controls. They reject executable or fetchable material and text that claims to change policy
# or authority. They are a filter, not a proof: prose that passes them is still only guidance under human approval.
_EXECUTABLE = re.compile(r"```|~~~|\$\(|`[^`\n]*(?:\bsh\b|\bbash\b|\bcurl\b|\bwget\b|\brm\b|\bsudo\b|\bchmod\b|\beval\b)[^`\n]*`"
                         r"|\b(?:https?|ssh|git|ftp|file)://|\bimport\s+[A-Za-z_]|\bfrom\s+[A-Za-z_][\w.]*\s+import\b"
                         r"|\bos\.system\b|\bsubprocess\b|\beval\(|\bexec\(|\brm\s+-rf\b|\bsudo\b|\bchmod\b|--dangerously|\bpickle\b|\bSELECT\s+.*\bFROM\b", re.I)
_AUTHORITY = re.compile(r"\bignore\s+(?:[\w-]+\s+){0,3}?(?:instructions?|polic(?:y|ies)|rules?|guards?|checks?|restrictions?)\b"
                        r"|\byou\s+are\s+(?:now\s+)?(?:authori[sz]ed|allowed|permitted)\b"
                        r"|\b(?:disable|skip|bypass|remove|weaken|omit|suppress)\s+(?:[\w-]+\s+){0,3}?"
                        r"(?:verification|checks?|tests?|testing|redaction|reproduction|sandbox|permissions?|approval|guards?|filters?|gates?)\b"
                        r"|\bapprove[sd]?\s+(?:itself|this\s+candidate|automatically)\b|\bself[- ]approv|\bmark(?:ed)?\s+(?:[\w-]+\s+){0,2}?(?:as\s+)?(?:approved|passed|verified)\b"
                        r"|\breport(?:ed|ing)?\s+(?:[\w-]+\s+){0,4}?as\s+(?:verified|passing|done|complete|fixed)\b"
                        r"|\bfetch\s+(?:and\s+run|the\s+payload)\b|\bexpose\s+(?:the\s+)?(?:credentials?|secrets?|keys?)\b|\bzero\s+tests?\s+(?:is|are)\s+(?:fine|acceptable|enough)\b"
                        r"|\bwithout\s+(?:running\s+)?(?:the\s+)?(?:tests?|reproduction|verification)\b|\bonly\s+(?:run\s+)?lint\b", re.I)
_PATHISH = re.compile(r"(?<![\w/.-])(?:\./)?(?:[\w.@-]+/)+[\w.@-]+|(?<![\w/.-])[\w-]+\.(?:py|js|ts|tsx|jsx|go|rs|java|rb|json|ya?ml|toml|md|sql|sh)\b")
_URLISH = re.compile(r"\b(?:https?|ssh|git|ftp|file)://|\bwww\.")
_LONG_NUMBER = re.compile(r"\d{5,}")


class LearningValidationError(ValueError):
    """A bounded diagnostic about a candidate; it never echoes candidate text, paths or task prose."""


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def text_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise LearningValidationError("Candidate document repeats a key.")
        out[key] = value
    return out


def parse_document(raw):
    """Strict JSON: bounded, one object, no duplicate keys, no NaN/Infinity, no nesting past depth 8."""
    if isinstance(raw, (bytes, bytearray)):
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise LearningValidationError("Candidate document exceeds 64 KiB.")
        try:
            raw = bytes(raw).decode("utf-8")
        except UnicodeDecodeError:
            raise LearningValidationError("Candidate document is not UTF-8.") from None
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise LearningValidationError("Candidate document exceeds 64 KiB.")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=lambda name: _constant(name))
    except ValueError as exc:
        if isinstance(exc, LearningValidationError):
            raise
        raise LearningValidationError("Candidate document is not valid JSON.") from None
    if not isinstance(value, dict):
        raise LearningValidationError("Candidate document must be one JSON object.")
    _depth(value, 0)
    return value


def _constant(name):
    raise LearningValidationError("Candidate document contains a non-finite number.")


def _depth(value, level):
    if level > 8:
        raise LearningValidationError("Candidate document nests too deeply.")
    if isinstance(value, dict):
        for item in value.values():
            _depth(item, level + 1)
    elif isinstance(value, list):
        if len(value) > MAX_EVENTS:
            raise LearningValidationError("Candidate document lists too many items.")
        for item in value:
            _depth(item, level + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise LearningValidationError("Candidate document contains a non-finite number.")


# ---------------------------------------------------------------- field validators


def _require(document, allowed, required, what="Candidate"):
    unknown = set(document) - set(allowed)
    if unknown:
        raise LearningValidationError(f"{what} carries an unknown field; controller-owned fields (state, approval, evaluation) are never supplied.")
    missing = set(required) - set(document)
    if missing:
        raise LearningValidationError(f"{what} is missing a required field: {sorted(missing)[0]}.")


def _ident(value, what):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise LearningValidationError(f"{what} must be a registered lowercase id.")
    return value


def _id_list(value, what, pattern=ID, limit=MAX_IDS):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(v, str) or not pattern.fullmatch(v) for v in value):
        raise LearningValidationError(f"{what} must be a bounded list of ids.")
    if len(set(value)) != len(value):
        raise LearningValidationError(f"{what} repeats an id.")
    return list(value)


def _text(value, what, limit=MAX_TEXT, *, allow_empty=False):
    if not isinstance(value, str) or (not value.strip() and not allow_empty) or len(value) > limit:
        raise LearningValidationError(f"{what} must be non-empty text of at most {limit} characters.")
    if any(ord(c) < 32 and c not in "\n\t" for c in value) or "\x7f" in value:
        raise LearningValidationError(f"{what} contains control characters.")
    if any(len(line) > MAX_LINE for line in value.split("\n")):
        raise LearningValidationError(f"{what} has a line over {MAX_LINE} characters.")
    return value.strip()


def lint_text(text, *, scope="repo", private_lexicon=()):
    """Reasons a learned text is refused. Structural refusals are certain; authority refusals are conservative."""
    reasons = []
    if _EXECUTABLE.search(text):
        reasons.append("text contains executable, importable or fetchable material; learned payloads are prose only")
    if _AUTHORITY.search(text):
        reasons.append("text attempts to change policy, authority or required verification; overlays cannot grant or remove either")
    if scope == "global":
        if _PATHISH.search(text) or _URLISH.search(text) or _LONG_NUMBER.search(text):
            reasons.append("global text names paths, URLs or identifiers; a global procedure must be capability-level")
        words = {w.lower() for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text)}
        leaked = words & {w.lower() for w in private_lexicon}
        if leaked:
            reasons.append(f"global text repeats {len(leaked)} repository-private identifier(s)")
    return reasons


def _terms(value, what):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_TERMS or any(not isinstance(v, str) or not TERM.fullmatch(v) for v in value):
        raise LearningValidationError(f"{what} must be at most {MAX_TERMS} lowercase terms.")
    return sorted(set(value))


def validate_applicability(value, *, negative=False):
    if value is None:
        return {"roles": [], "recipes": [], "task_terms": [], "min_term_matches": 1}
    if not isinstance(value, dict):
        raise LearningValidationError("Applicability must be an object.")
    _require(value, ("roles", "recipes", "task_terms", "min_term_matches"), (), "Applicability")
    out = {"roles": _id_list(value.get("roles"), "applicability.roles"), "recipes": _id_list(value.get("recipes"), "applicability.recipes"),
           "task_terms": _terms(value.get("task_terms"), "applicability.task_terms")}
    minimum = value.get("min_term_matches", 1)
    if type(minimum) is not int or not 1 <= minimum <= MAX_TERMS:
        raise LearningValidationError("applicability.min_term_matches must be an integer between 1 and 24.")
    out["min_term_matches"] = minimum
    if not negative and not (out["roles"] or out["recipes"] or out["task_terms"]):
        raise LearningValidationError("Applicability must name a role, a recipe or task terms; an overlay that applies to everything is not narrow.")
    return out


# ---------------------------------------------------------------- payloads per kind


def _validate_slot_payload(kind, payload):
    _require(payload, ("slot", "text"), ("slot", "text"), "Payload")
    slot = payload["slot"]
    if not isinstance(slot, str) or slot not in SLOTS[kind]:
        raise LearningValidationError("Payload names a slot this artifact kind does not declare as evolvable.")
    return {"slot": slot, "text": _text(payload["text"], "payload.text")}


def _validate_recipe_payload(payload):
    _require(payload, ("slot", "insert"), ("slot", "insert"), "Payload")
    if payload["slot"] != "workflow":
        raise LearningValidationError("Recipe overlays use the workflow slot.")
    inserts = payload["insert"]
    if not isinstance(inserts, list) or not inserts or len(inserts) > MAX_ADDED_STEPS:
        raise LearningValidationError(f"Recipe overlays insert between 1 and {MAX_ADDED_STEPS} steps; removing or reordering steps is not a supported operation.")
    out, seen = [], set()
    for item in inserts:
        if not isinstance(item, dict):
            raise LearningValidationError("Each inserted step must be an object.")
        _require(item, ("id", "after", "text", "condition", "capability", "fallback"), ("id", "after", "text"), "Inserted step")
        ident = _ident(item["id"], "inserted step id")
        if ident in seen:
            raise LearningValidationError("Inserted step ids must be unique.")
        seen.add(ident)
        step = {"id": ident, "after": _ident(item["after"], "inserted step anchor"), "text": _text(item["text"], "inserted step text", 600),
                "condition": _text(item["condition"], "inserted step condition", 240) if item.get("condition") is not None else None,
                "capability": item.get("capability"), "fallback": _text(item["fallback"], "inserted step fallback", 240) if item.get("fallback") is not None else None}
        if step["capability"] is not None and (not isinstance(step["capability"], str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{1,79}", step["capability"])):
            raise LearningValidationError("An inserted step's capability must be a registered capability id.")
        out.append(step)
    return {"slot": "workflow", "insert": out}


def _walk(bounds_key, value):
    low, high = PROFILE_BOUNDS[bounds_key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise LearningValidationError(f"Retrieval profile parameter {bounds_key} is outside its trusted range.")
    return int(value) if isinstance(low, int) and isinstance(high, int) else float(value)


def _validate_profile_payload(payload):
    _require(payload, ("strategy", "overrides"), (), "Payload")
    out = {"strategy": None, "overrides": {}}
    if payload.get("strategy") is not None:
        if payload["strategy"] not in PROFILE_STRATEGIES:
            raise LearningValidationError("Retrieval profile names a strategy that is not an approved deterministic strategy.")
        out["strategy"] = payload["strategy"]
    overrides = payload.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise LearningValidationError("Retrieval profile overrides must be an object.")
    for key, value in overrides.items():
        if key == "rrf_weights":
            if not isinstance(value, dict):
                raise LearningValidationError("rrf_weights must be an object.")
            spec = PROFILE_BOUNDS["rrf_weights"]
            for source, weight in value.items():
                if source not in spec["sources"]:
                    raise LearningValidationError("Retrieval profile weights a source it may not touch.")
                if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or not spec["range"][0] <= weight <= spec["range"][1]:
                    raise LearningValidationError("Retrieval profile weight is outside its trusted range.")
            out["overrides"]["rrf_weights"] = {k: float(v) for k, v in sorted(value.items())}
            continue
        if isinstance(value, dict):
            for sub, inner in value.items():
                bounds_key = f"{key}.{sub}"
                if bounds_key not in PROFILE_BOUNDS:
                    raise LearningValidationError("Retrieval profile sets a parameter that is not allowlisted.")
                out["overrides"].setdefault(key, {})[sub] = _walk(bounds_key, inner)
            continue
        if key not in PROFILE_BOUNDS or isinstance(PROFILE_BOUNDS[key], dict):
            raise LearningValidationError("Retrieval profile sets a parameter that is not allowlisted.")
        out["overrides"][key] = _walk(key, value)
    if out["strategy"] is None and not out["overrides"]:
        raise LearningValidationError("Retrieval profile changes nothing.")
    return out


def _validate_hint_payload(payload, registered_checks):
    _require(payload, ("order_first", "add_checks", "note"), (), "Payload")
    out = {"order_first": _id_list(payload.get("order_first"), "order_first", limit=6), "add_checks": [], "note": None}
    for item in payload.get("add_checks") or []:
        if not isinstance(item, dict):
            raise LearningValidationError("Each added check must be an object.")
        _require(item, ("check", "when"), ("check",), "Added check")
        out["add_checks"].append({"check": _ident(item["check"], "check id"), "when": _text(item["when"], "check condition", 240) if item.get("when") is not None else None})
    if len(out["add_checks"]) > 6:
        raise LearningValidationError("A verification hint adds at most six checks.")
    if payload.get("note") is not None:
        out["note"] = _text(payload["note"], "hint note", 400)
    named = set(out["order_first"]) | {c["check"] for c in out["add_checks"]}
    if not named and not out["note"]:
        raise LearningValidationError("A verification hint must name a registered check or carry a note.")
    unknown = named - set(registered_checks)
    if unknown:
        raise LearningValidationError("A verification hint names a check that is not a registered verification capability; prose is never turned into a command.")
    return out


def validate_candidate(document, catalog, *, policy=None, private_lexicon=()):
    """Tier A: a strict candidate document -> normalized candidate, or a bounded LearningValidationError.

    `catalog` describes the installed package: {"roles", "skills", "recipes", "capabilities", "checks", "workflows"}
    as sets/dicts of registered ids. Nothing is resolved by path; artifacts are resolved by registered id only.
    """
    policy = policy or {}
    allowed_kinds = tuple(policy.get("kinds") or KINDS)
    fields = ("schema_version", "kind", "operation", "scope", "target", "payload", "applicability", "negative_applicability",
              "hypothesis", "expected_effect", "risks", "counterexamples", "rejection_conditions", "supporting_event_ids",
              "counterexample_ids", "parent_revision_ids", "logical_parent_ids", "dependencies", "conflicts",
              "privacy_classification", "created_by_kind", "provider_metadata", "task_families")
    _require(document, fields, ("schema_version", "kind", "operation", "scope", "target", "payload", "hypothesis", "created_by_kind"))
    if document["schema_version"] != SCHEMA:
        raise LearningValidationError("Unsupported candidate schema version.")
    kind, operation, scope = document["kind"], document["operation"], document["scope"]
    if kind not in KINDS:
        raise LearningValidationError("Unknown artifact kind.")
    if kind not in allowed_kinds:
        raise LearningValidationError("This artifact kind is not enabled by the learning configuration.")
    if operation not in OPERATIONS:
        raise LearningValidationError("Unknown change operation.")
    if scope not in SCOPES:
        raise LearningValidationError("Scope must be repo or global.")
    if document["created_by_kind"] not in CREATORS:
        raise LearningValidationError("Unknown proposer kind.")
    target = document["target"]
    if not isinstance(target, dict):
        raise LearningValidationError("Target must be an object.")
    _require(target, ("artifact_id", "slot"), ("artifact_id",), "Target")
    artifact_id = _ident(target["artifact_id"], "target.artifact_id")
    payload = document["payload"]
    if not isinstance(payload, dict):
        raise LearningValidationError("Payload must be an object.")
    privacy = document.get("privacy_classification", "repo_private" if scope == "repo" else "sanitized_general")
    if privacy not in PRIVACY:
        raise LearningValidationError("Unknown privacy classification.")
    if scope == "global" and privacy != "sanitized_general":
        raise LearningValidationError("A global candidate must be classified sanitized_general.")
    if kind == "skill_overlay":
        if artifact_id not in catalog["skills"]:
            raise LearningValidationError("Target skill is not a bundled skill of the installed catalog.")
        normalized = _validate_slot_payload(kind, payload)
    elif kind == "role_method_overlay":
        if artifact_id not in catalog["roles"]:
            raise LearningValidationError("Target role is not in the installed catalog.")
        normalized = _validate_slot_payload(kind, payload)
    elif kind == "recipe_overlay":
        if artifact_id not in catalog["recipes"]:
            raise LearningValidationError("Target recipe is not in the installed catalog.")
        workflow = (catalog.get("workflows") or {}).get(artifact_id)
        if workflow is None:
            raise LearningValidationError("Target recipe has no validated workflow sidecar; only recipes with stable step ids are evolvable.")
        normalized = _validate_recipe_payload(payload)
        validate_recipe_insertions(workflow, normalized["insert"], catalog.get("capabilities") or ())
    elif kind == "retrieval_profile":
        if artifact_id != "retrieval":
            raise LearningValidationError("A retrieval profile targets the artifact id `retrieval`.")
        normalized = _validate_profile_payload(payload)
    else:
        if artifact_id != "verification":
            raise LearningValidationError("A verification hint targets the artifact id `verification`.")
        normalized = _validate_hint_payload(payload, catalog.get("checks") or ())
    if target.get("slot") is not None and target["slot"] != normalized.get("slot"):
        raise LearningValidationError("Target slot and payload slot disagree.")
    texts = []
    if "text" in normalized:
        texts.append(normalized["text"])
    for step in normalized.get("insert", []):
        texts += [t for t in (step["text"], step["condition"], step["fallback"]) if t]
    for check in normalized.get("add_checks", []):
        if check["when"]:
            texts.append(check["when"])
    if normalized.get("note"):
        texts.append(normalized["note"])
    for text in texts:
        reasons = lint_text(text, scope=scope, private_lexicon=private_lexicon)
        if reasons:
            raise LearningValidationError("Payload text refused: " + reasons[0] + ".")
    if document.get("applicability") is None:
        raise LearningValidationError("Applicability is required: name a role, a recipe or task terms.")
    candidate = {
        "schema_version": SCHEMA, "kind": kind, "operation": operation, "scope": scope,
        "target": {"artifact_id": artifact_id, "slot": normalized.get("slot")}, "payload": normalized,
        "applicability": validate_applicability(document["applicability"]),
        "negative_applicability": validate_applicability(document.get("negative_applicability"), negative=True) if document.get("negative_applicability") is not None else None,
        "hypothesis": _text(document["hypothesis"], "hypothesis", 600),
        "expected_effect": _effect(document.get("expected_effect")),
        "risks": [_text(r, "risk", 240) for r in _list(document.get("risks"), "risks", 8)],
        "counterexamples": [_text(r, "counterexample", 240) for r in _list(document.get("counterexamples"), "counterexamples", 8)],
        "rejection_conditions": [_text(r, "rejection condition", 240) for r in _list(document.get("rejection_conditions"), "rejection_conditions", 8)],
        "supporting_event_ids": _id_list(document.get("supporting_event_ids"), "supporting_event_ids", HEX, MAX_EVENTS),
        "counterexample_ids": _id_list(document.get("counterexample_ids"), "counterexample_ids", HEX, MAX_EVENTS),
        "parent_revision_ids": _id_list(document.get("parent_revision_ids"), "parent_revision_ids", REVISION),
        "logical_parent_ids": _id_list(document.get("logical_parent_ids"), "logical_parent_ids", ID),
        "dependencies": _id_list(document.get("dependencies"), "dependencies", REVISION),
        "conflicts": _id_list(document.get("conflicts"), "conflicts", REVISION),
        "task_families": _id_list(document.get("task_families"), "task_families", re.compile(r"[A-Za-z0-9._:-]{1,120}\Z"), MAX_EVENTS),
        "privacy_classification": privacy, "created_by_kind": document["created_by_kind"],
        "provider_metadata": _provider(document.get("provider_metadata")),
    }
    for text in (candidate["hypothesis"], *candidate["risks"], *candidate["counterexamples"], *candidate["rejection_conditions"]):
        reasons = [r for r in lint_text(text, scope=scope) if "executable" in r]
        if reasons:
            raise LearningValidationError("Candidate prose refused: " + reasons[0] + ".")
    if operation in ("merge", "split", "deprecate") and not candidate["parent_revision_ids"]:
        raise LearningValidationError(f"Operation {operation} needs parent_revision_ids.")
    if set(candidate["dependencies"]) & set(candidate["conflicts"]):
        raise LearningValidationError("A revision cannot depend on and conflict with the same revision.")
    return candidate


def _list(value, what, limit):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise LearningValidationError(f"{what} must be a list of at most {limit} items.")
    return value


def _effect(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise LearningValidationError("expected_effect must be an object.")
    _require(value, ("metric", "direction", "practical_threshold", "note"), ("metric", "direction"), "expected_effect")
    if value["metric"] not in ("task_success", "cost_per_success", "tokens", "steps", "wall_time", "retrieval_recall", "false_trigger_rate"):
        raise LearningValidationError("expected_effect.metric is not a measured metric.")
    if value["direction"] not in ("increase", "decrease"):
        raise LearningValidationError("expected_effect.direction must be increase or decrease.")
    threshold = value.get("practical_threshold")
    if threshold is not None and (isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not 0 < threshold <= 1):
        raise LearningValidationError("expected_effect.practical_threshold must be a number in (0, 1].")
    return {"metric": value["metric"], "direction": value["direction"], "practical_threshold": threshold,
            "note": _text(value["note"], "expected_effect.note", 240) if value.get("note") is not None else None}


def _provider(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise LearningValidationError("provider_metadata must be an object.")
    _require(value, ("provider", "model", "prompt_version", "input_tokens", "output_tokens", "cost_usd"), (), "provider_metadata")
    out = {}
    for key in ("provider", "model"):
        if value.get(key) is not None:
            out[key] = _text(str(value[key]), "provider_metadata." + key, 120)
    for key in ("prompt_version", "input_tokens", "output_tokens"):
        if value.get(key) is not None:
            if type(value[key]) is not int or value[key] < 0:
                raise LearningValidationError("provider_metadata counts must be non-negative integers.")
            out[key] = value[key]
    if value.get("cost_usd") is not None:
        if isinstance(value["cost_usd"], bool) or not isinstance(value["cost_usd"], (int, float)) or not math.isfinite(value["cost_usd"]) or value["cost_usd"] < 0:
            raise LearningValidationError("provider_metadata.cost_usd must be a finite non-negative number.")
        out["cost_usd"] = float(value["cost_usd"])
    return out


# ---------------------------------------------------------------- recipe workflows


def validate_workflow(workflow, capabilities=()):
    """A recipe's machine-readable sidecar: stable step ids, acyclic prerequisites, reachable steps, mandatory gates."""
    if not isinstance(workflow, dict):
        raise LearningValidationError("Workflow must be an object.")
    _require(workflow, ("schema_version", "recipe", "steps", "gates", "mandatory", "evolvable"), ("schema_version", "recipe", "steps", "gates", "mandatory", "evolvable"), "Workflow")
    if workflow["schema_version"] != SCHEMA:
        raise LearningValidationError("Unsupported workflow schema version.")
    _ident(workflow["recipe"], "workflow.recipe")
    steps = workflow["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 30:
        raise LearningValidationError("A workflow has between 1 and 30 steps.")
    ids = []
    for position, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise LearningValidationError("Each workflow step must be an object.")
        _require(step, ("id", "index", "title", "requires", "capability"), ("id", "index", "title", "requires"), "Workflow step")
        _ident(step["id"], "workflow step id")
        if step["index"] != position:
            raise LearningValidationError("Workflow step indices must be contiguous and in order.")
        _text(step["title"], "workflow step title", 160)
        ids.append(step["id"])
        if step.get("capability") is not None and capabilities and step["capability"] not in capabilities:
            raise LearningValidationError("A workflow step names a capability no skill provides.")
    if len(set(ids)) != len(ids):
        raise LearningValidationError("Workflow step ids must be unique.")
    known = set(ids)
    order = {ident: n for n, ident in enumerate(ids)}
    for step in steps:
        requires = _id_list(step["requires"], "workflow step requires")
        for dependency in requires:
            if dependency not in known:
                raise LearningValidationError("A workflow step requires an unknown step.")
            if order[dependency] >= order[step["id"]]:
                raise LearningValidationError("Workflow prerequisites must precede the step (no cycles).")
    reachable = {ids[0]}
    for step in steps[1:]:
        if not step["requires"] or any(dep in reachable for dep in step["requires"]):
            reachable.add(step["id"])
    if reachable != known:
        raise LearningValidationError("Every workflow step must be reachable from the first step.")
    gates = workflow["gates"]
    if not isinstance(gates, list) or not gates or len(gates) > 12:
        raise LearningValidationError("A workflow declares between 1 and 12 gates.")
    gate_ids = []
    for gate in gates:
        if not isinstance(gate, dict):
            raise LearningValidationError("Each gate must be an object.")
        _require(gate, ("id", "steps", "text"), ("id", "steps"), "Workflow gate")
        _ident(gate["id"], "gate id")
        gate_ids.append(gate["id"])
        for ident in _id_list(gate["steps"], "gate steps"):
            if ident not in known:
                raise LearningValidationError("A gate names an unknown step.")
    if len(set(gate_ids)) != len(gate_ids):
        raise LearningValidationError("Gate ids must be unique.")
    mandatory = _id_list(workflow["mandatory"], "workflow.mandatory")
    if not mandatory or any(ident not in known for ident in mandatory):
        raise LearningValidationError("workflow.mandatory must name existing steps.")
    gated = {ident for gate in gates for ident in gate["steps"]}
    if not gated <= set(mandatory):
        raise LearningValidationError("Every gated step must be mandatory.")
    evolvable = workflow["evolvable"]
    if not isinstance(evolvable, dict):
        raise LearningValidationError("workflow.evolvable must be an object.")
    _require(evolvable, ("insert_after", "max_added_steps"), ("insert_after", "max_added_steps"), "workflow.evolvable")
    anchors = _id_list(evolvable["insert_after"], "evolvable.insert_after")
    if any(ident not in known for ident in anchors):
        raise LearningValidationError("evolvable.insert_after names an unknown step.")
    if type(evolvable["max_added_steps"]) is not int or not 1 <= evolvable["max_added_steps"] <= MAX_ADDED_STEPS:
        raise LearningValidationError(f"evolvable.max_added_steps must be between 1 and {MAX_ADDED_STEPS}.")
    return workflow


def validate_recipe_insertions(workflow, inserts, capabilities=()):
    """Inserted optional steps keep every base step, every gate and every prerequisite exactly as declared."""
    anchors = set(workflow["evolvable"]["insert_after"])
    known = {step["id"] for step in workflow["steps"]}
    if len(inserts) > workflow["evolvable"]["max_added_steps"]:
        raise LearningValidationError("Recipe overlay inserts more steps than the workflow allows.")
    for step in inserts:
        if step["after"] not in anchors:
            raise LearningValidationError("Recipe overlay inserts after a step that is not evolvable (mandatory gates and their order are fixed).")
        if step["id"] in known:
            raise LearningValidationError("Recipe overlay reuses a base step id.")
        if step["capability"] is not None and capabilities and step["capability"] not in capabilities:
            raise LearningValidationError("Recipe overlay names a capability no installed skill provides.")
    return compose_workflow(workflow, inserts)


def compose_workflow(workflow, inserts):
    """The composed step graph: base steps unchanged, inserted steps as optional branches after their anchor."""
    steps = [dict(step, derived=False) for step in workflow["steps"]]
    for item in inserts:
        position = next(n for n, step in enumerate(steps) if step["id"] == item["after"]) + 1
        while position < len(steps) and steps[position].get("derived") and steps[position]["after"] == item["after"]:
            position += 1
        steps.insert(position, {"id": item["id"], "title": item["text"].split("\n")[0][:160], "requires": [item["after"]], "capability": item["capability"],
                                "condition": item["condition"], "fallback": item["fallback"], "derived": True, "after": item["after"], "text": item["text"]})
    for n, step in enumerate(steps, 1):
        step["index"] = n
    return {"recipe": workflow["recipe"], "steps": steps, "gates": workflow["gates"], "mandatory": workflow["mandatory"]}


# ---------------------------------------------------------------- revisions


def revision_record(candidate, *, base_package_digest, base_artifact_digest, policy_digest, namespace, evidence_cutoff, created, creation_cost=None, source_provenance=None):
    """The immutable revision: everything an evaluation binds to. Editing any field yields a new revision id."""
    record = {"schema_version": SCHEMA, "artifact_id": candidate["target"]["artifact_id"], "artifact_kind": candidate["kind"],
              "scope": candidate["scope"], "namespace": namespace, "operation": candidate["operation"],
              "editable_slot_ids": [candidate["target"]["slot"]] if candidate["target"]["slot"] else [],
              "typed_payload": candidate["payload"], "applicability": candidate["applicability"],
              "negative_applicability": candidate["negative_applicability"], "dependencies": candidate["dependencies"],
              "conflicts": candidate["conflicts"], "logical_parent_ids": candidate["logical_parent_ids"],
              "parent_revision_ids": candidate["parent_revision_ids"], "base_package_digest": base_package_digest,
              "base_artifact_digest": base_artifact_digest, "policy_digest": policy_digest,
              "supporting_event_ids": candidate["supporting_event_ids"], "counterexample_ids": candidate["counterexample_ids"],
              "task_families": candidate["task_families"], "evidence_cutoff": evidence_cutoff,
              "hypothesis": candidate["hypothesis"], "expected_effect": candidate["expected_effect"], "risks": candidate["risks"],
              "counterexamples": candidate["counterexamples"], "rejection_conditions": candidate["rejection_conditions"],
              "source_provenance": source_provenance or {"created_by_kind": candidate["created_by_kind"]},
              "privacy_classification": candidate["privacy_classification"],
              "invalidation_dependencies": sorted(set(candidate["dependencies"]) | set(candidate["parent_revision_ids"])),
              "created_by_kind": candidate["created_by_kind"], "optional_provider_metadata": candidate["provider_metadata"],
              "creation_cost": creation_cost, "created": created}
    record["rendered_body_digest"] = digest(candidate["payload"])
    record["revision_id"] = revision_identity(record)
    return record


# Fields outside the identity: timing, cost and the lifecycle view the store attaches when it hands a record back.
_NON_IDENTITY = ("created", "creation_cost", "revision_id", "state", "state_reason", "runtime_state", "runtime_reason", "experiment")


def revision_identity(record):
    return digest({k: v for k, v in record.items() if k not in _NON_IDENTITY})


def revision_digest_matches(record):
    """Recheck the id from the stored bytes: a tampered payload or applicability no longer names this revision."""
    return revision_identity(record) == record.get("revision_id")


# ---------------------------------------------------------------- applicability


def applicable(revision, *, role=None, recipes=(), terms=()):
    """(eligible, reason, matched terms). A heuristic gate reported as evidence, never as a probability."""
    want = revision["applicability"]
    negative = revision.get("negative_applicability")
    term_set = set(terms)
    if negative:
        if role and role in negative["roles"]:
            return False, "negative applicability: role excluded", []
        if set(negative["recipes"]) & set(recipes):
            return False, "negative applicability: recipe excluded", []
        blocked = sorted(term_set & set(negative["task_terms"]))
        if blocked and len(blocked) >= negative["min_term_matches"]:
            return False, "negative applicability: request names an excluded term", blocked
    if want["roles"] and (role is None or role not in want["roles"]):
        return False, "role does not match", []
    if want["recipes"] and not set(want["recipes"]) & set(recipes):
        return False, "recipe does not match", []
    matched = sorted(term_set & set(want["task_terms"]))
    if want["task_terms"] and len(matched) < want["min_term_matches"]:
        return False, "request lacks the overlay's task terms", matched
    return True, "role, recipe and task terms match", matched


# ---------------------------------------------------------------- composition


def _anchor(body, pattern):
    hits = [n for n, line in enumerate(body.split("\n")) if re.match(pattern, line)]
    if len(hits) != 1:
        return None
    return hits[0]


def _section_end(lines, start):
    """Index of the first line after the anchored section (next heading of the same or higher level, or EOF)."""
    heading = lines[start]
    level = len(heading) - len(heading.lstrip("#")) if heading.startswith("#") else None
    for n in range(start + 1, len(lines)):
        line = lines[n]
        if level is not None and line.startswith("#") and (len(line) - len(line.lstrip("#"))) <= level:
            return n
        if level is None and re.match(r"^[A-Z][A-Z ]{3,}:?\s*$", line) and n > start:
            return n
    return len(lines)


def _derived_block(kind, layers, title, workflow=None):
    lines = [DERIVED_MARK, "", f"### {title} (derived guidance; not part of the bundled text)", ""]
    for layer in layers:
        head = f"_Source: learned {layer['scope']} overlay {layer['revision_id'][:12]}; slot {layer['slot']}; evidence, not authority._"
        lines += [head, ""]
        if kind == "recipe_overlay":
            for step in layer["insert"]:
                anchor = workflow["titles"].get(step["after"], step["after"]) if workflow else step["after"]
                lines.append(f"- After step {workflow['indexes'].get(step['after'], '?') if workflow else '?'} ({anchor}), optionally: {step['text']}")
                if step.get("condition"):
                    lines.append(f"  Condition: {step['condition']}")
                if step.get("fallback"):
                    lines.append(f"  When unavailable: {step['fallback']}")
            lines.append("")
        else:
            lines += [layer["text"], ""]
    lines.append(DERIVED_END)
    return lines


def compose(kind, base_body, layers, workflow=None):
    """base + admitted layers -> {"content", "state", "reason", "diff"}; fail closed to the pristine base.

    `layers`: [{"revision_id", "scope", "slot", "text" | "insert"}]. Layers are grouped by slot; each slot gets one derived
    block anchored to its declared section, global layer before repository layer inside the block. Two layers of one
    scope on one slot is a conflict the caller resolves first (this refuses it too). A missing or ambiguous anchor, a
    protected role section that would change, or a composition whose inverse is not the base bytes all fail closed.
    """
    if not layers:
        return {"content": base_body, "state": "not_applicable", "reason": "no layer", "diff": []}
    if DERIVED_MARK in base_body:
        return {"content": base_body, "state": "conflict", "reason": "base body already carries derived guidance", "diff": []}
    groups = {}
    for layer in layers:
        groups.setdefault(layer["slot"], []).append(layer)
    order = list(SLOTS.get(kind, {}))
    content, blocks = base_body, []
    for slot in sorted(groups, key=lambda name: order.index(name) if name in order else len(order)):
        group = sorted(groups[slot], key=lambda layer: (layer["scope"] != "global", layer["revision_id"]))
        outcome = _compose_slot(kind, content, group, slot, workflow)
        if outcome["state"] != "active":
            return {"content": base_body, "state": outcome["state"], "reason": outcome["reason"], "diff": []}
        content, blocks = outcome["content"], blocks + outcome["diff"]
    if kind == "role_method_overlay":
        for name in PROTECTED_ROLE_SECTIONS:
            if _protected(base_body, name) != _protected(content, name):
                return {"content": base_body, "state": "conflict", "reason": "composition would alter a protected role section", "diff": []}
    # The base text survives verbatim: removing every derived block restores the exact bytes.
    if _strip_derived(content) != base_body:
        return {"content": base_body, "state": "conflict", "reason": "composition changed base text", "diff": []}
    return {"content": content, "state": "active", "reason": "composed", "diff": blocks}


def _compose_slot(kind, body, layers, slot, workflow):
    contract = SLOTS.get(kind, {}).get(slot)
    if contract is None:
        return {"content": body, "state": "conflict", "reason": "slot is not evolvable for this artifact kind", "diff": []}
    seen = set()
    for layer in layers:
        if layer["scope"] in seen:
            return {"content": body, "state": "conflict", "reason": "two overlays of one scope target the same slot", "diff": []}
        seen.add(layer["scope"])
    lines = body.split("\n")
    start = _anchor(body, contract["anchor"])
    if start is None:
        return {"content": body, "state": "stale_base", "reason": "slot anchor is missing or ambiguous in the current base; the overlay needs revalidation", "diff": []}
    end = _section_end(lines, start)
    block = _derived_block(kind, layers, contract["title"], workflow)
    # Self-delimiting: exactly one blank line before the mark and one after the end line, always, so stripping is exact.
    composed = lines[:end] + [""] + block + [""] + lines[end:]
    return {"content": "\n".join(composed), "state": "active", "reason": "composed", "diff": block}


def _protected(body, name):
    lines = body.split("\n")
    hits = [n for n, line in enumerate(lines) if line.startswith(name)]
    if not hits:
        return None
    start = hits[0]
    return "\n".join(lines[start:_section_end(lines, start)])


DERIVED_END = "_Base steps, gates, boundaries and required evidence above are unchanged; a learned note never removes a check._"


def _strip_derived(content):
    """Exact inverse of compose(): remove every blank-mark-...-end-blank run this module wrote, and nothing else."""
    lines = content.split("\n")
    while DERIVED_MARK in lines:
        start = lines.index(DERIVED_MARK)
        end = start
        while end < len(lines) and lines[end] != DERIVED_END:
            end += 1
        if end + 1 >= len(lines) or start == 0 or lines[start - 1] != "" or lines[end + 1] != "":
            return "\n".join(lines)  # Not a block this module wrote; leave it alone.
        lines = lines[:start - 1] + lines[end + 2:]
    return "\n".join(lines)


def workflow_view(workflow):
    return {"titles": {step["id"]: step["title"] for step in workflow["steps"]}, "indexes": {step["id"]: step["index"] for step in workflow["steps"]}}


def effective_profile(revisions, base_settings, *, caller_strategy_explicit=False):
    """Intersection of admitted retrieval profiles and the caller's configuration: never a provider, never a wider limit."""
    if not revisions:
        return None, None
    if len(revisions) > 1:
        return None, {"state": "conflict", "reason": "more than one active retrieval profile"}
    payload = revisions[0]["typed_payload"]
    strategy = None if caller_strategy_explicit else payload.get("strategy")
    overrides = copy.deepcopy(payload.get("overrides") or {})
    for key in ("llm_rerank", "role_summary", "explorer", "retrievers", "query_weights", "pin_named_paths", "fusion", "frames", "structural_records"):
        overrides.pop(key, None)
    if "context" in overrides and base_settings is not None:
        # Caller caps (files, bytes, tokens) remain the caller's; a profile may only choose within them.
        for key in ("max_files", "max_bytes", "max_tokens"):
            overrides["context"].pop(key, None)
    return {"strategy": strategy, "overrides": overrides, "revision_id": revisions[0]["revision_id"]}, {"state": "active", "reason": "profile applied within caller limits"}


def estimate_tokens(text):
    return math.ceil(len(text) / 4)


def added_tokens(base_body, content):
    return max(0, estimate_tokens(canonical(content)) - estimate_tokens(canonical(base_body)))
