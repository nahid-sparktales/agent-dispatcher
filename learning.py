#!/usr/bin/env python3
"""Governed procedural learning: evidence -> review -> immutable candidate -> validation -> evaluation -> human approval
-> atomic publication -> bounded runtime composition -> correction, retirement and rollback.

    FOREGROUND     context.py reads one immutable active generation read-only and composes bounded overlays.
    MAINTENANCE    this CLI: observe, review, propose, evaluate, approve, promote, rollback, revoke, prune.

Off unless the user's own settings file (outside every project) enables it; then `shadow` first, which describes
eligibility and proposals without changing any packet. Nothing here trains a model, observes a session or reads a
conversation: observations are explicit records keyed to experience events the host already handed in. A learned
artifact is lower-priority guidance with no authority: it cannot touch redaction, admission, permissions, required
verification, provider settings or this admission policy, and the host's permission layer is unchanged by it.

Storage: `learning.sqlite` beside the experience store in the private state directory (repository scope), or under
`learning-v1/profile-<digest>/` for a user-local profile (global scope), through repo_store's hardened opener.
Owner-only files, hashes and approval records establish provenance and integrity, not semantic truth, and none of
them can sandbox a malicious same-user process. Deletion here is logical deletion in a local SQLite file.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import sys
import time

SCHEMA = 1
STORE_FILE = "learning.sqlite"
MAX_SETTINGS_BYTES = 64 * 1024
MAX_OBSERVATION_BYTES = 256 * 1024
MODES = ("shadow", "active")
FEEDBACK = ("user_host", "development_evaluation", "synthetic_fixture", "hidden_grader")
EXPOSURES = ("eligible", "selected", "emitted", "host_confirmed_read", "reported_applied", "unknown")
FAILURE_CATEGORIES = ("failed_checks", "stale_checks", "zero_tests", "exit_code_only", "wrong_file", "missing_reproduction",
                      "no_regression_test", "timing_fix", "scope_violation", "infrastructure", "security_concern",
                      "verification_bypass", "history_unavailable", "capability_unavailable", "other")
TERMINAL = ("revoked", "pruned")
# Controller-owned state machine. A candidate never sets its own state; only these edges exist.
TRANSITIONS = {
    None: {"proposed"},
    "proposed": {"validated", "rejected", "invalid"},
    "validated": {"evaluating", "awaiting_experiment_authorization", "rejected", "invalid", "stale_support", "quarantined", "revoked"},
    "awaiting_experiment_authorization": {"experimental_canary", "rejected", "invalid", "revoked", "quarantined"},
    "experimental_canary": {"evaluating", "rejected", "revoked", "quarantined", "stale_support", "expired"},
    "evaluating": {"evaluation_passed", "evaluation_failed", "inconclusive", "invalid", "rejected", "revoked", "quarantined", "stale_support"},
    "evaluation_passed": {"awaiting_approval", "rejected", "invalid", "revoked", "quarantined", "stale_support", "evaluating"},
    "awaiting_approval": {"approved", "rejected", "revoked", "quarantined", "stale_support", "evaluating"},
    "approved": {"active", "canary", "rejected", "revoked", "quarantined", "stale_support"},
    "canary": {"active", "deprecated", "rolled_back", "revoked", "quarantined", "stale_support", "expired"},
    "active": {"deprecated", "rolled_back", "revoked", "quarantined", "stale_support"},
    "rolled_back": {"active", "deprecated", "revoked", "quarantined", "pruned"},
    "deprecated": {"active", "revoked", "pruned"},
    "stale_support": {"evaluating", "rejected", "revoked", "pruned", "deprecated"},
    "evaluation_failed": {"evaluating", "rejected", "pruned"},
    "inconclusive": {"evaluating", "rejected", "pruned"},
    "expired": {"evaluating", "pruned"},
    "rejected": {"pruned"}, "invalid": {"pruned"}, "quarantined": {"revoked", "rejected", "pruned"}, "revoked": {"pruned"},
}
LIVE = ("active", "canary")
RETENTION_ELIGIBLE = ("rejected", "invalid", "evaluation_failed", "inconclusive", "expired", "deprecated", "rolled_back", "stale_support", "revoked")
DEFAULTS = {
    "enabled": False,
    "mode": "shadow",
    "observation": {"record": False},
    "kinds": ["skill_overlay", "recipe_overlay", "role_method_overlay", "retrieval_profile", "verification_hint", "skill_selection"],
    "review": {"due_after_observations": 20, "min_support_families": 5, "max_candidates": 3},
    "proposals": {"host_assisted": True,
                  "provider": {"enabled": False, "provider": None, "model": None, "base_url": None, "api_key_env": None, "command": None,
                               "temperature": 0, "timeout": 120, "max_retries": 0, "max_output_tokens": 1500, "max_calls": 1,
                               "max_seconds": 180, "max_spend_usd": None, "price_per_mtok": None, "extra_body": {}}},
    "budget": {"max_overlays": 3, "max_added_tokens": 600, "max_added_share": 0.10},
    "evaluation": {"min_paired_families": 30, "min_blocks": 3, "practical_threshold": 0.05, "noninferiority_margin": None,
                   "confidence": 0.95, "global_min_families": 3, "monitor_regression_pairs": 8},
    "approval": {"policy": "human"},
    "canary": {"max_tasks": 20, "max_days": 30},
    "profile": None,
    "retention": {"max_age_days": 90},
}


class LearningError(ValueError):
    """Bounded diagnostic; never echoes task text, candidate text, private paths or store contents."""


_SIBLINGS = {}


def _sibling(name):
    if name not in _SIBLINGS:
        path = Path(__file__).resolve().with_name(name + ".py")
        namespace = {"__name__": "_dispatcher_learning_" + name, "__file__": str(path)}
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
        _SIBLINGS[name] = namespace
    return _SIBLINGS[name]


def _digest(value):
    return _sibling("learning_compose")["digest"](value)


def _merge(base, overrides):
    out = copy.deepcopy(base)
    for key, value in overrides.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else copy.deepcopy(value)
    return out


def _now():
    return int(time.time())


# ---------------------------------------------------------------- settings


def settings_path():
    explicit = os.environ.get("AGENT_DISPATCHER_LEARNING_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    config = os.environ.get("XDG_CONFIG_HOME")
    return (Path(config) if config and Path(config).is_absolute() else Path.home() / ".config") / "agent-dispatcher" / "procedural-learning.json"


def _outside(path, project, what):
    if project is not None:
        try:
            inside = Path(path).expanduser().resolve().is_relative_to(Path(project).expanduser().resolve())
        except OSError:
            inside = False
        if inside:
            raise LearningError(f"{what} must live outside the inspected project.")


def load_settings(path=None, project=None):
    """The user's own file, read without creating anything. An environment override gets the same location check."""
    location = Path(path).expanduser() if path else settings_path()
    _outside(location, project, "Procedural learning settings")
    try:
        if location.is_symlink() or (location.exists() and not location.is_file()):
            raise LearningError("Procedural learning settings must be a regular file.")
        if location.stat().st_size > MAX_SETTINGS_BYTES:
            raise LearningError("Procedural learning settings are too large.")
        loaded = json.loads(location.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return copy.deepcopy(DEFAULTS)
    except (OSError, ValueError):
        raise LearningError("Procedural learning settings could not be read.") from None
    if not isinstance(loaded, dict):
        raise LearningError("Procedural learning settings must be a JSON object.")
    return validate_settings(_merge(DEFAULTS, {key: value for key, value in loaded.items() if key in DEFAULTS}))


def validate_settings(settings):
    compose = _sibling("learning_compose")
    if type(settings["enabled"]) is not bool or type(settings["observation"]["record"]) is not bool:
        raise LearningError("enabled and observation.record must be booleans.")
    if settings["mode"] not in MODES:
        raise LearningError("mode must be shadow or active.")
    kinds = settings["kinds"]
    if not isinstance(kinds, list) or not kinds or any(k not in compose["KINDS"] for k in kinds) or len(set(kinds)) != len(kinds):
        raise LearningError("kinds must list known artifact kinds.")
    review = settings["review"]
    for key, low, high in (("due_after_observations", 1, 10000), ("min_support_families", 1, 1000), ("max_candidates", 1, 20)):
        if type(review[key]) is not int or not low <= review[key] <= high:
            raise LearningError(f"review.{key} must be an integer between {low} and {high}.")
    budget = settings["budget"]
    if type(budget["max_overlays"]) is not int or not 0 <= budget["max_overlays"] <= 10:
        raise LearningError("budget.max_overlays must be an integer between 0 and 10.")
    if type(budget["max_added_tokens"]) is not int or not 0 <= budget["max_added_tokens"] <= 4000:
        raise LearningError("budget.max_added_tokens must be an integer between 0 and 4000.")
    share = budget["max_added_share"]
    if isinstance(share, bool) or not isinstance(share, (int, float)) or not 0 <= share <= 0.5:
        raise LearningError("budget.max_added_share must be a number between 0 and 0.5.")
    evaluation = settings["evaluation"]
    for key in ("min_paired_families", "min_blocks", "global_min_families", "monitor_regression_pairs"):
        if type(evaluation[key]) is not int or not 1 <= evaluation[key] <= 100000:
            raise LearningError(f"evaluation.{key} must be a positive integer.")
    for key in ("practical_threshold", "confidence"):
        value = evaluation[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < 1:
            raise LearningError(f"evaluation.{key} must be a number in (0, 1).")
    margin = evaluation["noninferiority_margin"]
    if margin is not None and (isinstance(margin, bool) or not isinstance(margin, (int, float)) or not 0 <= margin <= 0.5):
        raise LearningError("evaluation.noninferiority_margin must be null or a number between 0 and 0.5.")
    if settings["approval"]["policy"] != "human":
        raise LearningError("approval.policy: only human approval exists in this release; automatic promotion does not ship.")
    canary = settings["canary"]
    if type(canary["max_tasks"]) is not int or not 1 <= canary["max_tasks"] <= 1000 or type(canary["max_days"]) is not int or not 1 <= canary["max_days"] <= 365:
        raise LearningError("canary.max_tasks and canary.max_days must be bounded positive integers.")
    profile = settings["profile"]
    if profile is not None and (not isinstance(profile, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", profile)):
        raise LearningError("profile must be null or a short lowercase name.")
    provider = settings["proposals"]["provider"]
    if type(provider["enabled"]) is not bool or type(settings["proposals"]["host_assisted"]) is not bool:
        raise LearningError("proposal switches must be booleans.")
    if type(provider["max_calls"]) is not int or not 1 <= provider["max_calls"] <= 5:
        raise LearningError("proposals.provider.max_calls must be between 1 and 5.")
    retention = settings["retention"]["max_age_days"]
    if retention is not None and (type(retention) is not int or not 1 <= retention <= 3650):
        raise LearningError("retention.max_age_days must be null or a positive integer.")
    return settings


def write_settings(path, changes, project=None):
    """`learning configure`: the only writer of the settings file; refuses a location inside the project."""
    location = Path(path).expanduser() if path else settings_path()
    _outside(location, project, "Procedural learning settings")
    current = load_settings(location, project)
    updated = validate_settings(_merge(current, changes))
    if location.is_symlink():
        raise LearningError("Procedural learning settings must not be a symlink.")
    location.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = location.with_name(location.name + ".tmp-" + hashlib.sha256(os.urandom(8)).hexdigest()[:8])
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({key: updated[key] for key in DEFAULTS}, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, location)
    finally:
        if temporary.exists():
            temporary.unlink()
    return updated


# ---------------------------------------------------------------- package catalog and base bodies


def _manifest(pack):
    base = Path(pack).resolve()
    catalog = base / "catalog"
    if (base / "scripts/runtime/catalog").is_dir():
        catalog = base / "scripts/runtime/catalog"
    read = _sibling("resources")["_read"]
    manifest = read(catalog / "resource-paths.json")
    if manifest.get("schema_version") != 1:
        raise LearningError("Package resource manifest is unsupported.")
    return base, catalog, manifest


def _safe_relative(base, relative):
    path = PurePosixPath(relative)
    if not isinstance(relative, str) or path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise LearningError("Package manifest path is unsafe.")
    target = (base / relative).resolve()
    if not target.is_relative_to(base):
        raise LearningError("Package manifest path escapes the package.")
    return target


def package_catalog(pack):
    """Registered ids of the installed package: roles, skills, recipes, capabilities, verification checks, workflows."""
    base, catalog, manifest = _manifest(pack)
    read = _sibling("resources")["_read"]
    loadouts = read(catalog / "loadouts.json")["roles"]
    skills = read(catalog / "skills.json")
    verifiers = {s["id"] for s in skills["skills"] if s.get("verifies")}
    roles = {r["id"]: r for r in loadouts}
    checks = set(verifiers)
    for role in loadouts:
        checks.update(role.get("verification", []))
    workflows = {}
    compose = _sibling("learning_compose")
    for recipe_id, relative in (manifest.get("recipes") or {}).items():
        target = _safe_relative(base, relative)
        sidecar = target.with_name(target.stem + ".workflow.json")
        if sidecar.is_file() and not sidecar.is_symlink():
            try:
                workflows[recipe_id] = compose["validate_workflow"](json.loads(sidecar.read_text(encoding="utf-8")), set(skills["capabilities"]))
            except (OSError, ValueError):
                continue  # An invalid sidecar makes the recipe non-evolvable, never partially evolvable.
    return {"roles": set(roles), "role_records": roles, "skills": set(manifest.get("guides") or {}), "recipes": set(manifest.get("recipes") or {}),
            "capabilities": set(skills["capabilities"]), "checks": checks, "workflows": workflows,
            "role_checks": {r["id"]: list(r.get("verification", [])) for r in loadouts}}


def package_digest(pack):
    """Installed catalog/build identity: catalog registries, the recipe workflows and the composition module."""
    base, catalog, manifest = _manifest(pack)
    parts = {}
    # Content identity, not layout: the resource manifest differs between the source, manual and Codex layouts of one build,
    # while the registries, workflows and composition module are byte-identical. A role overlay still binds to the host's
    # rendered role text through its base artifact digest.
    for name in ("loadouts.json", "skills.json"):
        parts[name] = hashlib.sha256((catalog / name).read_bytes()).hexdigest()
    for recipe_id, relative in sorted((manifest.get("recipes") or {}).items()):
        sidecar = _safe_relative(base, relative).with_name(PurePosixPath(relative).stem + ".workflow.json")
        if sidecar.is_file():
            parts["workflow:" + recipe_id] = hashlib.sha256(sidecar.read_bytes()).hexdigest()
    module = Path(__file__).resolve().with_name("learning_compose.py")
    parts["learning_compose.py"] = hashlib.sha256(module.read_bytes()).hexdigest()
    return _digest(parts)


def base_body(pack, kind, artifact_id):
    """The bundled artifact a revision composes onto, read through the package's bounded no-follow reader.

    Retrieval profiles bind to the retrieval module's bytes and verification hints to the registered check set; both
    have no text body to compose.
    """
    base, catalog, manifest = _manifest(pack)
    packet = _sibling("context_packet")
    section = {"skill_overlay": "guides", "role_method_overlay": "roles", "recipe_overlay": "recipes"}.get(kind)
    if section is None:
        if kind == "retrieval_profile":
            return {"content": None, "sha256": hashlib.sha256(Path(__file__).resolve().with_name("retrieval.py").read_bytes()).hexdigest()}
        if kind == "skill_selection":
            # Binds to the capability catalogs a selection was evaluated against; a catalog change makes it stale.
            return {"content": None, "sha256": _digest({name: hashlib.sha256((catalog / name).read_bytes()).hexdigest()
                                                        for name in ("skills.json", "external-skills.json", "mcp.json")})}
        return {"content": None, "sha256": _digest(sorted(package_catalog(pack)["checks"]))}
    relative = (manifest.get(section) or {}).get(artifact_id)
    if relative is None:
        raise LearningError("Target artifact is not registered in the installed package.")
    target = _safe_relative(base, relative)
    try:
        body = packet["_guidance"]({"id": artifact_id, "path": str(target)}, base)
    except ValueError:
        raise LearningError("Target artifact is missing, unsafe or over the package read limit.") from None
    if kind == "recipe_overlay":
        sidecar = target.with_name(target.stem + ".workflow.json")
        if sidecar.is_file() and not sidecar.is_symlink():
            body["sha256"] = _digest([body["sha256"], hashlib.sha256(sidecar.read_bytes()).hexdigest()])
    return body


def policy_digest(settings):
    """The admission policy a revision was validated under: kinds, review and evaluation thresholds, approval and canary
    ceilings, and the validator's own bytes. Runtime budgets are operational ceilings and stay outside it."""
    module = Path(__file__).resolve()
    return _digest({"kinds": sorted(settings["kinds"]), "review": settings["review"],
                    "evaluation": settings["evaluation"], "approval": settings["approval"], "canary": settings["canary"],
                    "learning.py": hashlib.sha256(module.read_bytes()).hexdigest(),
                    "learning_compose.py": hashlib.sha256(module.with_name("learning_compose.py").read_bytes()).hexdigest(),
                    "learning_eval.py": hashlib.sha256(module.with_name("learning_eval.py").read_bytes()).hexdigest()})


# ---------------------------------------------------------------- private store

_STORE = _sibling("repo_store")


class LearningStore(_STORE["_Base"]):
    """Immutable revisions, controller-owned lifecycle events, reviews, evaluations, approvals, generations,
    observations and enrollments. Opened through repo_store's hardened, owner-only, rollback-journal opener; a
    read-only open creates no side files and never migrates."""

    file_name = STORE_FILE
    tables = (
        "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS revisions(revision_id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL, kind TEXT NOT NULL, scope TEXT NOT NULL,"
        " created INTEGER NOT NULL, record TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS revisions_artifact ON revisions(artifact_id)",
        "CREATE TABLE IF NOT EXISTS lifecycle(id INTEGER PRIMARY KEY, revision_id TEXT NOT NULL, state TEXT NOT NULL, reason TEXT,"
        " created INTEGER NOT NULL, record TEXT)",
        "CREATE INDEX IF NOT EXISTS lifecycle_revision ON lifecycle(revision_id)",
        "CREATE TABLE IF NOT EXISTS reviews(review_id TEXT PRIMARY KEY, created INTEGER NOT NULL, record TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS evaluations(evaluation_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL, created INTEGER NOT NULL, record TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS approvals(approval_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL, created INTEGER NOT NULL,"
        " consumed INTEGER, record TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS generations(id INTEGER PRIMARY KEY, generation_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL,"
        " created INTEGER NOT NULL, record TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS observations(event_id TEXT PRIMARY KEY, task_family TEXT NOT NULL, created INTEGER NOT NULL, record TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS enrollments(namespace TEXT PRIMARY KEY, created INTEGER NOT NULL, record TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS tombstones(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, ident TEXT NOT NULL, reason TEXT, created INTEGER NOT NULL)",
    )

    def __init__(self, directory, *, create=False, readonly=False, namespace_kind="production"):
        if namespace_kind not in ("production", "test"):
            raise LearningError("Unknown namespace kind.")
        self._namespace_kind = namespace_kind
        super().__init__(directory, create=create, readonly=readonly)

    def _migrate(self):
        with self.transaction():
            for statement in self.tables:
                self.connection.execute(statement)
            row = self.connection.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
            if row is None:
                self.connection.execute("INSERT INTO meta(key, value) VALUES('schema', ?)", (str(SCHEMA),))
                self.connection.execute("INSERT INTO meta(key, value) VALUES('namespace_kind', ?)", (json.dumps(self._namespace_kind),))
            elif row[0] != str(SCHEMA):
                raise _STORE["StoreError"]("Learning store schema is unsupported; learned content is declined until an authorized migration.")

    def _check(self):
        try:
            row = self.connection.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        except sqlite3.Error:
            raise _STORE["StoreError"]("Learning store is empty, corrupt or incompatible.") from None
        if row is None or row[0] != str(SCHEMA):
            raise _STORE["StoreError"]("Learning store schema is unsupported; learned content is declined until an authorized migration.")

    @property
    def namespace_kind(self):
        return self.meta("namespace_kind", "production")

    # ---- revisions and lifecycle

    def add_revision(self, record):
        if self.connection.execute("SELECT 1 FROM revisions WHERE revision_id=?", (record["revision_id"],)).fetchone():
            return False
        self.connection.execute("INSERT INTO revisions(revision_id, artifact_id, kind, scope, created, record) VALUES(?,?,?,?,?,?)",
                                (record["revision_id"], record["artifact_id"], record["artifact_kind"], record["scope"], record["created"],
                                 json.dumps(record, sort_keys=True, separators=(",", ":"))))
        return True

    def revision(self, revision_id):
        row = self.connection.execute("SELECT record FROM revisions WHERE revision_id=?", (revision_id,)).fetchone()
        if row is None:
            return None
        record = json.loads(row[0])
        state, reason, _ = self.state_of(revision_id)
        record["state"], record["state_reason"] = state, reason
        return record

    def revisions(self, *, kind=None, artifact_id=None, scope=None, states=None):
        query, args = "SELECT revision_id FROM revisions", []
        clauses = []
        for column, value in (("kind", kind), ("artifact_id", artifact_id), ("scope", scope)):
            if value is not None:
                clauses.append(f"{column}=?")
                args.append(value)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        rows = [self.revision(row[0]) for row in self.connection.execute(query + " ORDER BY created, revision_id", args)]
        return [r for r in rows if states is None or r["state"] in states]

    def state_of(self, revision_id):
        row = self.connection.execute("SELECT state, reason, record FROM lifecycle WHERE revision_id=? ORDER BY id DESC LIMIT 1", (revision_id,)).fetchone()
        if row is None:
            return None, None, None
        return row[0], row[1], json.loads(row[2]) if row[2] else None

    def transition(self, revision_id, state, reason, record=None):
        current, _, _ = self.state_of(revision_id)
        if state not in TRANSITIONS.get(current, set()):
            raise LearningError(f"Lifecycle transition {current} -> {state} is not allowed.")
        self.connection.execute("INSERT INTO lifecycle(revision_id, state, reason, created, record) VALUES(?,?,?,?,?)",
                                (revision_id, state, (reason or "")[:240], _now(), json.dumps(record, sort_keys=True) if record is not None else None))
        return state

    def history(self, revision_id):
        rows = self.connection.execute("SELECT state, reason, created, record FROM lifecycle WHERE revision_id=? ORDER BY id", (revision_id,)).fetchall()
        return [{"state": r[0], "reason": r[1], "created": r[2], "record": json.loads(r[3]) if r[3] else None} for r in rows]

    # ---- reviews, evaluations, approvals

    def add_review(self, record):
        self.connection.execute("INSERT OR REPLACE INTO reviews(review_id, created, record) VALUES(?,?,?)",
                                (record["review_id"], record["created"], json.dumps(record, sort_keys=True, separators=(",", ":"))))

    def reviews(self):
        return [json.loads(r[0]) for r in self.connection.execute("SELECT record FROM reviews ORDER BY created, review_id")]

    def review(self, review_id):
        row = self.connection.execute("SELECT record FROM reviews WHERE review_id=?", (review_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def add_evaluation(self, record):
        self.connection.execute("INSERT OR REPLACE INTO evaluations(evaluation_id, revision_id, created, record) VALUES(?,?,?,?)",
                                (record["evaluation_id"], record["candidate_revision_id"], record["created"], json.dumps(record, sort_keys=True, separators=(",", ":"))))

    def evaluations(self, revision_id=None):
        query, args = "SELECT record FROM evaluations", ()
        if revision_id is not None:
            query, args = query + " WHERE revision_id=?", (revision_id,)
        return [json.loads(r[0]) for r in self.connection.execute(query + " ORDER BY created, evaluation_id", args)]

    def evaluation(self, evaluation_id):
        row = self.connection.execute("SELECT record FROM evaluations WHERE evaluation_id=?", (evaluation_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def add_approval(self, record):
        self.connection.execute("INSERT INTO approvals(approval_id, revision_id, created, consumed, record) VALUES(?,?,?,?,?)",
                                (record["approval_id"], record["revision_id"], record["created"], None, json.dumps(record, sort_keys=True, separators=(",", ":"))))

    def approvals(self, revision_id, *, unconsumed=False):
        query, args = "SELECT record, consumed FROM approvals WHERE revision_id=?", [revision_id]
        if unconsumed:
            query += " AND consumed IS NULL"
        return [dict(json.loads(r[0]), consumed=r[1]) for r in self.connection.execute(query + " ORDER BY created", args)]

    def consume_approval(self, approval_id, generation_id):
        changed = self.connection.execute("UPDATE approvals SET consumed=? WHERE approval_id=? AND consumed IS NULL", (_now(), approval_id)).rowcount
        if changed != 1:
            raise LearningError("Approval was already consumed by another promotion; re-approve against the current generation.")
        self.connection.execute("UPDATE approvals SET record=json_set(record, '$.consumed_by', ?) WHERE approval_id=?", (generation_id, approval_id))

    # ---- generations

    def active_generation(self):
        row = self.connection.execute("SELECT record FROM generations WHERE status='active' ORDER BY id DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None

    def generation(self, generation_id):
        row = self.connection.execute("SELECT record, status FROM generations WHERE generation_id=?", (generation_id,)).fetchone()
        return dict(json.loads(row[0]), status=row[1]) if row else None

    def generations(self):
        return [dict(json.loads(r[0]), status=r[1]) for r in self.connection.execute("SELECT record, status FROM generations ORDER BY id")]

    def publish_generation(self, record, expected_active):
        """Compare-and-swap inside the caller's transaction: the active pointer moves only if it is what the caller saw."""
        current = self.active_generation()
        current_id = current["generation_id"] if current else None
        if current_id != expected_active:
            raise LearningError("Active generation changed since this operation was prepared; inspect `learning status` and retry against the current generation.")
        self.connection.execute("UPDATE generations SET status='superseded' WHERE status='active'")
        self.connection.execute("INSERT INTO generations(generation_id, status, created, record) VALUES(?,?,?,?)",
                                (record["generation_id"], "active", record["created"], json.dumps(record, sort_keys=True, separators=(",", ":"))))
        return record

    # ---- observations, enrollments, tombstones

    def add_observation(self, record):
        if self.connection.execute("SELECT 1 FROM observations WHERE event_id=?", (record["event_id"],)).fetchone():
            return False
        self.connection.execute("INSERT INTO observations(event_id, task_family, created, record) VALUES(?,?,?,?)",
                                (record["event_id"], record["task_family"], record["created"], json.dumps(record, sort_keys=True, separators=(",", ":"))))
        return True

    def observations(self):
        return [json.loads(r[0]) for r in self.connection.execute("SELECT record FROM observations ORDER BY created, event_id")]

    def observation(self, event_id):
        row = self.connection.execute("SELECT record FROM observations WHERE event_id=?", (event_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def forget_observation(self, event_id, reason="forgotten"):
        removed = self.connection.execute("DELETE FROM observations WHERE event_id=?", (event_id,)).rowcount
        if removed:
            self.add_tombstone("observation", event_id, reason)
        return removed

    def add_tombstone(self, kind, ident, reason):
        self.connection.execute("INSERT INTO tombstones(kind, ident, reason, created) VALUES(?,?,?,?)", (kind, ident, (reason or "")[:240], _now()))

    def tombstones(self):
        return [dict(zip(("kind", "ident", "reason", "created"), r)) for r in self.connection.execute("SELECT kind, ident, reason, created FROM tombstones ORDER BY id")]

    def enroll(self, namespace, record):
        self.connection.execute("INSERT OR REPLACE INTO enrollments(namespace, created, record) VALUES(?,?,?)",
                                (namespace, record["created"], json.dumps(record, sort_keys=True, separators=(",", ":"))))

    def unenroll(self, namespace):
        return self.connection.execute("DELETE FROM enrollments WHERE namespace=?", (namespace,)).rowcount

    def enrollments(self):
        return [json.loads(r[0]) for r in self.connection.execute("SELECT record FROM enrollments ORDER BY created")]

    def delete_revision(self, revision_id, reason):
        """Prune: payload rows go, a non-content tombstone stays."""
        self.connection.execute("DELETE FROM revisions WHERE revision_id=?", (revision_id,))
        self.connection.execute("DELETE FROM evaluations WHERE revision_id=?", (revision_id,))
        self.connection.execute("DELETE FROM approvals WHERE revision_id=?", (revision_id,))
        self.connection.execute("DELETE FROM lifecycle WHERE revision_id=?", (revision_id,))
        self.add_tombstone("revision", revision_id, reason)

    def counts(self):
        out = {}
        for table in ("revisions", "reviews", "evaluations", "approvals", "generations", "observations", "enrollments", "tombstones"):
            out[table] = self.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        out["states"] = dict(self.connection.execute(
            "SELECT state, count(*) FROM lifecycle l WHERE id = (SELECT max(id) FROM lifecycle WHERE revision_id=l.revision_id) GROUP BY state").fetchall())
        return out


def repo_directory(project, identity=None):
    return _STORE["state_directory"](project, identity)


def profile_directory(profile):
    if not isinstance(profile, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", profile):
        raise LearningError("Profile must be a short lowercase name.")
    base = os.environ.get("XDG_CACHE_HOME", "")
    home = Path(base).resolve() if base and Path(base).is_absolute() else Path.home().resolve() / ".cache"
    return home / "agent-dispatcher" / "learning-v1" / ("profile-" + _digest({"profile": profile})[:32])


def repo_namespace(project, identity=None):
    """The repository namespace id: the private state directory name (resolved path, device and inode), never a URL."""
    return repo_directory(project, identity).name


def open_store(directory, *, create=False, readonly=True, namespace_kind="production"):
    try:
        return LearningStore(directory, create=create, readonly=readonly, namespace_kind=namespace_kind)
    except _STORE["StoreError"] as exc:
        message = str(exc)
        if "No repository index" in message:
            raise LearningError("No learning store exists for this scope.") from None
        raise LearningError(message.replace("Repository index", "Learning store")) from None


def store_exists(directory):
    """Something occupies the store path; the hardened opener decides whether it is a usable store (a symlink is refused, with a diagnostic)."""
    target = Path(directory) / STORE_FILE
    return target.is_symlink() or target.exists()


# ---------------------------------------------------------------- observations


def _bounded_list(value, what, limit, pattern=None):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(v, str) or not 0 < len(v) <= 200 for v in value):
        raise LearningError(f"Observation {what} must be a bounded list of short strings.")
    if pattern is not None and any(not pattern.fullmatch(v) for v in value):
        raise LearningError(f"Observation {what} contains an unregistered value.")
    return list(value)


def _measured(value, what):
    if value is None:
        return {"value": None, "provenance": "unavailable"}
    if not isinstance(value, dict) or set(value) - {"value", "provenance"}:
        raise LearningError(f"Observation resources.{what} must be {{value, provenance}}.")
    number, provenance = value.get("value"), value.get("provenance", "unavailable")
    if provenance not in ("measured", "estimated", "unavailable"):
        raise LearningError(f"Observation resources.{what}.provenance must be measured, estimated or unavailable.")
    if number is not None and (isinstance(number, bool) or not isinstance(number, (int, float)) or number != number or number in (float("inf"), float("-inf")) or number < 0):
        raise LearningError(f"Observation resources.{what}.value must be a finite non-negative number or null (unknown is null, never zero).")
    if (number is None) != (provenance == "unavailable"):
        raise LearningError(f"Observation resources.{what}: unknown is null with provenance unavailable, never zero; a measured value cannot be null.")
    return {"value": number, "provenance": provenance}


def family_of(event, supplied=None):
    """Logical task family: the harness's id when given, else a fingerprint of the request's strongest terms.

    ponytail: term-set fingerprinting groups paraphrases and repeated trials well enough for support counts; a
    harness with real task identity should supply `task_family` and skip the heuristic.
    """
    if isinstance(supplied, str) and 0 < len(supplied) <= 120 and re.fullmatch(r"[A-Za-z0-9._:-]+", supplied):
        return supplied
    terms = sorted(event["task"]["terms"].items(), key=lambda kv: (-kv[1], kv[0]))[:12]
    return "family-" + _digest([t for t, _ in terms])[:16]


def build_observation(document, event, *, generation_id=None):
    """Validate one explicit observation against its experience event; unknown fields are refused, unknowns stay null."""
    compose = _sibling("learning_compose")
    if not isinstance(document, dict):
        raise LearningError("Observation must be a JSON object.")
    allowed = {"schema_version", "event_id", "task_family", "sequence", "snapshot", "configuration", "exposure", "workflow",
               "failure_categories", "feedback_class", "user_accepted", "tests_changed", "resources", "limits_of_observation", "notes"}
    unknown = set(document) - allowed
    if unknown:
        raise LearningError("Observation carries an unknown field.")
    if document.get("schema_version") != SCHEMA:
        raise LearningError("Unsupported observation schema version.")
    if document.get("event_id") != event["id"]:
        raise LearningError("Observation event_id does not name the experience event.")
    feedback = document.get("feedback_class", "user_host")
    if feedback not in FEEDBACK:
        raise LearningError("Observation feedback_class is unknown.")
    exposure = []
    for item in document.get("exposure") or []:
        if (not isinstance(item, dict) or set(item) - {"revision_id", "state"} or not isinstance(item.get("revision_id"), str)
                or not compose["REVISION"].fullmatch(item["revision_id"]) or item.get("state") not in EXPOSURES):
            raise LearningError("Observation exposure entries need a revision id and a known exposure state.")
        exposure.append({"revision_id": item["revision_id"], "state": item["state"]})
    if len(exposure) > 40:
        raise LearningError("Observation lists too many exposures.")
    workflow = document.get("workflow") or {}
    if not isinstance(workflow, dict) or set(workflow) - {"steps", "checks", "retrieval"}:
        raise LearningError("Observation workflow must be {steps, checks, retrieval}.")
    retrieval = workflow.get("retrieval") or {}
    if not isinstance(retrieval, dict) or set(retrieval) - {"history_expansion", "profile", "strategy"}:
        raise LearningError("Observation workflow.retrieval has an unknown field.")
    if retrieval.get("history_expansion", "unknown") not in ("used", "unavailable", "not_applicable", "unknown"):
        raise LearningError("Observation history_expansion must be used, unavailable, not_applicable or unknown.")
    snapshot = document.get("snapshot") or {}
    if not isinstance(snapshot, dict) or set(snapshot) - {"baseline", "final"}:
        raise LearningError("Observation snapshot must be {baseline, final}.")
    for side in ("baseline", "final"):
        part = snapshot.get(side)
        if part is not None and (not isinstance(part, dict) or set(part) - {"head", "dirty", "tree_digest"}
                                 or (part.get("dirty") is not None and type(part["dirty"]) is not bool)
                                 or (part.get("tree_digest") is not None and not compose["HEX"].fullmatch(str(part["tree_digest"])))):
            raise LearningError(f"Observation snapshot.{side} must be {{head, dirty, tree_digest}}.")
    configuration = document.get("configuration") or {}
    if not isinstance(configuration, dict) or set(configuration) - {"package_digest", "effective_guidance_digest", "generation_id", "revisions_available", "policy_digest"}:
        raise LearningError("Observation configuration has an unknown field.")
    for key in ("user_accepted", "tests_changed"):
        if document.get(key) is not None and type(document[key]) is not bool:
            raise LearningError(f"Observation {key} must be a boolean or null.")
    resources = document.get("resources") or {}
    if not isinstance(resources, dict) or set(resources) - {"tokens", "cost_usd", "duration_s", "steps"}:
        raise LearningError("Observation resources has an unknown field.")
    sequence = document.get("sequence")
    if sequence is not None and (not isinstance(sequence, dict) or set(sequence) - {"harness", "position"} or type(sequence.get("position", 0)) is not int):
        raise LearningError("Observation sequence must be {harness, position}.")
    notes = document.get("notes")
    if notes is not None and (not isinstance(notes, str) or len(notes) > 400):
        raise LearningError("Observation notes must be at most 400 characters.")
    record = {"schema_version": SCHEMA, "event_id": event["id"], "task_id": event["task_id"],
              "task_family": family_of(event, document.get("task_family")), "task_digest": event["task"]["digest"],
              "role": event.get("role"), "outcome": event["outcome"], "outcome_reason": event.get("outcome_reason"),
              "checks": event.get("checks"), "source": event.get("source"), "recorded": event["recorded"],
              "sequence": sequence, "snapshot": {"baseline": snapshot.get("baseline") or event.get("baseline"), "final": snapshot.get("final") or {"tree_digest": None, "head": None, "dirty": None,
                                                                                                                                              "edited_digest": (event.get("final") or {}).get("digest")}},
              "configuration": {"package_digest": configuration.get("package_digest"), "effective_guidance_digest": configuration.get("effective_guidance_digest"),
                                "generation_id": configuration.get("generation_id", generation_id), "policy_digest": configuration.get("policy_digest"),
                                "revisions_available": _bounded_list(configuration.get("revisions_available"), "configuration.revisions_available", 40, compose["REVISION"])},
              "exposure": exposure,
              "workflow": {"steps": _bounded_list(workflow.get("steps"), "workflow.steps", 40, compose["ID"]),
                           "checks": _bounded_list(workflow.get("checks"), "workflow.checks", 40, compose["ID"]),
                           "retrieval": {"history_expansion": retrieval.get("history_expansion", "unknown"),
                                         "profile": retrieval.get("profile") if isinstance(retrieval.get("profile"), str) and compose["REVISION"].fullmatch(retrieval["profile"]) else None,
                                         "strategy": retrieval.get("strategy") if isinstance(retrieval.get("strategy"), str) and len(retrieval["strategy"]) <= 40 else None}},
              "failure_categories": _bounded_list(document.get("failure_categories"), "failure_categories", 12, re.compile("|".join(FAILURE_CATEGORIES) + r"\Z")),
              "feedback_class": feedback, "user_accepted": document.get("user_accepted"),
              "tests_changed": document.get("tests_changed", event.get("tests_changed")),
              "resources": {key: _measured(resources.get(key), key) for key in ("tokens", "cost_usd", "duration_s", "steps")},
              "limits_of_observation": _bounded_list(document.get("limits_of_observation"), "limits_of_observation", 8),
              "notes": notes, "created": _now()}
    return record


def experience_store(directory, *, readonly=True):
    try:
        return _STORE["ExperienceStore"](directory, readonly=readonly)
    except _STORE["StoreError"]:
        return None


def observe(store, experience, document):
    """Persist one observation keyed to an existing experience event; identical events are idempotent."""
    if not isinstance(document, dict) or not isinstance(document.get("event_id"), str):
        raise LearningError("Observation needs the experience event id.")
    event = experience.get_event(document["event_id"]) if experience is not None else None
    if event is None:
        raise LearningError("Observation refers to an experience event this project has not recorded.")
    record = build_observation(document, event, generation_id=(store.active_generation() or {}).get("generation_id"))
    with store.transaction():
        stored = store.add_observation(record)
    return {"stored": stored, "event_id": record["event_id"], "task_family": record["task_family"], "feedback_class": record["feedback_class"],
            "outcome": record["outcome"], "reason": "duplicate observation ignored" if not stored else "recorded"}


# ---------------------------------------------------------------- support and invalidation


def support_status(store, experience, revision):
    """How much of a revision's evidence still stands: forgotten or superseded events withdraw support."""
    ids = revision.get("supporting_event_ids") or []
    if not ids:
        return {"declared": 0, "current": 0, "withdrawn": 0, "synthetic": 0, "families": 0}
    current, withdrawn, synthetic, families = 0, 0, 0, set()
    observations = {o["event_id"]: o for o in store.observations()}
    for ident in ids:
        event = experience.get_event(ident) if experience is not None else None
        if event is None or event.get("status", "current") != "current":
            withdrawn += 1
            continue
        current += 1
        observation = observations.get(ident)
        if observation and observation["feedback_class"] == "synthetic_fixture":
            synthetic += 1
        families.add(observation["task_family"] if observation else family_of(event))
    return {"declared": len(ids), "current": current, "withdrawn": withdrawn, "synthetic": synthetic, "families": len(families)}


def sync_support(store, experience, settings, *, reason="support withdrawn by correction or forgetting"):
    """Consult the experience store's invalidations; suspend revisions whose evidence no longer suffices."""
    changed, suspended = [], []
    minimum = settings["review"]["min_support_families"]
    for revision in store.revisions():
        if "stale_support" not in TRANSITIONS.get(revision["state"], set()) or (revision["created_by_kind"] == "human" and not revision["supporting_event_ids"]):
            continue  # Already inactive, terminal or unsupported by design: nothing to suspend.
        status = support_status(store, experience, revision)
        if status["declared"] and status["withdrawn"] and (status["families"] < minimum or status["current"] == 0):
            with store.transaction():
                if revision["state"] in LIVE:
                    suspended.append(revision["revision_id"])
                store.transition(revision["revision_id"], "stale_support", reason, {"support": status})
            changed.append(revision["revision_id"])
    if suspended:
        _republish_without(store, suspended, settings, reason)
    return {"changed": changed, "suspended": suspended}


def _republish_without(store, revision_ids, settings, reason):
    active = store.active_generation()
    if not active:
        return None
    remaining = [r for r in active["revision_ids"] if r not in set(revision_ids)]
    if remaining == active["revision_ids"]:
        return active
    return _new_generation(store, remaining, active["generation_id"], settings, reason, canaries={k: v for k, v in (active.get("canaries") or {}).items() if k in remaining})


def _new_generation(store, revision_ids, expected_active, settings, reason, *, canaries=None, restored_from=None, pack_digest=None):
    record = {"schema_version": SCHEMA, "revision_ids": sorted(revision_ids), "parent_generation": expected_active, "created": _now(),
              "reason": (reason or "")[:240], "policy_digest": policy_digest(settings), "base_package_digest": pack_digest,
              "canaries": canaries or {}, "restored_from": restored_from}
    record["generation_id"] = _digest({k: v for k, v in record.items() if k != "created"} | {"created": record["created"]})
    with store.transaction():
        store.publish_generation(record, expected_active)
    return record


# ---------------------------------------------------------------- review


def _families(events, observations, *, production):
    """Deduplicated evidence: one row per logical task family, latest current event first; synthetic rows are excluded in production."""
    rows, excluded = {}, {"synthetic": 0, "not_current": 0}
    for event in events:
        if event.get("status", "current") != "current":
            excluded["not_current"] += 1
            continue
        observation = observations.get(event["id"])
        if production and observation and observation["feedback_class"] == "synthetic_fixture":
            excluded["synthetic"] += 1
            continue
        family = observation["task_family"] if observation else family_of(event)
        row = {"family": family, "event_id": event["id"], "recorded": event["recorded"], "outcome": event["outcome"], "role": event.get("role"),
               "observation": observation, "feedback_class": observation["feedback_class"] if observation else "user_host"}
        if family not in rows or rows[family]["recorded"] < row["recorded"]:
            rows[family] = row
    return list(rows.values()), excluded


WEAK_OUTCOMES = ("exit_code_only", "zero_tests", "stale_checks", "insufficient_evidence")
POSITIVE_OUTCOMES = ("checked_success", "accepted", "grader_passed")


def review_experience(store, experience, settings, catalog, *, cursor=None, scope="repo", now=None):
    """Deterministic pattern review over admitted evidence -> hypotheses or no_change, with support and contradictions."""
    now = now if now is not None else _now()
    events = experience.events(status=None) if experience is not None else []
    observations = {o["event_id"]: o for o in store.observations()}
    production = store.namespace_kind != "test"
    families, excluded = _families(events, observations, production=production)
    if cursor:
        families = [f for f in families if f["recorded"] > cursor.get("recorded_before", -1)]
    minimum = settings["review"]["min_support_families"]
    hypotheses, no_change, warnings, quarantine = [], [], [], []
    active = store.active_generation() or {"revision_ids": []}
    active_revisions = {r["revision_id"]: r for r in store.revisions(states=LIVE + ("experimental_canary",))}

    def hypothesis(pattern, kind, target, operation, support, contra, applicability, payload, wording, note, extra=None):
        entry = {"pattern": pattern, "kind": kind, "target": target, "operation": operation, "scope": scope,
                 "support_families": len(support), "supporting_event_ids": sorted(r["event_id"] for r in support)[:400],
                 "contradicting_families": len(contra), "counterexample_ids": sorted(r["event_id"] for r in contra)[:400],
                 "task_families": sorted({r["family"] for r in support})[:400],
                 "feedback_classes": dict(sorted(__import__("collections").Counter(r["feedback_class"] for r in support).items())),
                 "applicability": applicability, "payload": payload, "wording": wording, "note": note}
        if extra:
            entry.update(extra)
        if len(support) >= minimum:
            hypotheses.append(entry)
        else:
            no_change.append({"pattern": pattern, "reason": f"insufficient_evidence: {len(support)} independent task famil{'y' if len(support) == 1 else 'ies'} < {minimum}",
                              "support_families": len(support), "contradicting_families": len(contra)})

    # 1. Weak verification evidence per role: a hint that names the role's registered checks, deterministic wording.
    by_role = {}
    for row in families:
        by_role.setdefault(row["role"], []).append(row)
    for role, rows in sorted(by_role.items(), key=lambda kv: str(kv[0])):
        if role is None or role not in catalog["roles"]:
            continue
        weak = [r for r in rows if r["outcome"] in WEAK_OUTCOMES]
        strong = [r for r in rows if r["outcome"] in POSITIVE_OUTCOMES]
        checks = [c for c in catalog["role_checks"].get(role, []) if c in catalog["checks"]]
        if weak and checks and "verification_hint" in settings["kinds"]:
            hypothesis("weak_verification_evidence", "verification_hint", "verification", "create", weak, strong,
                       {"roles": [role]}, {"order_first": checks[:3], "note": "Run the scoped checks before reporting; a command exit or unknown test count is not verified success."},
                       "deterministic", f"{len(weak)} task families for role {role} ended with weak or absent check evidence")
        failed = [r for r in rows if r["outcome"] == "failed_checks"]
        if failed and "skill_overlay" in settings["kinds"]:
            skill = next((s for s in (catalog["role_records"].get(role) or {}).get("skills", {}).get("core", []) if s in catalog["skills"]), None)
            if skill:
                hypothesis("recurring_failed_checks", "skill_overlay", skill, "refine", failed, strong,
                           {"roles": [role]}, None, "host_required",
                           f"{len(failed)} task families for role {role} ended with failing checks; a failure-handling branch needs host-authored wording")
    # 2. History expansion helped when used and was missed when unavailable: the debug-recipe optional branch.
    if "recipe_overlay" in settings["kinds"] and "debug-application" in catalog.get("workflows", {}):
        used = [r for r in families if r["observation"] and r["observation"]["workflow"]["retrieval"]["history_expansion"] == "used" and r["outcome"] in POSITIVE_OUTCOMES]
        contra = [r for r in families if r["observation"] and r["observation"]["workflow"]["retrieval"]["history_expansion"] == "used" and r["outcome"] not in POSITIVE_OUTCOMES]
        if used:
            hypothesis("history_expansion_helped", "recipe_overlay", "debug-application", "refine", used, contra,
                       {"recipes": ["debug-application"], "roles": ["debugger"], "task_terms": ["regression", "bug", "failing", "broke", "crash"], "min_term_matches": 1},
                       {"slot": "workflow", "insert": [{"id": "eligible-history-expansion", "after": "gather-evidence",
                                                        "text": "Expand evidence with eligible commit history for the failing files: recent changes, co-changed partners and changed symbols, through the repository memory helper only.",
                                                        "condition": "eligible history is available for this repository and the incident is not live",
                                                        "fallback": "Continue with source and symbol retrieval; an unavailable history store is a documented gap, never a reason to build one mid-task."}]},
                       "deterministic", f"{len(used)} task families succeeded after using eligible history; {len(contra)} used it without success")
    # 3. Stale active artifacts: the base changed under an approved overlay.
    for revision in active_revisions.values():
        current = _current_base_digest(store, revision)
        if current is not None and current != revision["base_artifact_digest"]:
            hypotheses.append({"pattern": "stale_base", "kind": revision["artifact_kind"], "target": revision["artifact_id"], "operation": "deprecate",
                               "scope": revision["scope"], "parent_revision_ids": [revision["revision_id"]], "support_families": 0,
                               "supporting_event_ids": [], "contradicting_families": 0, "counterexample_ids": [], "task_families": [],
                               "feedback_classes": {}, "applicability": revision["applicability"], "payload": None, "wording": "deterministic",
                               "note": "the bundled base changed since this overlay was evaluated; it falls back at runtime until revalidated"})
    # 4. Already-effective overlays: recorded applications with success are support, not a reason for another change.
    for revision_id, revision in active_revisions.items():
        applied = [r for r in families if r["observation"] and any(x["revision_id"] == revision_id and x["state"] in ("reported_applied", "host_confirmed_read") for x in r["observation"]["exposure"])]
        if applied:
            no_change.append({"pattern": "already_effective", "revision_id": revision_id, "reason": "an active overlay was applied in earlier tasks; success while loaded is not causal benefit, and no change is proposed",
                              "support_families": len([r for r in applied if r["outcome"] in POSITIVE_OUTCOMES]), "contradicting_families": len([r for r in applied if r["outcome"] not in POSITIVE_OUTCOMES])})
    # 5. Severe failures: warn immediately; quarantine an emitted overlay; never authorize a replacement.
    for row in families:
        observation = row["observation"]
        if observation and {"security_concern", "verification_bypass"} & set(observation["failure_categories"]):
            emitted = [x["revision_id"] for x in observation["exposure"] if x["state"] in ("emitted", "host_confirmed_read", "reported_applied") and x["revision_id"] in active_revisions]
            warnings.append({"event_id": row["event_id"], "categories": sorted({"security_concern", "verification_bypass"} & set(observation["failure_categories"])), "emitted_revisions": emitted})
            quarantine.extend(emitted)
    hypotheses.sort(key=lambda h: (-h["support_families"], h["pattern"], h["target"]))
    kept = hypotheses[:settings["review"]["max_candidates"]]
    for extra in hypotheses[settings["review"]["max_candidates"]:]:
        no_change.append({"pattern": extra["pattern"], "reason": "review candidate cap reached", "support_families": extra["support_families"], "contradicting_families": extra["contradicting_families"]})
    review = {"schema_version": SCHEMA, "scope": scope, "created": now, "cursor": {"recorded_before": max((f["recorded"] for f in families), default=cursor.get("recorded_before", -1) if cursor else -1),
                                                                                    "events_seen": len(events)},
              "filtered": {"families": len(families), "events": len(events), **excluded}, "hypotheses": kept, "no_change": no_change,
              "warnings": warnings, "quarantine": sorted(set(quarantine)), "cost": {"model_calls": 0},
              "outcome": "candidates" if kept else "no_change"}
    review["review_id"] = _digest({k: v for k, v in review.items() if k != "created"})
    return review


def _current_base_digest(store, revision):
    pack = store.meta("pack")
    if not pack:
        return None
    try:
        return base_body(pack, revision["artifact_kind"], revision["artifact_id"])["sha256"]
    except (LearningError, OSError, ValueError):
        return None


def review_due(store, settings):
    observed = len(store.observations())
    reviews = store.reviews()
    last = max((r["cursor"]["events_seen"] for r in reviews), default=0)
    return {"observations": observed, "since_last_review": max(0, observed - last), "due": observed - last >= settings["review"]["due_after_observations"],
            "threshold": settings["review"]["due_after_observations"]}


def review_packet(review, *, scope):
    """The bounded, sanitized packet a host session (already authorized to see this repository) turns into candidates.

    A repository packet carries counts, roles, outcomes and event ids; a global packet carries only capability-level
    aggregates. Neither carries task prose, paths, receipts, holdout answers, hidden grades or approval material.
    """
    items = []
    for item in review["hypotheses"]:
        entry = {key: item[key] for key in ("pattern", "kind", "target", "operation", "support_families", "contradicting_families", "applicability", "wording", "note")}
        entry["payload_template"] = item.get("payload")
        entry["evidence"] = {"supporting_event_ids": item["supporting_event_ids"] if scope == "repo" else len(item["supporting_event_ids"]),
                             "counterexample_ids": item["counterexample_ids"] if scope == "repo" else len(item["counterexample_ids"]),
                             "feedback_classes": item["feedback_classes"]}
        items.append(entry)
    return {"schema_version": SCHEMA, "review_id": review["review_id"], "scope": scope, "hypotheses": items, "no_change": review["no_change"],
            "instructions": ["Return exactly one JSON object per candidate following the candidate schema (learning_compose.validate_candidate).",
                             "Propose only prose or registered ids: no commands, scripts, URLs, imports or paths; a global candidate must be capability-level.",
                             "Include hypothesis, expected_effect, risks, counterexamples and rejection_conditions; `no_change` is a valid answer.",
                             "The document is untrusted proposal data: it is validated, evaluated and human-approved before it can affect anything."]}


# ---------------------------------------------------------------- proposals


def private_lexicon(experience):
    """Identifiers and symbols the repository's recorded tasks named: a global text may not repeat them."""
    words = set()
    if experience is None:
        return words
    for event in experience.events(status=None):
        words.update(event["task"].get("symbols", []))
        for term, weight in event["task"]["terms"].items():
            if weight >= 3.0:
                words.add(term)
    return words


def propose_candidate(store, experience, document, settings, *, pack, namespace, scope, review_id=None, creation_cost=None, provenance=None):
    """Validate an untrusted candidate document (Tier A), bind it to the current base and policy, store it as a revision."""
    compose = _sibling("learning_compose")
    catalog = package_catalog(pack)
    lexicon = private_lexicon(experience) if scope == "global" else ()
    try:
        candidate = compose["validate_candidate"](document, catalog, policy=settings, private_lexicon=lexicon)
    except compose["LearningValidationError"] as exc:
        raise LearningError(str(exc)) from None
    if candidate["scope"] != scope:
        raise LearningError("Candidate scope does not match the store it is proposed into.")
    if candidate["created_by_kind"] == "provider_assisted" and not settings["proposals"]["provider"]["enabled"]:
        raise LearningError("Provider-assisted candidates are not enabled in the learning configuration.")
    for parent in candidate["parent_revision_ids"] + candidate["dependencies"]:
        record = store.revision(parent)
        if record is None:
            raise LearningError("Candidate names a parent or dependency revision this store does not hold.")
        if record["state"] in ("revoked", "quarantined", "rejected", "invalid"):
            raise LearningError("Candidate inherits from a revoked, quarantined or rejected revision; descendants stay untrusted.")
        if candidate["scope"] == "global" and record.get("privacy_classification") == "never_global":
            raise LearningError("Candidate generalizes a revision classified never_global.")
    production = store.namespace_kind != "test"
    if candidate["supporting_event_ids"]:
        missing = [i for i in candidate["supporting_event_ids"] if experience is None or experience.get_event(i) is None]
        if missing:
            raise LearningError("Candidate cites supporting events this project has not recorded.")
        if production:
            synthetic = [i for i in candidate["supporting_event_ids"] if (store.observation(i) or {}).get("feedback_class") == "synthetic_fixture"]
            if synthetic:
                raise LearningError("Candidate cites synthetic fixture evidence; it cannot enter a production library.")
    elif candidate["created_by_kind"] != "human" and candidate["operation"] not in ("deprecate", "generalize"):
        raise LearningError("A generated candidate must cite the observations that support it.")
    try:
        base = base_body(pack, candidate["kind"], candidate["target"]["artifact_id"])
    except LearningError:
        raise
    record = compose["revision_record"](candidate, base_package_digest=package_digest(pack), base_artifact_digest=base["sha256"],
                                        policy_digest=policy_digest(settings), namespace=namespace,
                                        evidence_cutoff=max([experience.get_event(i)["recorded"] for i in candidate["supporting_event_ids"]] or [None]) if experience is not None and candidate["supporting_event_ids"] else None,
                                        created=_now(), creation_cost=creation_cost,
                                        source_provenance={"created_by_kind": candidate["created_by_kind"], "review_id": review_id,
                                                           "inherits": candidate["parent_revision_ids"] + candidate["logical_parent_ids"], **(provenance or {})})
    with store.transaction():
        if not store.meta("pack"):
            store.set_meta("pack", str(Path(pack).resolve()))
        stored = store.add_revision(record)
        if stored:
            store.transition(record["revision_id"], "proposed", "candidate imported", {"review_id": review_id, "created_by_kind": candidate["created_by_kind"]})
            store.transition(record["revision_id"], "validated", "structural and security validation passed (Tier A); utility unproven")
    return {"revision_id": record["revision_id"], "stored": stored, "state": "validated" if stored else store.revision(record["revision_id"])["state"],
            "kind": candidate["kind"], "artifact_id": candidate["target"]["artifact_id"], "slot": candidate["target"]["slot"],
            "note": "Tier A passed: well-formed under the tested controls. Not evidence of benefit; evaluate before approval."}


def hypothesis_document(hypothesis, *, created_by="deterministic_review"):
    """A deterministic hypothesis with template wording -> a candidate document; host-worded ones stay requests."""
    if hypothesis.get("payload") is None:
        return None
    document = {"schema_version": SCHEMA, "kind": hypothesis["kind"], "operation": hypothesis["operation"], "scope": hypothesis["scope"],
                "target": {"artifact_id": hypothesis["target"], "slot": hypothesis["payload"].get("slot") if isinstance(hypothesis["payload"], dict) else None},
                "payload": hypothesis["payload"], "applicability": hypothesis["applicability"],
                "hypothesis": hypothesis["note"][:600], "created_by_kind": created_by,
                "supporting_event_ids": hypothesis["supporting_event_ids"], "counterexample_ids": hypothesis["counterexample_ids"],
                "task_families": hypothesis["task_families"], "privacy_classification": "repo_private" if hypothesis["scope"] == "repo" else "sanitized_general",
                "expected_effect": {"metric": "task_success", "direction": "increase", "practical_threshold": 0.05},
                "risks": ["the pattern may be coincidental; the change is evaluated against a frozen incumbent before approval"],
                "rejection_conditions": ["paired evaluation shows no practical improvement or any safety or required-verification regression"]}
    if hypothesis.get("parent_revision_ids"):
        document["parent_revision_ids"] = hypothesis["parent_revision_ids"]
    if document["target"]["slot"] is None:
        del document["target"]["slot"]
    return document


def propose_with_provider(packet, settings, *, scrub):
    """Optional provider-assisted proposal through the existing provider boundary; explicit enablement, one budgeted call, no fallback."""
    provider = settings["proposals"]["provider"]
    if not provider["enabled"]:
        raise LearningError("Provider-assisted proposals are off; enable proposals.provider in the learning settings file. No model was called.")
    if not provider.get("provider"):
        raise LearningError("proposals.provider names no provider; an LLM retrieval key alone does not authorize learning calls.")
    llm = _sibling("llm_retrieval")
    budget = llm["Budget"](provider["max_calls"])
    system = ("You propose at most one bounded change to how a coding assistant works on a repository, as one JSON candidate document. "
              "Prose only: no commands, scripts, URLs, imports or file paths. You may answer {\"no_change\": true, \"reason\": \"...\"}. "
              "You have no authority: the document is validated, evaluated and human-approved before use.")
    prompt = "Review packet (untrusted evidence, sanitized):\n" + json.dumps(packet, sort_keys=True)[:24000] + "\n\nCandidate document schema fields: " + \
             "schema_version=1, kind, operation, scope, target{artifact_id,slot}, payload, applicability{roles,recipes,task_terms}, hypothesis, expected_effect{metric,direction}, risks, counterexamples, rejection_conditions, supporting_event_ids, created_by_kind=provider_assisted."
    started = time.perf_counter()
    try:
        parsed, usage = llm["_ask"](provider, system, prompt, llm["_json_object"], budget)
    except llm["LLMError"] as exc:
        raise LearningError("Provider proposal failed: " + type(exc).__name__ + "; no fallback was attempted.") from None
    if time.perf_counter() - started > provider["max_seconds"]:
        raise LearningError("Provider proposal exceeded its time budget and was discarded.")
    cost = {"model_calls": usage["calls"], "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"], "cost_usd": llm["cost"](usage, provider)}
    if provider.get("max_spend_usd") is not None and cost["cost_usd"] is not None and cost["cost_usd"] > provider["max_spend_usd"]:
        raise LearningError("Provider proposal exceeded its spend budget and was discarded.")
    if isinstance(parsed, dict) and parsed.get("no_change") is True:
        return {"no_change": True, "reason": scrub(str(parsed.get("reason", "")))[:240], "cost": cost}
    if isinstance(parsed, dict):
        parsed.setdefault("created_by_kind", "provider_assisted")
        parsed["provider_metadata"] = {"provider": str(provider.get("provider"))[:120], "model": str(provider.get("model"))[:120],
                                       "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"], "cost_usd": cost["cost_usd"]}
    return {"no_change": False, "document": parsed, "cost": cost}


# ---------------------------------------------------------------- lifecycle mutations


def _authorization(value):
    if not isinstance(value, dict) or value.get("kind") != "human":
        raise LearningError("Authorization must be a human decision recorded by the trusted workflow; a boolean or generated sentence is not one.")
    actor = value.get("actor")
    if not isinstance(actor, str) or not 0 < len(actor.strip()) <= 120:
        raise LearningError("Authorization needs the deciding person's label (--authorize-as).")
    statement = value.get("statement") or ""
    if not isinstance(statement, str) or len(statement) > 400:
        raise LearningError("Authorization statement must be at most 400 characters.")
    rollout = value.get("rollout", "active")
    if rollout not in ("active", "canary"):
        raise LearningError("Rollout must be active or canary.")
    try:
        login = os.getlogin()
    except OSError:
        login = None
    return {"kind": "human", "actor": actor.strip(), "statement": statement.strip(), "rollout": rollout, "uid": os.getuid(), "login": login,
            "recorded": _now(), "note": "Recorded by the CLI the host let this user run; the host, not this file, authenticates the person."}


def bundle_digest(store, pack, revision_ids, settings):
    """Digest of the fully composed guidance a set of revisions yields over the current base and package."""
    compose = _sibling("learning_compose")
    parts = {"package": package_digest(pack), "policy": policy_digest(settings), "artifacts": {}}
    grouped = {}
    for ident in sorted(revision_ids):
        revision = store.revision(ident)
        if revision is None:
            raise LearningError("Bundle names a revision this store does not hold.")
        grouped.setdefault((revision["artifact_kind"], revision["artifact_id"], (revision["editable_slot_ids"] or [None])[0]), []).append(revision)
    for (kind, artifact_id, slot), revisions in grouped.items():
        base = base_body(pack, kind, artifact_id)
        if kind in ("retrieval_profile", "verification_hint", "skill_selection"):
            parts["artifacts"][f"{kind}:{artifact_id}"] = _digest([base["sha256"], [r["typed_payload"] for r in sorted(revisions, key=lambda r: r["revision_id"])]])
            continue
        layers = [_layer(r) for r in sorted(revisions, key=lambda r: (r["scope"] != "global", r["revision_id"]))]
        workflow = None
        if kind == "recipe_overlay":
            workflows = package_catalog(pack)["workflows"]
            workflow = compose["workflow_view"](workflows[artifact_id]) if artifact_id in workflows else None
        composed = compose["compose"](kind, base["content"], layers, workflow)
        parts["artifacts"][f"{kind}:{artifact_id}:{slot}"] = {"base": base["sha256"], "effective": compose["text_digest"](composed["content"]), "state": composed["state"]}
    return _digest(parts)


def _layer(revision):
    payload = revision["typed_payload"]
    return {"revision_id": revision["revision_id"], "scope": revision["scope"], "slot": payload.get("slot"), "text": payload.get("text"), "insert": payload.get("insert")}


def approve_candidate(store, experience, revision_id, evaluation_id, expected_generation, authorization, settings, *, pack, canary=None):
    """Bind a human decision to the exact candidate, evaluation, composed bundle, policy and incumbent generation."""
    revision = store.revision(revision_id)
    if revision is None:
        raise LearningError("Unknown candidate revision.")
    if revision["state"] not in ("evaluation_passed", "awaiting_approval"):
        raise LearningError(f"Candidate is {revision['state']}; only a candidate whose evaluation passed can be approved.")
    compose = _sibling("learning_compose")
    if not compose["revision_digest_matches"](revision):
        with store.transaction():
            store.transition(revision_id, "invalid", "stored revision bytes do not match their id")
        raise LearningError("Stored revision does not match its id; it was marked invalid.")
    evaluation = store.evaluation(evaluation_id)
    if evaluation is None or evaluation["candidate_revision_id"] != revision_id:
        raise LearningError("Evaluation does not belong to this candidate.")
    if evaluation["status"] != "passed":
        raise LearningError(f"Evaluation status is {evaluation['status']}; only a passed evaluation supports approval, and no flag converts an inconclusive one.")
    if not evaluation["evaluator"]["authoritative"] and store.namespace_kind != "test":
        raise LearningError("Evaluation came from a non-authoritative runner (test-only); it cannot support a production approval.")
    active = store.active_generation()
    active_id = active["generation_id"] if active else None
    if expected_generation != active_id:
        raise LearningError("Expected generation is not the active generation; re-inspect `learning status` before approving.")
    if evaluation["incumbent_generation_id"] != active_id:
        raise LearningError("Evaluation compared against a different incumbent generation; re-evaluate against the current one.")
    if evaluation["policy_digest"] != policy_digest(settings):
        raise LearningError("Learning policy changed since the evaluation; re-evaluate under the current policy.")
    current_bundle = bundle_digest(store, pack, (active["revision_ids"] if active else []) + [revision_id], settings)
    if evaluation["candidate_bundle_digest"] != current_bundle:
        raise LearningError("The composed candidate bundle changed since the evaluation (base or package drift); re-evaluate.")
    support = support_status(store, experience, revision)
    if support["withdrawn"]:
        raise LearningError("Some supporting evidence was corrected or forgotten since the candidate was created; re-run review.")
    decision = _authorization(authorization)
    if decision["rollout"] == "canary":
        canary = canary or {}
        tasks, days = canary.get("max_tasks", settings["canary"]["max_tasks"]), canary.get("max_days", settings["canary"]["max_days"])
        if type(tasks) is not int or not 1 <= tasks <= settings["canary"]["max_tasks"] or type(days) is not int or not 1 <= days <= settings["canary"]["max_days"]:
            raise LearningError("Canary bounds exceed the configured ceilings.")
        decision["canary"] = {"max_tasks": tasks, "expires": _now() + days * 86400}
    record = {"schema_version": SCHEMA, "revision_id": revision_id, "evaluation_id": evaluation_id, "expected_generation": expected_generation,
              "policy_digest": policy_digest(settings), "candidate_bundle_digest": current_bundle, "scope": revision["scope"],
              "authorization": decision, "created": _now()}
    record["approval_id"] = _digest(record)
    with store.transaction():
        if revision["state"] == "evaluation_passed":
            store.transition(revision_id, "awaiting_approval", "evaluation passed; awaiting human decision")
        store.add_approval(record)
        store.transition(revision_id, "approved", f"approved by {decision['actor']} for {decision['rollout']} rollout", {"approval_id": record["approval_id"]})
    return {"approval_id": record["approval_id"], "revision_id": revision_id, "rollout": decision["rollout"], "expected_generation": expected_generation,
            "note": "Approval binds this exact candidate, evaluation, bundle, policy and incumbent generation; `learning promote` publishes it atomically."}


def promote_candidate(store, experience, revision_id, expected_generation, settings, *, pack):
    """Consume an approval and publish a new compatible generation with compare-and-swap; a stale approval fails visibly."""
    revision = store.revision(revision_id)
    if revision is None:
        raise LearningError("Unknown candidate revision.")
    if revision["state"] != "approved":
        raise LearningError(f"Candidate is {revision['state']}; only an approved candidate can be promoted.")
    compose = _sibling("learning_compose")
    if not compose["revision_digest_matches"](revision):
        raise LearningError("Stored revision does not match its id.")
    approvals = store.approvals(revision_id, unconsumed=True)
    if not approvals:
        raise LearningError("No unconsumed approval exists for this candidate.")
    approval = approvals[-1]
    active = store.active_generation()
    active_id = active["generation_id"] if active else None
    if expected_generation != active_id or approval["expected_generation"] != active_id:
        raise LearningError("Stale approval: the active generation is not the one the approval expected. Re-approve against the current generation.")
    if approval["policy_digest"] != policy_digest(settings):
        raise LearningError("Learning policy changed since approval; re-evaluate and re-approve.")
    current_bundle = bundle_digest(store, pack, (active["revision_ids"] if active else []) + [revision_id], settings)
    if approval["candidate_bundle_digest"] != current_bundle:
        raise LearningError("Composed bundle drifted since approval (base or package changed); re-evaluate and re-approve.")
    if revision["scope"] == "global" and revision["privacy_classification"] != "sanitized_general":
        raise LearningError("A global revision must be classified sanitized_general.")
    support = support_status(store, experience, revision)
    if support["withdrawn"]:
        raise LearningError("Supporting evidence was withdrawn since approval; re-run review and evaluation.")
    if store.namespace_kind != "test" and support["synthetic"]:
        raise LearningError("Candidate rests on synthetic fixture evidence; refused in a production library.")
    current_ids = list(active["revision_ids"]) if active else []
    slot = (revision["editable_slot_ids"] or [None])[0]
    superseded = []
    for other_id in current_ids:
        other = store.revision(other_id)
        if other is None:
            continue
        same = (other["artifact_kind"], other["artifact_id"], (other["editable_slot_ids"] or [None])[0], other["scope"]) == (revision["artifact_kind"], revision["artifact_id"], slot, revision["scope"])
        if same or other_id in revision["conflicts"] or revision_id in other.get("conflicts", []):
            if other_id in revision["parent_revision_ids"]:
                superseded.append(other_id)
            else:
                raise LearningError("An active revision occupies the same slot or is declared conflicting; propose a refine/merge that names it as a parent instead.")
    for dependency in revision["dependencies"]:
        if dependency not in current_ids:
            raise LearningError("A declared dependency is not part of the active generation.")
    canaries = dict(active.get("canaries") or {}) if active else {}
    rollout = approval["authorization"]["rollout"]
    if rollout == "canary":
        canaries[revision_id] = dict(approval["authorization"]["canary"], approval_id=approval["approval_id"])
    remaining = [r for r in current_ids if r not in superseded] + [revision_id]
    record = {"schema_version": SCHEMA, "revision_ids": sorted(remaining), "parent_generation": active_id, "created": _now(),
              "reason": f"promotion of {revision_id[:12]} ({rollout})", "policy_digest": policy_digest(settings),
              "base_package_digest": package_digest(pack), "canaries": {k: v for k, v in canaries.items() if k in remaining}, "restored_from": None,
              "approval_id": approval["approval_id"]}
    record["generation_id"] = _digest(record)
    with store.transaction():
        store.consume_approval(approval["approval_id"], record["generation_id"])
        for other_id in superseded:
            store.transition(other_id, "deprecated", f"superseded by {revision_id[:12]}")
        store.transition(revision_id, "canary" if rollout == "canary" else "active", "published in generation " + record["generation_id"][:12], {"generation_id": record["generation_id"]})
        store.publish_generation(record, active_id)
    return {"generation_id": record["generation_id"], "revision_id": revision_id, "state": "canary" if rollout == "canary" else "active",
            "superseded": superseded, "previous_generation": active_id}


def rollback_generation(store, expected_generation, target_generation, authorization, settings, *, pack):
    """Restore a complete compatible generation (never one with revoked members); with no safe predecessor, the pristine base."""
    _authorization(dict(authorization, rollout="active"))
    active = store.active_generation()
    active_id = active["generation_id"] if active else None
    if expected_generation != active_id:
        raise LearningError("Expected generation is not the active generation.")
    target = None
    if target_generation not in (None, "base"):
        target = store.generation(target_generation)
        if target is None:
            raise LearningError("Unknown target generation.")
    revisions = []
    if target is not None:
        if target["policy_digest"] != policy_digest(settings):
            raise LearningError("Target generation was published under another learning policy; rolling back to it is refused (use `base`).")
        for ident in target["revision_ids"]:
            revision = store.revision(ident)
            if revision is None or revision["state"] in ("revoked", "quarantined", "pruned", "invalid"):
                raise LearningError("Target generation contains a revoked, quarantined or removed revision; choose an earlier generation or `base`.")
            current = base_body(pack, revision["artifact_kind"], revision["artifact_id"])["sha256"]
            if current != revision["base_artifact_digest"]:
                raise LearningError("Target generation is incompatible with the current package (base artifact changed); choose `base` and re-evaluate.")
            revisions.append(ident)
    record = {"schema_version": SCHEMA, "revision_ids": sorted(revisions), "parent_generation": active_id, "created": _now(),
              "reason": "rollback", "policy_digest": policy_digest(settings), "base_package_digest": package_digest(pack),
              "canaries": {k: v for k, v in ((target or {}).get("canaries") or {}).items() if k in revisions},
              "restored_from": target["generation_id"] if target else "base"}
    record["generation_id"] = _digest(record)
    with store.transaction():
        for ident in (active["revision_ids"] if active else []):
            if ident not in revisions:
                state = store.revision(ident)["state"]
                if state in LIVE:
                    store.transition(ident, "rolled_back", "removed by rollback to " + record["restored_from"][:12])
        for ident in revisions:
            state = store.revision(ident)["state"]
            if state in ("rolled_back", "deprecated"):
                store.transition(ident, "active", "restored by rollback")
        store.publish_generation(record, active_id)
    return {"generation_id": record["generation_id"], "restored_from": record["restored_from"], "revision_ids": record["revision_ids"], "previous_generation": active_id}


def descendants(store, revision_id):
    """Provenance DAG walk (parents, logical parents, dependencies, inherits) with cycle protection."""
    out, pending, seen = [], [revision_id], set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        for revision in store.revisions():
            inherited = set(revision.get("parent_revision_ids", [])) | set(revision.get("dependencies", [])) | set((revision.get("source_provenance") or {}).get("inherits", []))
            if current in inherited and revision["revision_id"] not in seen:
                out.append(revision["revision_id"])
                pending.append(revision["revision_id"])
    return out


def revoke(store, revision_id, reason, settings, *, quarantine_only=False):
    """Unsafe or unsupported: block new consumption now, take descendants with it, republish without them."""
    revision = store.revision(revision_id)
    if revision is None:
        raise LearningError("Unknown revision.")
    affected = [revision_id] + descendants(store, revision_id)
    state = "quarantined" if quarantine_only else "revoked"
    removed = []
    with store.transaction():
        for ident in affected:
            current = store.revision(ident)["state"]
            if current in TERMINAL or (state == "quarantined" and current == "quarantined"):
                continue
            if state not in TRANSITIONS.get(current, set()):
                if current in ("rejected", "invalid", "pruned"):
                    continue
                store.transition(ident, "quarantined" if "quarantined" in TRANSITIONS.get(current, set()) else state, reason)
                if state == "revoked" and "revoked" in TRANSITIONS.get(store.revision(ident)["state"], set()):
                    store.transition(ident, "revoked", reason)
            else:
                store.transition(ident, state, reason)
            removed.append(ident)
    generation = _republish_without(store, affected, settings, f"{state}: " + (reason or ""))
    return {"revision_id": revision_id, "state": state, "affected": removed, "generation_id": generation["generation_id"] if generation else None,
            "note": "Emitted instructions cannot be removed from a model's context; new consumption is blocked and the host must reassess affected work."}


def deprecate(store, revision_id, reason, settings):
    revision = store.revision(revision_id)
    if revision is None:
        raise LearningError("Unknown revision.")
    if revision["state"] not in LIVE:
        raise LearningError(f"Revision is {revision['state']}; only a live revision is deprecated (history stays).")
    with store.transaction():
        store.transition(revision_id, "deprecated", reason)
    generation = _republish_without(store, [revision_id], settings, "deprecation: " + (reason or ""))
    return {"revision_id": revision_id, "state": "deprecated", "generation_id": generation["generation_id"] if generation else None}


def prune(store, settings, *, apply=False, max_age_days=None, now=None):
    """Retention-eligible inactive content: listed by default, removed only with --apply, leaving non-content tombstones."""
    now = now if now is not None else _now()
    age = max_age_days if max_age_days is not None else settings["retention"]["max_age_days"]
    candidates = []
    active_ids = set((store.active_generation() or {}).get("revision_ids", []))
    for revision in store.revisions():
        if revision["state"] not in RETENTION_ELIGIBLE or revision["revision_id"] in active_ids:
            continue
        history = store.history(revision["revision_id"])
        last = history[-1]["created"] if history else revision["created"]
        if age is not None and now - last < age * 86400:
            continue
        uses = sum(1 for o in store.observations() if any(x["revision_id"] == revision["revision_id"] for x in o["exposure"]))
        candidates.append({"revision_id": revision["revision_id"], "state": revision["state"], "kind": revision["artifact_kind"], "artifact_id": revision["artifact_id"],
                           "age_days": (now - last) // 86400, "observed_uses": uses,
                           "rank": (revision["state"] in ("rejected", "invalid"), -uses, -(now - last))})
    candidates.sort(key=lambda c: c["rank"], reverse=True)
    for item in candidates:
        del item["rank"]
    removed = []
    if apply:
        with store.transaction():
            for item in candidates:
                if item["state"] not in TERMINAL and "pruned" in TRANSITIONS.get(item["state"], set()):
                    store.transition(item["revision_id"], "pruned", "retention")
                store.delete_revision(item["revision_id"], f"pruned after {item['age_days']} days in state {item['state']}")
                removed.append(item["revision_id"])
    return {"dry_run": not apply, "candidates": candidates, "removed": removed,
            "note": "Low use alone does not select a revision; only retention-eligible inactive states past the age are listed. Logical deletion only."}


def forget(store, experience, settings, *, event_id=None, revision_id=None):
    """Forget user data and derived private content; keep only minimal non-content lineage."""
    if event_id is None and revision_id is None:
        raise LearningError("Say what to forget: --event or --revision.")
    result = {"observations_removed": 0, "revisions_removed": [], "suspended": []}
    with store.transaction():
        if event_id is not None:
            result["observations_removed"] = store.forget_observation(event_id, "forgotten by the user")
        if revision_id is not None:
            revision = store.revision(revision_id)
            if revision is None:
                raise LearningError("Unknown revision.")
            affected = [revision_id] + descendants(store, revision_id)
            for ident in affected:
                current = store.revision(ident)
                if current is None:
                    continue
                if current["state"] in LIVE:
                    result["suspended"].append(ident)
                store.delete_revision(ident, "forgotten by the user (descendant)" if ident != revision_id else "forgotten by the user")
                result["revisions_removed"].append(ident)
    if result["suspended"]:
        _republish_without(store, result["suspended"], settings, "forgotten content removed from the active generation")
    synced = sync_support(store, experience, settings, reason="support forgotten")
    result["stale_support"] = synced["changed"]
    result["suspended"] += synced["suspended"]
    result["note"] = "Logical deletion in the local SQLite file; backups, provider copies and SQLite free pages are outside this operation."
    return result


# ---------------------------------------------------------------- profiles, generalization, export


def enroll(profile_store, repo_store_obj, namespace, *, consent_aggregate, project_label=None):
    record = {"schema_version": SCHEMA, "namespace": namespace, "consent_aggregate_evidence": bool(consent_aggregate),
              "label": (project_label or "")[:80], "created": _now()}
    with profile_store.transaction():
        profile_store.enroll(namespace, record)
    with repo_store_obj.transaction():
        repo_store_obj.set_meta("profile_namespace", namespace)
    return record


def unenroll(profile_store, namespace, settings):
    """Stop new use of this repository's evidence immediately; global revisions that rested on it lose support."""
    with profile_store.transaction():
        removed = profile_store.unenroll(namespace)
    affected = []
    for revision in profile_store.revisions():
        sources = (revision.get("source_provenance") or {}).get("namespaces") or []
        if namespace in sources and revision["state"] not in TERMINAL and revision["state"] not in ("rejected", "invalid", "stale_support"):
            with profile_store.transaction():
                if revision["state"] in LIVE:
                    affected.append(revision["revision_id"])
                if "stale_support" in TRANSITIONS.get(revision["state"], set()):
                    profile_store.transition(revision["revision_id"], "stale_support", "an enrolled repository withdrew its evidence")
    if affected:
        _republish_without(profile_store, affected, settings, "unenrollment withdrew supporting evidence")
    return {"removed": removed, "suspended": affected}


def generalize(profile_store, sources, settings, *, kind, artifact_id, slot, text=None, minimum_families=None):
    """Sanitized general-procedure candidate document from independent enrolled repository families.

    `sources`: [{"namespace", "revision", "lexicon", "families"}] gathered by the caller from enrolled repository stores
    that consented to aggregate use. Repository text is never copied: the general wording is supplied by the caller
    (host or human) or, when every source already carries an identical sanitized_general text, reused.
    """
    compose = _sibling("learning_compose")
    minimum = minimum_families if minimum_families is not None else settings["evaluation"]["global_min_families"]
    enrolled = {e["namespace"] for e in profile_store.enrollments() if e["consent_aggregate_evidence"]}
    usable = [s for s in sources if s["namespace"] in enrolled and s["revision"]["artifact_kind"] == kind and s["revision"]["artifact_id"] == artifact_id
              and (s["revision"]["editable_slot_ids"] or [None])[0] == slot and s["revision"].get("privacy_classification") != "never_global"]
    if len({s["namespace"] for s in usable}) < minimum:
        return {"no_change": True, "reason": f"insufficient independent repository families: {len({s['namespace'] for s in usable})} < {minimum}", "families": len(usable)}
    shares = {}
    for source in usable:
        shares[source["namespace"]] = shares.get(source["namespace"], 0) + max(1, source.get("families", 1))
    total = sum(shares.values())
    if total and max(shares.values()) / total > 0.6 and len(shares) > 1:
        return {"no_change": True, "reason": "one repository dominates the aggregate evidence; a general rule would mostly restate it", "shares": shares}
    wording = text
    if wording is None:
        texts = {s["revision"]["typed_payload"].get("text") for s in usable}
        if len(texts) == 1 and next(iter(texts)):
            wording = next(iter(texts))
    if kind == "recipe_overlay":
        payload = usable[0]["revision"]["typed_payload"]
    elif wording is None:
        return {"no_change": True, "reason": "sources disagree on wording; supply a sanitized general text (host or human authored)", "families": len(usable)}
    else:
        payload = {"slot": slot, "text": wording}
    lexicon = set()
    for source in usable:
        lexicon |= set(source.get("lexicon") or ())
    applicability = {"roles": sorted({r for s in usable for r in s["revision"]["applicability"]["roles"]}),
                     "recipes": sorted({r for s in usable for r in s["revision"]["applicability"]["recipes"]}),
                     "task_terms": sorted(set.intersection(*[set(s["revision"]["applicability"]["task_terms"]) for s in usable])) if usable else [],
                     "min_term_matches": 1}
    if not (applicability["roles"] or applicability["recipes"] or applicability["task_terms"]):
        return {"no_change": True, "reason": "no shared applicability across the source repositories", "families": len(usable)}
    document = {"schema_version": SCHEMA, "kind": kind, "operation": "generalize", "scope": "global", "target": {"artifact_id": artifact_id, "slot": slot},
                "payload": payload, "applicability": applicability, "hypothesis": "A procedure that helped in several independent repositories generalizes at capability level.",
                "created_by_kind": "human" if text is not None else "deterministic_review", "privacy_classification": "sanitized_general",
                "logical_parent_ids": sorted({s["revision"]["artifact_id"] for s in usable}),
                "expected_effect": {"metric": "task_success", "direction": "increase", "practical_threshold": 0.05},
                "risks": ["negative transfer: a repository-specific habit may not hold elsewhere; the held-out transfer evaluation decides"],
                "rejection_conditions": ["no improvement on a held-out repository family, or any degradation of the worst family"]}
    try:
        for probe in ([payload.get("text")] if payload.get("text") else [step["text"] for step in payload.get("insert", [])]):
            reasons = compose["lint_text"](probe, scope="global", private_lexicon=lexicon)
            if reasons:
                return {"no_change": True, "reason": "sanitization refused: " + reasons[0], "families": len(usable)}
    except Exception:  # noqa: BLE001 - lint is defensive; refusing is the safe default.
        return {"no_change": True, "reason": "sanitization could not be established", "families": len(usable)}
    provenance = {"namespaces": sorted({s["namespace"] for s in usable}), "source_revisions": sorted(s["revision"]["revision_id"] for s in usable),
                  "evaluation_summaries": [s.get("evaluation_summary") for s in usable if s.get("evaluation_summary")]}
    return {"no_change": False, "document": document, "provenance": provenance, "families": len(usable), "shares": shares}


def export_patch(store, pack, revision_ids):
    """A sanitized review patch of effective artifacts against canonical bundled sources; never touches installed files."""
    import difflib
    compose = _sibling("learning_compose")
    catalog = package_catalog(pack)
    out = []
    for ident in revision_ids:
        revision = store.revision(ident)
        if revision is None:
            raise LearningError("Unknown revision.")
        if revision["scope"] == "global" and revision["privacy_classification"] != "sanitized_general":
            raise LearningError("Only sanitized_general revisions are exportable.")
        kind, artifact_id = revision["artifact_kind"], revision["artifact_id"]
        if kind in ("retrieval_profile", "verification_hint", "skill_selection"):
            out.append(f"# {kind} {artifact_id} ({ident[:12]}): typed payload, no text body\n" + json.dumps(revision["typed_payload"], indent=2, sort_keys=True) + "\n")
            continue
        base = base_body(pack, kind, artifact_id)
        workflow = compose["workflow_view"](catalog["workflows"][artifact_id]) if kind == "recipe_overlay" and artifact_id in catalog["workflows"] else None
        composed = compose["compose"](kind, base["content"], [_layer(revision)], workflow)
        label = {"skill_overlay": "skill", "role_method_overlay": "role", "recipe_overlay": "recipe"}[kind]
        diff = difflib.unified_diff(base["content"].split("\n"), composed["content"].split("\n"), fromfile=f"a/{label}/{artifact_id}.md",
                                    tofile=f"b/{label}/{artifact_id}.md", lineterm="")
        out.append("\n".join(diff) + "\n")
    header = ("# Exported learned overlays: a review patch against canonical sources.\n# Approval does not travel with this file; import it elsewhere as an untrusted candidate.\n")
    return header + "\n".join(out)


def export_generation(store, settings):
    """A frozen library for experiments: the active generation's revisions as untrusted candidate material with provenance."""
    active = store.active_generation()
    revisions = [store.revision(i) for i in (active or {}).get("revision_ids", [])]
    return {"schema_version": SCHEMA, "exported": _now(), "generation_id": (active or {}).get("generation_id"), "policy_digest": policy_digest(settings),
            "revisions": [{k: v for k, v in r.items() if k not in ("state", "state_reason")} for r in revisions if r],
            "note": "Frozen for evaluation. Importing installs nothing; `learning import-generation` records an experimental canary bound to an explicit authorization."}


def document_from_record(record):
    """The candidate document a frozen revision came from, without the source namespace's event, parent or dependency ids."""
    document = {"schema_version": SCHEMA, "kind": record["artifact_kind"], "operation": record["operation"], "scope": record["scope"],
                "target": {"artifact_id": record["artifact_id"], "slot": (record.get("editable_slot_ids") or [None])[0]}, "payload": record["typed_payload"],
                "applicability": record["applicability"], "negative_applicability": record.get("negative_applicability"), "hypothesis": record["hypothesis"],
                "expected_effect": record.get("expected_effect"), "risks": record.get("risks") or [], "counterexamples": record.get("counterexamples") or [],
                "rejection_conditions": record.get("rejection_conditions") or [], "task_families": record.get("task_families") or [],
                "logical_parent_ids": record.get("logical_parent_ids") or [], "privacy_classification": record["privacy_classification"],
                "created_by_kind": record["created_by_kind"], "provider_metadata": record.get("optional_provider_metadata")}
    if document["target"]["slot"] is None:
        del document["target"]["slot"]
    if document["operation"] in ("merge", "split", "deprecate"):
        document["operation"] = "refine"  # Parent ids do not cross namespaces; the imported material is a refinement of the base.
    return {k: v for k, v in document.items() if v is not None}


def import_generation(store, experience, document, settings, authorization, *, pack, experiment):
    """Install a frozen library into an isolated arm as an explicitly authorized experimental canary (never a stable promotion).

    Each frozen revision is re-validated (Tier A) and re-derived as a new content-addressed revision bound to this
    package and this policy; provenance records where it came from. Approval does not travel with the file.
    """
    compose = _sibling("learning_compose")
    decision = _authorization(dict(authorization, rollout="canary"))
    if not isinstance(experiment, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,120}", experiment):
        raise LearningError("An experiment id is required.")
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA or not isinstance(document.get("revisions"), list):
        raise LearningError("Frozen library document is malformed.")
    if len(document["revisions"]) > 50:
        raise LearningError("Frozen library lists too many revisions.")
    catalog = package_catalog(pack)
    installed = []
    for record in document["revisions"]:
        if not isinstance(record, dict) or not compose["revision_digest_matches"](record):
            raise LearningError("A frozen revision does not match its id; the library is refused.")
        current = base_body(pack, record["artifact_kind"], record["artifact_id"])
        if current["sha256"] != record["base_artifact_digest"]:
            raise LearningError("A frozen revision binds to another base artifact than this package ships; the library is incompatible.")
        try:
            candidate = compose["validate_candidate"](document_from_record(record), catalog, policy=settings)
        except compose["LearningValidationError"] as exc:
            raise LearningError("A frozen revision fails the current validation controls; the library is refused: " + str(exc)) from None
        stored = compose["revision_record"](candidate, base_package_digest=package_digest(pack), base_artifact_digest=current["sha256"],
                                            policy_digest=policy_digest(settings), namespace=store.directory.name, evidence_cutoff=record.get("evidence_cutoff"),
                                            created=_now(), source_provenance={"created_by_kind": record["created_by_kind"], "imported_from_revision": record["revision_id"],
                                                                               "frozen_generation": document.get("generation_id"), "experiment": experiment,
                                                                               "inherits": [record["revision_id"]]})
        with store.transaction():
            if store.add_revision(stored):
                store.transition(stored["revision_id"], "proposed", "imported frozen library", {"experiment": experiment, "imported_from": record["revision_id"]})
                store.transition(stored["revision_id"], "validated", "imported revision re-validated (Tier A)")
                store.transition(stored["revision_id"], "awaiting_experiment_authorization", "experiment " + experiment)
                store.transition(stored["revision_id"], "experimental_canary", f"authorized by {decision['actor']} for experiment {experiment}",
                                 {"authorization": decision, "experiment": experiment, "max_tasks": settings["canary"]["max_tasks"], "expires": _now() + settings["canary"]["max_days"] * 86400})
            elif store.revision(stored["revision_id"])["state"] not in ("experimental_canary",):
                raise LearningError("A frozen revision already exists in this store in another state; use a fresh arm namespace.")
        installed.append(stored["revision_id"])
    with store.transaction():
        store.set_meta("experiment", {"id": experiment, "imported": _now(), "frozen_generation": document.get("generation_id")})
        if not store.meta("pack"):
            store.set_meta("pack", str(Path(pack).resolve()))
    return {"installed": installed, "experiment": experiment, "state": "experimental_canary",
            "note": "Experimental canary: a real, bounded, authorized behavior change for evaluation; never reported as a stable measured win."}


def start_experimental_canary(store, revision_id, authorization, settings, *, experiment, max_tasks=None, max_days=None):
    """validated + component checks passed -> awaiting_experiment_authorization -> experimental_canary, bounded and explicit."""
    revision = store.revision(revision_id)
    if revision is None:
        raise LearningError("Unknown revision.")
    if revision["state"] != "validated":
        raise LearningError(f"Revision is {revision['state']}; only a validated candidate can enter an experimental canary.")
    checks = [e for e in store.evaluations(revision_id) if e.get("tier") == "B" and e["status"] == "passed"]
    if not checks:
        raise LearningError("Component checks (Tier B) have not passed for this candidate; run `learning component-check` first.")
    decision = _authorization(dict(authorization, rollout="canary"))
    if not isinstance(experiment, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,120}", experiment):
        raise LearningError("An experiment id is required.")
    tasks = max_tasks if max_tasks is not None else settings["canary"]["max_tasks"]
    days = max_days if max_days is not None else settings["canary"]["max_days"]
    if type(tasks) is not int or not 1 <= tasks <= settings["canary"]["max_tasks"] or type(days) is not int or not 1 <= days <= settings["canary"]["max_days"]:
        raise LearningError("Canary bounds exceed the configured ceilings.")
    record = {"authorization": decision, "experiment": experiment, "max_tasks": tasks, "expires": _now() + days * 86400, "component_check": checks[-1]["evaluation_id"]}
    with store.transaction():
        store.transition(revision_id, "awaiting_experiment_authorization", "experiment requested: " + experiment)
        store.transition(revision_id, "experimental_canary", f"authorized by {decision['actor']} for experiment {experiment}", record)
    return {"revision_id": revision_id, "state": "experimental_canary", **{k: v for k, v in record.items() if k != "authorization"}}


# ---------------------------------------------------------------- runtime view (read-only)


def canary_uses(store, revision_id):
    return sum(1 for o in store.observations() if any(x["revision_id"] == revision_id and x["state"] in ("emitted", "host_confirmed_read", "reported_applied") for x in o["exposure"]))


def eligible_revisions(store, settings, *, now=None):
    """Live revisions of the active generation plus unexpired experimental canaries; expiry and use counts are read, never written."""
    now = now if now is not None else _now()
    active = store.active_generation()
    rows = []
    canaries = (active or {}).get("canaries") or {}
    for ident in (active or {}).get("revision_ids", []):
        revision = store.revision(ident)
        if revision is None or revision["state"] not in LIVE:
            continue
        if revision["state"] == "canary":
            bound = canaries.get(ident) or {}
            if now >= bound.get("expires", 0) or canary_uses(store, ident) >= bound.get("max_tasks", 0):
                rows.append(dict(revision, runtime_state="not_approved", runtime_reason="canary exhausted or expired; awaiting stable approval"))
                continue
        rows.append(dict(revision, runtime_state="live"))
    for revision in store.revisions(states=("experimental_canary",)):
        _, _, record = store.state_of(revision["revision_id"])
        record = record or {}
        if now >= record.get("expires", 0) or canary_uses(store, revision["revision_id"]) >= record.get("max_tasks", 0):
            rows.append(dict(revision, runtime_state="not_approved", runtime_reason="experimental canary exhausted or expired"))
            continue
        rows.append(dict(revision, runtime_state="live", experiment=record.get("experiment")))
    return active, rows


def resolve(project, pack, task, *, role=None, recipes=(), settings=None, identity=None, caller_strategy_explicit=False, scrub=None, now=None):
    """The foreground view: eligible overlays for one request, composed materials, explain states, an exposure descriptor.

    Read-only: opens stores read-only, writes no counters, migrates nothing, creates no directory. Disabled -> None,
    so a packet without learning is byte-for-byte what it was.
    """
    settings = settings or load_settings(project=project)
    if not settings["enabled"]:
        return None
    compose = _sibling("learning_compose")
    engine = _sibling("retrieval")
    report = {"status": "shadow" if settings["mode"] == "shadow" else "active", "mode": settings["mode"], "generation": None, "overlays": [],
              "diagnostics": [], "exposure": None, "reuse_key": None, "budget": settings["budget"]}
    stores = []
    for scope, directory in (("repo", repo_directory(project, identity)), ("global", profile_directory(settings["profile"]) if settings["profile"] else None)):
        if directory is None or not store_exists(directory):
            continue
        try:
            stores.append((scope, open_store(directory, readonly=True)))
        except LearningError as exc:
            report["diagnostics"].append(f"{scope} learning store declined: {exc}")
    if not stores:
        report["status"] = "shadow" if settings["mode"] == "shadow" else "not_applicable"
        report["reason"] = "no learning store for this repository or profile; baseline guidance"
        return report
    query = engine["analyze_query"](task[:16000])
    terms = set(query["terms"])
    try:
        catalog = package_catalog(pack)
        pack_digest = package_digest(pack)
    except (LearningError, OSError, ValueError, KeyError):
        report["diagnostics"].append("package catalog unavailable; learned guidance declined")
        for _, store in stores:
            store.close()
        return dict(report, status="capability_unavailable")
    rows, generation_ids = [], []
    try:
        for scope, store in stores:
            active, revisions = eligible_revisions(store, settings, now=now)
            generation_ids.append({"scope": scope, "generation_id": (active or {}).get("generation_id"), "namespace_kind": store.namespace_kind})
            experience = experience_store(store.directory) if scope == "repo" else None
            try:
                for revision in revisions:
                    row = {"revision_id": revision["revision_id"], "artifact_id": revision["artifact_id"], "kind": revision["artifact_kind"], "scope": scope,
                           "slot": (revision["editable_slot_ids"] or [None])[0], "state": "active", "reason": "", "matched_terms": []}
                    if revision.get("runtime_state") != "live":
                        row.update(state="not_approved", reason=revision.get("runtime_reason", "not live"))
                    elif revision["artifact_kind"] not in settings["kinds"]:
                        row.update(state="capability_unavailable", reason="artifact kind disabled by configuration")
                    elif revision["policy_digest"] != policy_digest(settings):
                        row.update(state="stale_base", reason="validated under another learning policy")
                    elif revision["base_package_digest"] != pack_digest:
                        row.update(state="stale_base", reason="installed package changed since evaluation")
                    else:
                        ok, why, matched = compose["applicable"](revision, role=role, recipes=recipes, terms=terms)
                        row["matched_terms"] = matched
                        if not ok:
                            row.update(state="not_applicable", reason=why)
                        elif experience is not None and any(experience.get_event(i) is None or experience.get_event(i).get("status", "current") != "current" for i in revision["supporting_event_ids"]):
                            row.update(state="insufficient_evidence", reason="supporting evidence was corrected or forgotten; awaiting re-review")
                    row["_revision"] = revision
                    rows.append(row)
            finally:
                if experience is not None:
                    experience.close()
    finally:
        for _, store in stores:
            store.close()
    # Dependencies, base freshness, same-slot conflicts and the parent binding between layers.
    live = {row["revision_id"]: row for row in rows if row["state"] == "active"}
    for row in list(live.values()):
        revision = row["_revision"]
        for dependency in revision["dependencies"]:
            if dependency not in live:
                row.update(state="insufficient_evidence", reason="a declared dependency is not live")
        if row["state"] != "active":
            continue
        try:
            base = base_body(pack, row["kind"], row["artifact_id"])
        except LearningError as exc:
            row.update(state="capability_unavailable", reason=str(exc))
            continue
        if base["sha256"] != revision["base_artifact_digest"]:
            row.update(state="stale_base", reason="bundled base artifact changed since this overlay was evaluated")
        row["_base"] = base
    live = {row["revision_id"]: row for row in rows if row["state"] == "active"}
    groups = {}
    for row in live.values():
        groups.setdefault((row["kind"], row["artifact_id"], row["slot"]), []).append(row)
    for key, members in groups.items():
        for scope in ("repo", "global"):
            same = [m for m in members if m["scope"] == scope]
            if len(same) > 1:
                for m in same:
                    m.update(state="conflict", reason="two admitted overlays of one scope target the same slot; base used")
        repo_rows = [m for m in members if m["scope"] == "repo" and m["state"] == "active"]
        global_rows = [m for m in members if m["scope"] == "global" and m["state"] == "active"]
        for m in repo_rows:
            parents = set(m["_revision"]["parent_revision_ids"])
            expected = {g["revision_id"] for g in global_rows}
            declared_global = parents & {r["revision_id"] for r in rows if r["scope"] == "global"}
            if declared_global and declared_global != expected:
                m.update(state="stale_base", reason="the global overlay this specialization was evaluated against is no longer the active one")
    live = [row for row in rows if row["state"] == "active"]
    live.sort(key=lambda r: (r["scope"] != "repo", -len(r["_revision"]["task_families"]), r["revision_id"]))
    textual = [r for r in live if r["kind"] in ("skill_overlay", "role_method_overlay", "recipe_overlay")]
    for extra in textual[settings["budget"]["max_overlays"]:]:
        extra.update(state="budget_omitted", reason="overlay limit reached; lower-priority overlay omitted")
    live = [row for row in rows if row["state"] == "active"]
    materials = {}
    for row in live:
        if row["kind"] in ("skill_overlay", "role_method_overlay", "recipe_overlay"):
            item = materials.setdefault((row["kind"], row["artifact_id"]), {"kind": row["kind"], "artifact_id": row["artifact_id"], "layers": [], "base": row["_base"], "workflow": None})
            item["layers"].append(dict(_layer(row["_revision"]), revision_id=row["revision_id"]))
            if row["kind"] == "recipe_overlay" and row["artifact_id"] in catalog["workflows"]:
                item["workflow"] = compose["workflow_view"](catalog["workflows"][row["artifact_id"]])
    for item in materials.values():
        item["layers"].sort(key=lambda layer: (layer["scope"] != "global", layer["revision_id"]))
    profiles = [r["_revision"] for r in live if r["kind"] == "retrieval_profile"]
    retrieval, profile_state = compose["effective_profile"](profiles, None, caller_strategy_explicit=caller_strategy_explicit)
    if profile_state and profile_state["state"] != "active":
        for r in live:
            if r["kind"] == "retrieval_profile":
                r.update(state=profile_state["state"], reason=profile_state["reason"])
        retrieval = None
    hints = [dict(r["_revision"]["typed_payload"], revision_id=r["revision_id"]) for r in live if r["kind"] == "verification_hint"]
    selections = [dict(r["_revision"]["typed_payload"], revision_id=r["revision_id"], scope=r["scope"]) for r in live if r["kind"] == "skill_selection"]
    shadow = settings["mode"] == "shadow"
    if shadow:
        for row in rows:
            if row["state"] == "active":
                row.update(state="shadow", reason="eligible; shadow mode emits nothing")
    emitted = [row["revision_id"] for row in rows if row["state"] == "active"]
    report["overlays"] = [{k: v for k, v in row.items() if not k.startswith("_")} for row in rows]
    report["generation"] = generation_ids
    report["exposure"] = {"generations": generation_ids, "revisions": [{"revision_id": row["revision_id"], "state": "emitted" if row["state"] == "active" else "eligible" if row["state"] == "shadow" else "not_emitted"}
                                                                       for row in rows if row["state"] in ("active", "shadow")],
                          "package_digest": pack_digest, "policy_digest": policy_digest(settings)}
    report["exposure"]["digest"] = _digest(report["exposure"])
    report["reuse_key"] = _digest({"generations": generation_ids, "emitted": sorted(emitted), "policy": policy_digest(settings), "package": pack_digest,
                                  "role": role, "matched": sorted({t for row in rows for t in row["matched_terms"]})})
    report["status"] = "shadow" if shadow else ("active" if emitted else "not_applicable")
    if not shadow and not emitted and rows:
        report["reason"] = "no admitted overlay applies to this request; baseline guidance"
    return dict(report, _materials=materials if not shadow else {}, _retrieval=retrieval if not shadow else None, _hints=hints if not shadow else [],
                _selections=selections if not shadow else [])


# ---------------------------------------------------------------- command line


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, "learning: invalid arguments; use --help. Input values withheld.\n")


def _project(value):
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise LearningError("Project must be an existing readable directory.")
    return root


def _pack(value):
    context = _sibling("context")
    return context["find_pack"](value)


def _read_document(value, limit=MAX_OBSERVATION_BYTES):
    raw = sys.stdin.buffer.read(limit + 1) if value == "-" else Path(value).read_bytes()[:limit + 1]
    if len(raw) > limit:
        raise LearningError("Document exceeds its size limit.")
    return _sibling("learning_compose")["parse_document"](raw)


def _scope_store(args, settings, root, *, create=False, readonly=True):
    scope = getattr(args, "scope", None) or "repo"
    if scope == "global":
        profile = getattr(args, "profile", None) or settings["profile"]
        if not profile:
            raise LearningError("Global scope needs --profile or a configured profile; it never falls back to the current repository.")
        directory = profile_directory(profile)
    else:
        directory = repo_directory(root, getattr(args, "identity", None) or os.environ.get("AGENT_DISPATCHER_INDEX_ID") or None)
    return scope, open_store(directory, create=create, readonly=readonly), directory


def _summary(revision):
    return {key: revision.get(key) for key in ("revision_id", "artifact_kind", "artifact_id", "editable_slot_ids", "scope", "operation", "state", "state_reason",
                                              "created_by_kind", "privacy_classification", "created", "task_families")} | {"support": len(revision.get("supporting_event_ids") or [])}


def command_status(args, settings, root):
    report = {"read_only": True, "enabled": settings["enabled"], "mode": settings["mode"], "kinds": settings["kinds"], "profile": settings["profile"],
              "observation_recording": settings["observation"]["record"], "stores": {}}
    for scope, directory in (("repo", repo_directory(root, args.identity or os.environ.get("AGENT_DISPATCHER_INDEX_ID") or None)),
                             ("global", profile_directory(settings["profile"]) if settings["profile"] else None)):
        if directory is None:
            report["stores"][scope] = {"status": "no_profile"}
            continue
        if not store_exists(directory):
            report["stores"][scope] = {"status": "absent", "state_directory": str(directory)}
            continue
        try:
            with open_store(directory, readonly=True) as store:
                active = store.active_generation()
                item = {"status": "present", "namespace_kind": store.namespace_kind, "counts": store.counts(), "integrity": store.integrity(),
                        "active_generation": (active or {}).get("generation_id"), "active_revisions": len((active or {}).get("revision_ids", [])),
                        "review": review_due(store, settings), "state_directory": str(directory)}
                if scope == "repo":
                    item["enrolled_profile_namespace"] = store.meta("profile_namespace")
                report["stores"][scope] = item
        except LearningError as exc:
            report["stores"][scope] = {"status": "unavailable", "detail": str(exc)}
    if not settings["enabled"]:
        report["note"] = "Procedural learning is off (default): no observation, review, store or packet effect. Enable shadow mode in the settings file to start."
    return report


def command_explain(args, settings, root, pack):
    task = args.task
    if args.task_file:
        task = sys.stdin.read(16001) if args.task_file == "-" else Path(args.task_file).read_text(encoding="utf-8")[:16001]
    if not isinstance(task, str) or not task.strip() or len(task) > 16000:
        raise LearningError("Task must contain 1-16000 characters; contents withheld.")
    context = _sibling("context")
    scrub = context["_scrubber"](pack)
    outcome = resolve(root, pack, scrub(task), role=args.role, settings=settings, identity=args.identity or os.environ.get("AGENT_DISPATCHER_INDEX_ID") or None, scrub=scrub)
    if outcome is None:
        return {"status": "disabled", "overlays": [], "note": "procedural learning is off; the packet is the baseline packet"}
    return {k: v for k, v in outcome.items() if not k.startswith("_")}


def main(argv=None):
    parser = SafeParser(prog="learning", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=SafeParser)

    def common(command, *, scope=True):
        command.add_argument("--project", default=".")
        command.add_argument("--pack")
        command.add_argument("--identity", help="Explicit repository identity (harness use)")
        command.add_argument("--config", help="Learning settings file outside the project (default: ~/.config/agent-dispatcher/procedural-learning.json)")
        command.add_argument("--json", action="store_true")
        if scope:
            command.add_argument("--scope", choices=("repo", "global"), default="repo")
            command.add_argument("--profile", help="Learning profile name for --scope global")
        return command

    common(sub.add_parser("status"), scope=False)
    explain = common(sub.add_parser("explain"), scope=False)
    group = explain.add_mutually_exclusive_group(required=True)
    group.add_argument("--task")
    group.add_argument("--task-file")
    explain.add_argument("--role")
    listing = common(sub.add_parser("list"))
    listing.add_argument("--kind")
    listing.add_argument("--state")
    common(sub.add_parser("show")).add_argument("id")
    common(sub.add_parser("diff")).add_argument("id")
    effective = common(sub.add_parser("effective"))
    effective.add_argument("artifact")
    effective.add_argument("--kind", required=True, choices=("skill_overlay", "role_method_overlay", "recipe_overlay"))
    common(sub.add_parser("evaluations")).add_argument("revision", nargs="?")
    common(sub.add_parser("history")).add_argument("revision")
    review = common(sub.add_parser("review"))
    review.add_argument("--dry-run", action="store_true", help="Compute the review without storing it (default)")
    review.add_argument("--apply", action="store_true", help="Store the review and any deterministic candidate documents")
    review.add_argument("--packet", action="store_true", help="Emit the sanitized host-assisted review packet")
    observe_cmd = common(sub.add_parser("observe"), scope=False)
    observe_cmd.add_argument("--event", required=True, help="The experience event id this observation belongs to")
    observe_cmd.add_argument("--observation-file", required=True, help="JSON observation, or - for standard input")
    propose = common(sub.add_parser("propose"))
    propose.add_argument("--from-file", help="Candidate document (JSON), or - for standard input")
    propose.add_argument("--provider", action="store_true", help="Ask the explicitly enabled proposal provider (one budgeted call)")
    propose.add_argument("--review", help="Review id the candidate answers")
    evaluate = common(sub.add_parser("evaluate"))
    evaluate.add_argument("revision")
    evaluate.add_argument("--spec", required=True, help="Evaluation specification JSON (frozen on use)")
    evaluate.add_argument("--runner", default=None, help="Registered runner id (default: the spec's runner)")
    evaluate.add_argument("--batch", help="For end_to_end_batch: the completed batch directory")
    evaluate.add_argument("--fixture-results", help="For fake_test_runner: JSON paired outcomes (test only)")
    common(sub.add_parser("component-check")).add_argument("revision")
    approve = common(sub.add_parser("approve"))
    approve.add_argument("revision")
    approve.add_argument("--evaluation", required=True)
    approve.add_argument("--expected-generation", default=None)
    approve.add_argument("--authorize-as", required=True, help="Label of the deciding person")
    approve.add_argument("--statement", default="")
    approve.add_argument("--rollout", choices=("active", "canary"), default="active")
    approve.add_argument("--canary-tasks", type=int)
    approve.add_argument("--canary-days", type=int)
    promote = common(sub.add_parser("promote"))
    promote.add_argument("revision")
    promote.add_argument("--expected-generation", default=None)
    canary = common(sub.add_parser("canary"))
    canary.add_argument("revision")
    canary.add_argument("--authorize-as", required=True)
    canary.add_argument("--experiment", required=True)
    canary.add_argument("--tasks", type=int)
    canary.add_argument("--days", type=int)
    rollback = common(sub.add_parser("rollback"))
    rollback.add_argument("--target-generation", required=True, help="A generation id, or `base`")
    rollback.add_argument("--expected-generation", default=None)
    rollback.add_argument("--authorize-as", required=True)
    for name in ("deprecate", "revoke"):
        command = common(sub.add_parser(name))
        command.add_argument("revision")
        command.add_argument("--reason", required=True)
    prune_cmd = common(sub.add_parser("prune"))
    prune_cmd.add_argument("--apply", action="store_true")
    prune_cmd.add_argument("--dry-run", action="store_true")
    prune_cmd.add_argument("--max-age-days", type=int)
    forget_cmd = common(sub.add_parser("forget"))
    forget_cmd.add_argument("--event")
    forget_cmd.add_argument("--revision")
    common(sub.add_parser("sync"))
    profile = common(sub.add_parser("profile"), scope=False)
    profile.add_argument("action", choices=("enroll", "unenroll", "show"))
    profile.add_argument("--profile", required=True)
    profile.add_argument("--consent-aggregate", action="store_true", help="Allow this repository's aggregate evidence in global candidates")
    generalize_cmd = common(sub.add_parser("generalize"), scope=False)
    generalize_cmd.add_argument("--profile", required=True)
    generalize_cmd.add_argument("--kind", required=True)
    generalize_cmd.add_argument("--artifact", required=True)
    generalize_cmd.add_argument("--slot", required=True)
    generalize_cmd.add_argument("--text-file", help="Sanitized general wording (host or human authored)")
    generalize_cmd.add_argument("--repo", action="append", default=[], help="Enrolled repository path whose evidence to aggregate; repeatable")
    generalize_cmd.add_argument("--apply", action="store_true", help="Propose the resulting document into the profile store")
    export = common(sub.add_parser("export"))
    export.add_argument("--output", help="Explicit destination file; omit for --dry-run")
    export.add_argument("--dry-run", action="store_true")
    export.add_argument("--revision", action="append", default=[])
    common(sub.add_parser("export-generation")).add_argument("--output", required=True)
    imported = common(sub.add_parser("import-generation"))
    imported.add_argument("--from", dest="source", required=True)
    imported.add_argument("--experiment", required=True)
    imported.add_argument("--authorize-as", required=True)
    configure = common(sub.add_parser("configure"), scope=False)
    configure.add_argument("--enable", action="store_true")
    configure.add_argument("--disable", action="store_true")
    configure.add_argument("--mode", choices=MODES)
    configure.add_argument("--record-observations", choices=("on", "off"))
    configure.add_argument("--kinds", help="Comma-separated artifact kinds")
    configure.add_argument("--set-profile", help="Profile name, or `none`")
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except (LearningError, _STORE["StoreError"], _sibling("learning_eval")["EvaluationError"]) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, UnicodeError):
        print("Procedural learning could not complete; local I/O failed.", file=sys.stderr)
        return 2


def _print(result):
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, default=str))


def _dispatch(args):  # noqa: C901 - one command table
    root = _project(args.project)
    if args.command == "configure":
        changes = {}
        if args.enable and args.disable:
            raise LearningError("Choose --enable or --disable.")
        if args.enable:
            changes["enabled"] = True
        if args.disable:
            changes["enabled"] = False
        if args.mode:
            changes["mode"] = args.mode
        if args.record_observations:
            changes["observation"] = {"record": args.record_observations == "on"}
        if args.kinds:
            changes["kinds"] = [k.strip() for k in args.kinds.split(",") if k.strip()]
        if args.set_profile:
            changes["profile"] = None if args.set_profile == "none" else args.set_profile
        updated = write_settings(args.config, changes, project=root)
        _print({"written": str(Path(args.config).expanduser() if args.config else settings_path()), "settings": {k: updated[k] for k in ("enabled", "mode", "kinds", "profile", "observation")}})
        return 0
    settings = load_settings(args.config, project=root)
    pack = _pack(args.pack)
    if args.command == "status":
        _print(command_status(args, settings, root))
        return 0
    if args.command == "explain":
        _print(command_explain(args, settings, root, pack))
        return 0
    if not settings["enabled"]:
        raise LearningError("Procedural learning is off; run `learning configure --enable --mode shadow` (a settings file outside the project) first. Nothing was written.")
    identity = args.identity or os.environ.get("AGENT_DISPATCHER_INDEX_ID") or None
    repo_dir = repo_directory(root, identity)
    if args.command == "observe":
        if not settings["observation"]["record"]:
            raise LearningError("Observation recording is off (observation.record); nothing was written.")
        document = _read_document(args.observation_file)
        if document.get("event_id") != args.event:
            raise LearningError("--event and the observation's event_id disagree.")
        experience = experience_store(repo_dir)
        if experience is None:
            raise LearningError("No experience store: record the task with repository_memory.py record first.")
        try:
            with open_store(repo_dir, create=True, readonly=False) as store:
                if not store.meta("pack"):
                    with store.transaction():
                        store.set_meta("pack", str(pack))
                _print(observe(store, experience, document))
        finally:
            experience.close()
        return 0
    if args.command == "profile":
        profile_dir = profile_directory(args.profile)
        namespace = repo_namespace(root, identity)
        if args.action == "show":
            if not store_exists(profile_dir):
                _print({"profile": args.profile, "status": "absent"})
                return 0
            with open_store(profile_dir, readonly=True) as store:
                _print({"profile": args.profile, "enrollments": store.enrollments(), "this_repository": namespace, "counts": store.counts()})
            return 0
        with open_store(profile_dir, create=True, readonly=False) as store:
            if args.action == "enroll":
                with open_store(repo_dir, create=True, readonly=False) as repo:
                    _print(dict(enroll(store, repo, namespace, consent_aggregate=args.consent_aggregate, project_label=root.name), profile=args.profile))
            else:
                _print(dict(unenroll(store, namespace, settings), profile=args.profile, namespace=namespace))
        return 0
    if args.command == "generalize":
        profile_dir = profile_directory(args.profile)
        if not store_exists(profile_dir):
            raise LearningError("Profile store is absent; enroll a repository first.")
        sources = []
        for repo_path in args.repo:
            repo_root = _project(repo_path)
            directory = repo_directory(repo_root)
            if not store_exists(directory):
                continue
            with open_store(directory, readonly=True) as repo:
                experience = experience_store(directory)
                lexicon = private_lexicon(experience)
                if experience is not None:
                    experience.close()
                for revision in repo.revisions(kind=args.kind, artifact_id=args.artifact, states=LIVE + ("evaluation_passed", "awaiting_approval", "approved")):
                    evaluations = [e for e in repo.evaluations(revision["revision_id"]) if e["status"] == "passed"]
                    sources.append({"namespace": directory.name, "revision": revision, "lexicon": lexicon, "families": len(revision["task_families"]),
                                    "evaluation_summary": {"evaluation_id": evaluations[-1]["evaluation_id"], "status": "passed"} if evaluations else None})
        text = Path(args.text_file).read_text(encoding="utf-8") if args.text_file else None
        with open_store(profile_dir, create=False, readonly=not args.apply) as store:
            result = generalize(store, sources, settings, kind=args.kind, artifact_id=args.artifact, slot=args.slot, text=text)
            if args.apply and not result["no_change"]:
                result["proposed"] = propose_candidate(store, None, result["document"], settings, pack=pack, namespace="profile:" + args.profile,
                                                       scope="global", provenance=result["provenance"])
        _print(result)
        return 0
    scope, store, directory = _scope_store(args, settings, root, create=args.command in ("propose", "review", "import-generation"),
                                           readonly=args.command in ("list", "show", "diff", "effective", "evaluations", "history", "export", "export-generation")
                                           or (args.command == "review" and not args.apply) or (args.command == "prune" and not args.apply))
    experience = experience_store(repo_dir) if scope == "repo" else None
    try:
        with store:
            if args.command in ("propose", "review", "import-generation") and not store.meta("pack"):
                with store.transaction():
                    store.set_meta("pack", str(pack))
            result = _mutations(args, settings, root, pack, scope, store, experience, directory)
    finally:
        if experience is not None:
            experience.close()
    if isinstance(result, str):
        print(result)
    else:
        _print(result)
    return 0


def _mutations(args, settings, root, pack, scope, store, experience, directory):  # noqa: C901
    compose = _sibling("learning_compose")
    evaluation_module = _sibling("learning_eval")
    if args.command == "list":
        rows = store.revisions(kind=args.kind, states=[args.state] if args.state else None)
        return {"scope": scope, "revisions": [_summary(r) for r in rows], "active_generation": (store.active_generation() or {}).get("generation_id"), "review": review_due(store, settings)}
    if args.command == "show":
        revision = store.revision(args.id)
        if revision is not None:
            return dict(revision, support=support_status(store, experience, revision), history=store.history(args.id))
        for getter in (store.review, store.evaluation, store.generation):
            record = getter(args.id)
            if record is not None:
                return record
        raise LearningError("Unknown id.")
    if args.command == "diff":
        return export_patch(store, pack, [args.id])
    if args.command == "effective":
        base = base_body(pack, args.kind, args.artifact)
        catalog = package_catalog(pack)
        _, rows = eligible_revisions(store, settings)
        layers = [_layer(r) for r in rows if r["artifact_kind"] == args.kind and r["artifact_id"] == args.artifact and r.get("runtime_state") == "live"]
        layers.sort(key=lambda layer: (layer["scope"] != "global", layer["revision_id"]))
        workflow = compose["workflow_view"](catalog["workflows"][args.artifact]) if args.kind == "recipe_overlay" and args.artifact in catalog["workflows"] else None
        composed = compose["compose"](args.kind, base["content"], layers, workflow) if layers else {"content": base["content"], "state": "not_applicable", "reason": "no live overlay", "diff": []}
        return {"artifact_id": args.artifact, "kind": args.kind, "base_sha256": base["sha256"], "effective_sha256": compose["text_digest"](composed["content"]),
                "state": composed["state"], "reason": composed["reason"], "layers": [{k: v for k, v in layer.items() if k in ("revision_id", "scope", "slot")} for layer in layers],
                "derived_block": composed["diff"], "content": composed["content"]}
    if args.command == "evaluations":
        return {"evaluations": [{k: v for k, v in e.items() if k != "spec"} for e in store.evaluations(args.revision)]}
    if args.command == "history":
        return {"revision_id": args.revision, "history": store.history(args.revision)}
    if args.command == "review":
        synced = sync_support(store, experience, settings) if args.apply else {"changed": [], "suspended": []}
        catalog = package_catalog(pack)
        last = store.reviews()
        review = review_experience(store, experience, settings, catalog, cursor=last[-1]["cursor"] if last else None, scope=scope)
        result = {"review": review, "due": review_due(store, settings), "stored": False, "candidates": [], "sync": synced}
        if args.packet:
            result["packet"] = review_packet(review, scope=scope)
        if args.apply:
            with store.transaction():
                store.add_review(review)
            result["stored"] = True
            for hypothesis in review["hypotheses"]:
                document = hypothesis_document(hypothesis)
                if document is None:
                    result["candidates"].append({"pattern": hypothesis["pattern"], "status": "host_wording_required"})
                    continue
                try:
                    result["candidates"].append(dict(propose_candidate(store, experience, document, settings, pack=pack, namespace=directory.name, scope=scope, review_id=review["review_id"]), pattern=hypothesis["pattern"]))
                except LearningError as exc:
                    result["candidates"].append({"pattern": hypothesis["pattern"], "status": "rejected", "reason": str(exc)})
            for ident in review["quarantine"]:
                result.setdefault("quarantined", []).append(revoke(store, ident, "severe failure observed while emitted", settings, quarantine_only=True))
        return result
    if args.command == "propose":
        if args.provider:
            packet = None
            if args.review:
                review = store.review(args.review)
                if review is None:
                    raise LearningError("Unknown review id.")
                packet = review_packet(review, scope=scope)
            else:
                catalog = package_catalog(pack)
                packet = review_packet(review_experience(store, experience, settings, catalog, scope=scope), scope=scope)
            context = _sibling("context")
            reply = propose_with_provider(packet, settings, scrub=context["_scrubber"](pack))
            if reply["no_change"]:
                return reply
            return dict(propose_candidate(store, experience, reply["document"], settings, pack=pack, namespace=directory.name, scope=scope, review_id=args.review, creation_cost=reply["cost"]), cost=reply["cost"])
        if not args.from_file:
            raise LearningError("propose needs --from-file or --provider.")
        document = _read_document(args.from_file, limit=compose["MAX_DOCUMENT_BYTES"])
        return propose_candidate(store, experience, document, settings, pack=pack, namespace=directory.name, scope=scope, review_id=args.review)
    if args.command == "component-check":
        return evaluation_module["component_checks"](store, args.revision, settings, pack=pack)
    if args.command == "evaluate":
        spec = _read_document(args.spec)
        return evaluation_module["evaluate_candidate"](store, experience, args.revision, spec, settings, pack=pack, runner=args.runner, batch=args.batch, fixture_results=args.fixture_results)
    if args.command == "approve":
        authorization = {"kind": "human", "actor": args.authorize_as, "statement": args.statement, "rollout": args.rollout}
        canary = {k: v for k, v in (("max_tasks", args.canary_tasks), ("max_days", args.canary_days)) if v is not None}
        return approve_candidate(store, experience, args.revision, args.evaluation, args.expected_generation, authorization, settings, pack=pack, canary=canary or None)
    if args.command == "promote":
        return promote_candidate(store, experience, args.revision, args.expected_generation, settings, pack=pack)
    if args.command == "canary":
        return start_experimental_canary(store, args.revision, {"kind": "human", "actor": args.authorize_as}, settings, experiment=args.experiment, max_tasks=args.tasks, max_days=args.days)
    if args.command == "rollback":
        return rollback_generation(store, args.expected_generation, None if args.target_generation == "base" else args.target_generation, {"kind": "human", "actor": args.authorize_as}, settings, pack=pack)
    if args.command == "deprecate":
        return deprecate(store, args.revision, args.reason, settings)
    if args.command == "revoke":
        return revoke(store, args.revision, args.reason, settings)
    if args.command == "prune":
        return prune(store, settings, apply=args.apply and not args.dry_run, max_age_days=args.max_age_days)
    if args.command == "forget":
        return forget(store, experience, settings, event_id=args.event, revision_id=args.revision)
    if args.command == "sync":
        return sync_support(store, experience, settings)
    if args.command == "export":
        ids = args.revision or (store.active_generation() or {}).get("revision_ids", [])
        text = export_patch(store, pack, ids)
        if args.output and not args.dry_run:
            target = Path(args.output).expanduser().resolve()
            if target.is_relative_to(Path(pack).resolve()) or target.exists() and not target.is_file():
                raise LearningError("Export destination must be an explicit file outside the installed package.")
            target.write_text(text, encoding="utf-8")
            return {"written": str(target), "revisions": len(ids)}
        return text
    if args.command == "export-generation":
        document = export_generation(store, settings)
        target = Path(args.output).expanduser().resolve()
        if target.is_relative_to(Path(pack).resolve()):
            raise LearningError("Export destination must be outside the installed package.")
        target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"written": str(target), "revisions": len(document["revisions"]), "generation_id": document["generation_id"]}
    if args.command == "import-generation":
        document = _read_document(args.source)
        return import_generation(store, experience, document, settings, {"kind": "human", "actor": args.authorize_as}, pack=pack, experiment=args.experiment)
    raise LearningError("Unknown command.")


if __name__ == "__main__":
    raise SystemExit(main())
