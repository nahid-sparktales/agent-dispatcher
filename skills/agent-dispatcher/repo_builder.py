"""Deep deterministic repository indexing: complete inventory, batches, checkpoints, incremental refresh.

    build    enumerate everything the admission policy allows -> deterministic batches -> per-file
             records, symbols, edges, corpus statistics, bounded history -> atomic publication
    refresh  reconcile the working tree (committed, staged, unstaged, untracked, deleted, renamed)
             by metadata signature (fast) or content hash (strict); recompute only what changed;
             sweep obsolete rows only after a complete enumeration; publish a new generation
    status   read-only: coverage, freshness, counters; creates nothing

The extractor is `repo_index.file_record` (the same one the context helper uses), the admission
rules are `context._skip`/`_read`/redaction (the same ones every scan uses), and history goes
through the hardened `context._bounded_output`. Nothing here executes project code, follows a
symlink, reads a credential file, or opens a file the helper would refuse.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import time

VERSION = 1  # Extractor/builder version; part of the policy fingerprint that keys every record.
DEFAULTS = {
    "max_files": 50000,
    "max_admitted_bytes": 256 * 1024 * 1024,
    "batch_size": 200,
    "max_seconds": None,  # Elapsed work budget for one build/refresh; None means unbounded.
    "verify": "fast",  # "fast": metadata signature; "strict": re-hash every file's content.
    "history": {"max_commits": 5000, "max_commit_files": 30, "min_support": 2, "half_life_days": None,
                "max_bytes": 16 * 1024 * 1024, "max_paths_per_commit": 200, "subject_chars": 120},
}
MAX_SETTINGS_BYTES = 64 * 1024
_TRANSPORT = {"provider": None, "model": None, "base_url": None, "api_key_env": None, "command": None,
              "temperature": 0, "timeout": 120, "max_retries": 1, "extra_body": {}, "price_per_mtok": None}
# The user's own settings file (never a project file) decides every optional capability separately:
# whether a published deep index is used, whether authorized tasks may maintain it, whether the onboarding
# Explorer may call a model, and whether task experience is recorded and/or used.
SETTINGS = {
    "index": {"use": "auto",  # "auto": use a published index when one exists; "off"; "require": report when absent
              "maintain": {"enabled": True, "max_seconds": 10, "max_files": 500},
              "build": {}},  # Overrides of DEFAULTS for build/refresh.
    "exploration": dict(_TRANSPORT, enabled=False, max_iterations=8, max_operations=40, max_calls=12, max_evidence_bytes=200000,
                        max_input_tokens=300000, max_output_tokens=1200, max_total_output_tokens=30000, max_seconds=600,
                        max_spend_usd=None, max_snippet_lines=60, questions=None),
    "experience": {"record": False, "use": False, "eligible_outcomes": list(("checked_success", "accepted")), "exposure_log": None},
}
GIT_STATUS_KINDS = {"M": "modified", "A": "added", "D": "deleted", "R": "renamed", "C": "copied", "T": "typechange", "U": "unmerged", "?": "untracked"}


class BuildError(ValueError):
    """Bounded diagnostic; never echoes file contents or untrusted values."""


_SIBLINGS = {}


def _sibling(name):
    if name not in _SIBLINGS:
        path = Path(__file__).resolve().with_name(name + ".py")
        namespace = {"__name__": "_dispatcher_builder_" + name, "__file__": str(path)}
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
        _SIBLINGS[name] = namespace
    return _SIBLINGS[name]


def _merge(base, overrides):
    out = json.loads(json.dumps(base))
    for key, value in (overrides or {}).items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def policy_fingerprint(scrub, config):
    """Everything a stored record depends on besides the source: extractor code, redaction, history settings."""
    root = Path(__file__).resolve().parent
    files = {}
    for name in ("repo_index.py", "repo_builder.py", "context.py"):
        path = root / name
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return _digest({"version": VERSION, "record_schema": _sibling("repo_index")["SCHEMA"], "files": files,
                    "redaction": getattr(scrub, "_dispatcher_policy", None), "history": config["history"]})


def _signature(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode, info.st_uid, info.st_nlink]


def path_state(project, relative):
    """(signature, reason): the metadata identity of a regular, non-linked file, or why there is none.

    `missing` is a tracked path with no file behind it (deleted in the working tree): absent, not failed.
    """
    cursor = project
    try:
        for part in PurePosixPath(relative).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                return None, "symlink withheld"
        info = os.stat(cursor, follow_symlinks=False)
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "unreadable or unsafe path"
    if not stat.S_ISREG(info.st_mode):
        return None, "not a regular file"
    return _signature(info), None


def stat_signature(project, relative):
    """Metadata identity of a regular, non-linked file; None when the path is unsafe or missing."""
    return path_state(project, relative)[0]


# ---------------------------------------------------------------- inventory and working tree state


def enumerate_inventory(project, max_files, diagnostics):
    """Every path Git or ripgrep lists, without the context helper's 10,000-path prefix."""
    context = _sibling("context")
    git, rg = shutil.which("git"), shutil.which("rg")
    commands = []
    if git:
        commands.append([git, "-c", "core.fsmonitor=false", "-C", str(project), "ls-files", "--cached", "--others",
                         "--exclude-standard", "-z", "--", "."])
    if rg:
        commands.append([rg, "--no-config", "--files", "--hidden", "-0", "-g", "!.git/**", "."])
    for command in commands:
        try:
            paths, okay, limited = context["_path_command"](command, project, max_bytes=64 * 1024 * 1024)
        except (OSError, TypeError):
            continue
        if not okay:
            continue
        paths = [p for p in paths if ".agent-dispatcher" not in PurePosixPath(p).parts]
        complete = not limited and len(paths) <= max_files
        if limited:
            diagnostics.append("Path enumeration reached its byte or time limit; the inventory is partial.")
        if len(paths) > max_files:
            diagnostics.append(f"Inventory exceeds the configured file limit ({max_files}); later paths are omitted.")
        return paths[:max_files], complete
    diagnostics.append("Ignore-aware file enumeration unavailable (Git or ripgrep required); nothing indexed.")
    return [], False


def git_state(project):
    """HEAD, branch and a NUL-safe porcelain summary of the working tree. Never a content decision by itself."""
    context = _sibling("context")
    git = shutil.which("git")
    state = {"available": bool(git), "head": None, "branch": None, "detached": None, "unborn": None, "shallow": None,
             "changes": {}, "changed_paths": []}
    if not git:
        return state
    base = [git, "-c", "core.fsmonitor=false", "-c", "core.quotepath=off"]
    head, code, _ = context["_bounded_output"](base + ["rev-parse", "--verify", "--quiet", "HEAD"], project)
    if code == 0 and head:
        state["head"] = head.decode("ascii", "replace").strip()
    else:
        inside, code, _ = context["_bounded_output"](base + ["rev-parse", "--is-inside-work-tree"], project)
        if code != 0:
            state["available"] = False
            return state
        state["unborn"] = True
    branch, code, _ = context["_bounded_output"](base + ["symbolic-ref", "--quiet", "--short", "HEAD"], project)
    state["branch"] = branch.decode("utf-8", "replace").strip() if code == 0 and branch else None
    state["detached"] = state["branch"] is None and state["head"] is not None
    shallow, code, _ = context["_bounded_output"](base + ["rev-parse", "--is-shallow-repository"], project)
    state["shallow"] = shallow.decode("ascii", "replace").strip() == "true" if code == 0 and shallow else None
    raw, code, limited = context["_bounded_output"](base + ["status", "--porcelain=v1", "-z", "--untracked-files=all",
                                                            "--ignore-submodules=all", "--no-renames", "--", "."], project)
    if raw is None or code != 0 or limited:
        state["changes"] = {"unknown": True}
        return state
    counts, changed = Counter(), []
    for entry in raw.split(b"\0"):
        if len(entry) < 4:
            continue
        code_x, code_y, path = chr(entry[0]), chr(entry[1]), entry[3:].decode("utf-8", "replace")
        if code_x == "?":
            counts["untracked"] += 1
        else:
            if code_x != " ":
                counts["staged_" + GIT_STATUS_KINDS.get(code_x, "other")] += 1
            if code_y != " ":
                counts["unstaged_" + GIT_STATUS_KINDS.get(code_y, "other")] += 1
        changed.append(path)
    state["changes"] = dict(counts)
    state["changed_paths"] = sorted(set(changed))[:10000]
    return state


# ---------------------------------------------------------------- history


def fetch_history(project, universe, config, scrub, *, since=None):
    """Bounded `git log` from HEAD only (never other refs or the reflog), reduced to admitted paths.

    Returns (commits newest first, horizon). Commit subjects are scrubbed and capped; authors are
    never read. Renames are Git similarity matches (`R<score>`), recorded as evidence, not identity.
    """
    context = _sibling("context")
    git = shutil.which("git")
    tuning = config["history"]
    horizon = {"head": None, "commits": 0, "truncated": False, "shallow": None, "since": since, "available": bool(git),
               "first_parent": False, "scope": "commits reachable from HEAD"}
    if not git:
        return [], horizon
    base = [git, "-c", "core.fsmonitor=false", "-c", "core.quotepath=off", "-c", "diff.external=", "-c", "core.pager=cat"]
    head, code, _ = context["_bounded_output"](base + ["rev-parse", "--verify", "--quiet", "HEAD"], project)
    if code != 0 or not head:
        horizon["available"] = False
        return [], horizon
    horizon["head"] = head.decode("ascii", "replace").strip()
    shallow, code, _ = context["_bounded_output"](base + ["rev-parse", "--is-shallow-repository"], project)
    horizon["shallow"] = shallow.decode("ascii", "replace").strip() == "true" if code == 0 and shallow else None
    revision = f"{since}..HEAD" if since else "HEAD"
    raw, code, limited = context["_bounded_output"](
        base + ["log", revision, f"-n{tuning['max_commits']}", "--no-merges", "-M", "--name-status", "--relative",
                "--no-ext-diff", "--no-textconv", "--format=%x01%H%x02%ct%x02%s", "--", "."],
        project, max_bytes=tuning["max_bytes"])
    if raw is None or (code != 0 and not limited):
        horizon["available"] = False
        return [], horizon
    commits = []
    for block in raw.decode("utf-8", "replace").split("\x01")[1:]:
        header, _, body = block.partition("\n")
        parts = header.split("\x02")
        if len(parts) != 3:
            continue
        try:
            stamp = int(parts[1].strip())
        except ValueError:
            continue
        paths, renames = [], []
        for line in body.split("\n"):
            fields = line.split("\t")
            status = fields[0].strip()
            if not status:
                continue
            if status[0] in "RC" and len(fields) == 3:
                old, new = fields[1], fields[2]
                # The old name is no longer in the universe by definition; it is admitted as evidence only when the
                # policy would have admitted it (never a credential name) and the new name is indexed.
                if new in universe and not context["_skip"](old):
                    try:
                        score = int(status[1:] or "0")
                    except ValueError:
                        score = 0
                    renames.append([old, new, score])
                for path in (old, new):
                    if path in universe:
                        paths.append(path)
            elif len(fields) == 2 and fields[1] in universe:
                paths.append(fields[1])
        paths = sorted(set(paths))
        commits.append({"sha": parts[0].strip()[:40], "stamp": stamp, "subject": scrub(parts[2])[:tuning["subject_chars"]],
                        "paths": paths[:tuning["max_paths_per_commit"]], "renames": renames[:50], "touched": len(paths),
                        "capped": len(paths) > tuning["max_paths_per_commit"]})
    if limited:
        # A cut-off log ends with a commit whose file list may be incomplete; drop it rather than trust it.
        commits = commits[:-1]
    horizon.update(commits=len(commits), truncated=limited or len(commits) >= tuning["max_commits"])
    return commits, horizon


def cochange_from(commits, config):
    facts = _sibling("repo_index")
    tuning = config["history"]
    rows = [(c["stamp"], c["paths"]) for c in commits if 2 <= len(c["paths"]) <= tuning["max_commit_files"] and not c.get("capped")]
    return facts["cochange"](rows, min_support=tuning["min_support"], half_life_days=tuning["half_life_days"])


def filter_commits(commits, universe):
    """Stored commits re-reduced to the current universe, so history never keeps a path the index dropped."""
    out = []
    for commit in commits:
        paths = [p for p in commit["paths"] if p in universe]
        renames = [pair for pair in commit.get("renames", []) if pair[1] in universe]
        out.append(dict(commit, paths=paths, renames=renames, touched=len(paths)))
    return out


def _ancestor(project, old, new):
    context = _sibling("context")
    git = shutil.which("git")
    if not git or not old or not new or old == new:
        return old == new
    _, code, _ = context["_bounded_output"]([git, "-c", "core.fsmonitor=false", "merge-base", "--is-ancestor", old, new], project)
    return code == 0


# ---------------------------------------------------------------- symbols and edges


def symbol_rows(path, record, text):
    """Stable identities from language, path, qualified name, kind and order of appearance; location and
    content fingerprints kept apart so a line shift changes neither identity nor content."""
    lines = text.split("\n")
    seen = Counter()
    rows = []
    for name, kind, line, end, parent in record["defs"]:
        qualname = f"{parent}.{name}" if parent else name
        seen[(qualname, kind)] += 1
        occurrence = seen[(qualname, kind)]
        ident = hashlib.sha256("\0".join((record["lang"], path, qualname, kind, str(occurrence))).encode("utf-8")).hexdigest()[:20]
        span = "\n".join(lines[max(0, line - 1):max(line, end)])
        rows.append({"id": ident, "name": name, "qualname": qualname, "kind": kind, "line": line, "end_line": max(line, end),
                     "parent": parent or None, "fingerprint": hashlib.sha256(span.encode("utf-8")).hexdigest(), "status": "current"})
    return rows


_EDGE_METHODS = {"imports": ("python-ast-import", "resolved"), "calls": ("ast-call-name-unique-definition", "candidate"),
                 "references": ("identifier-mention-unique-definition", "candidate"), "inherits": ("ast-base-name-unique-class", "candidate"),
                 "tested_by": ("test-naming-or-import", "candidate")}


def edge_rows(index):
    """Persisted relationships carry the method and a status that says how far the evidence goes."""
    rows = []
    for source, targets in index.edges.items():
        lang = index.records.get(source, {}).get("lang", "other")
        for target, kinds in targets.items():
            for kind, detail in kinds.items():
                method, status = _EDGE_METHODS[kind]
                if kind == "imports" and lang != "python":
                    method = "relative-import-path"
                elif kind in ("calls", "references", "inherits") and lang != "python":
                    method = "regex-declaration-" + method
                rows.append({"source": source, "target": target, "kind": kind, "method": method, "status": status, "detail": detail})
    return rows


def relationship_coverage(index):
    """Named calls that resolve, are ambiguous (several definitions) or unknown: labeled, never guessed."""
    resolved = ambiguous = unresolved = 0
    facts = _sibling("repo_index")
    for path, record in index.records.items():
        own = {row[0] for row in record["defs"]}
        for name in record["calls"]:
            if name in own:
                continue
            found = index.definitions.get(name)
            if not found:
                unresolved += 1
            elif len({row[0] for row in found}) > facts["MAX_DEF_FILES"]:
                ambiguous += 1
            else:
                resolved += 1
    return {"call_targets": {"resolved_candidate": resolved, "ambiguous": ambiguous, "unresolved": unresolved}}


def rename_aliases(store, generation, commits, changed):
    """A symbol that moved with a Git rename keeps a link to its old identity only when the content
    fingerprint matches; otherwise the connection is recorded as uncertain."""
    added = 0
    old_symbols = {}
    for commit in commits:
        for old, new, score in commit.get("renames", []):
            if new not in changed:
                continue
            if old not in old_symbols:
                old_symbols[old] = {(row["qualname"], row["kind"]): row for row in store.symbols(path=old, limit=2000)}
            for row in store.symbols(path=new, limit=2000):
                previous = old_symbols[old].get((row["qualname"], row["kind"]))
                if previous is None or previous["id"] == row["id"]:
                    continue
                exact = previous["fingerprint"] == row["fingerprint"]
                store.add_alias(generation, row["id"], previous["id"], f"git-rename-R{score}" + ("+content-fingerprint" if exact else ""),
                                "supported" if exact else "uncertain")
                added += 1
    return added


# ---------------------------------------------------------------- the builder


class Builder:
    """One build or refresh over one project, writing to an open IndexStore."""

    def __init__(self, project, store, scrub, config=None, *, log=None):
        self.project = Path(project).resolve()
        self.store = store
        self.scrub = scrub
        self.config = _merge(DEFAULTS, config)
        self.context = _sibling("context")
        self.facts = _sibling("repo_index")
        self.retrieval = _sibling("retrieval")
        self.log = log or (lambda line: None)
        self.counters = Counter()
        self.timings = {}
        self.diagnostics = []
        self.policy = policy_fingerprint(scrub, self.config)
        self.started = time.monotonic()

    # ---- helpers

    def _time(self, stage, started):
        self.timings[stage] = round(self.timings.get(stage, 0.0) + (time.monotonic() - started) * 1000, 1)

    def _over_budget(self):
        limit = self.config["max_seconds"]
        return limit is not None and time.monotonic() - self.started > limit

    def _read(self, relative, remaining):
        """Policy read through the helper's reader; returns (redacted text, raw sha, size, reason)."""
        text, used, reason = self.context["_read"](self.project, relative, remaining)
        self.counters["reads"] += 1
        self.counters["bytes_read"] += used
        if reason:
            return None, None, used, reason
        self.counters["hashes"] += 1
        raw_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return self.context["_redact_source"](text, self.scrub), raw_sha, used, None

    def _row(self, relative, signature, text, sha, used, reason):
        if reason:
            status = "oversized" if reason == "file exceeds 256 KiB limit" else "binary" if reason == "binary file withheld" else "failed"
            return {"path": relative, "sha256": None, "signature": signature, "size": used, "lang": None,
                    "kind": self.context["_kind"](relative), "status": status, "reason": reason, "record": None}
        record = self.facts["file_record"](relative, text)
        self.counters["parses"] += 1
        return {"path": relative, "sha256": sha, "signature": signature, "size": used, "lang": record["lang"],
                "kind": self.context["_kind"](relative), "status": "indexed", "reason": None, "record": record}

    # ---- the passes

    def run(self, *, mode="build", resume=False):
        """build: every admitted file; refresh: only what changed. Both publish atomically or leave a partial generation."""
        if mode not in ("build", "refresh"):
            raise BuildError("Mode must be build or refresh.")
        published = self.store.published()
        building = self.store.building()
        stored_policy = self.store.meta("policy")
        policy_changed = stored_policy is not None and stored_policy != self.policy
        if policy_changed:
            self.diagnostics.append("Extraction or redaction policy changed; every record is recomputed.")
            mode = "build"
        if mode == "refresh" and published is None:
            raise BuildError("No published index to refresh; run build first.")
        strict = self.config["verify"] == "strict"
        started = time.monotonic()
        paths, complete = enumerate_inventory(self.project, self.config["max_files"], self.diagnostics)
        self.counters["enumerated"] = len(paths)
        git = git_state(self.project)
        self._time("enumerate_ms", started)
        snapshot = {"head": git["head"], "branch": git["branch"], "detached": git["detached"], "unborn": git["unborn"],
                    "shallow": git["shallow"], "worktree_changes": git["changes"],
                    "semantics": "working tree content over HEAD; staged-but-unsaved content is not indexed",
                    "policy": self.policy, "verify": "strict" if strict else "fast", "mode": mode}
        with self.store.transaction():
            if resume and building is not None and building["policy"] == self.policy:
                generation = building["id"]
                self.diagnostics.append(f"Resuming interrupted generation {generation}.")
            else:
                generation = self.store.start_generation(self.policy, mode, snapshot)
            self.store.set_meta("policy", self.policy)
            self.store.set_meta("project", {"path": str(self.project)})
        excluded = Counter()
        admitted = []
        for path in paths:
            reason = self.context["_skip"](path)
            if reason:
                excluded[reason] += 1
            else:
                admitted.append(path)
        existing = self.store.file_rows(admitted) if not policy_changed else {}
        done = {p for p, row in existing.items() if row["generation"] == generation} if resume else set()
        todo = [p for p in admitted if p not in done]
        self.counters["policy_excluded"] = sum(excluded.values())
        self.counters["resumed"] = len(done)
        reused = changed = failed = 0
        remaining = self.config["max_admitted_bytes"]
        pending, changed_paths, missing = [], [], []
        batch, touch, signatures = [], [], {}
        stage = time.monotonic()

        def commit_batch():
            nonlocal batch, touch, signatures
            if not batch and not touch:
                return
            with self.store.transaction():
                self.store.upsert_files(generation, [row for row, _ in batch])
                for row, text in batch:
                    if row["status"] == "indexed":
                        self.store.replace_symbols(generation, row["path"], symbol_rows(row["path"], row["record"], text))
                        self.counters["symbols_written"] += len(row["record"]["defs"])
                self.store.touch(generation, touch, signatures)
                self.counters["writes"] += 1
            self.log(f"[{reused + changed + failed} / {len(todo)}] reused: {reused} recomputed: {changed} failed: {failed}")
            batch, touch, signatures = [], [], {}

        for number, path in enumerate(todo):
            if self._over_budget():
                pending = todo[number:]
                break
            signature, problem = path_state(self.project, path)
            self.counters["stats"] += 1
            previous = existing.get(path)
            indexed_before = bool(previous and previous["status"] == "indexed")
            if problem == "missing":
                missing.append(path)  # Tracked but deleted from the working tree: absent, swept with the rest.
            elif signature is None:
                batch.append((self._row(path, None, None, None, 0, problem), None))
                failed += 1
            elif indexed_before and not strict and previous["signature"] == signature:
                touch.append(path)
                reused += 1
                self.counters["records_reused"] += 1
            else:
                if remaining <= 0:
                    pending = todo[number:]
                    self.diagnostics.append("Admitted byte budget exhausted; remaining files are pending.")
                    break
                text, sha, used, reason = self._read(path, remaining)
                remaining -= used
                if reason is None and indexed_before and sha == previous["sha256"]:
                    # Metadata differs (or strict mode) but the content is identical: keep the record and symbols.
                    touch.append(path)
                    signatures[path] = signature
                    reused += 1
                    self.counters["records_reused"] += 1
                    self.counters["metadata_only_changes"] += 1
                else:
                    row = self._row(path, signature, text, sha, used, reason)
                    batch.append((row, text))
                    changed_paths.append(path)
                    changed += row["status"] == "indexed"
                    failed += row["status"] == "failed"
            if len(batch) + len(touch) >= self.config["batch_size"]:
                commit_batch()
        commit_batch()
        self._time("records_ms", stage)
        if pending:
            self.diagnostics.append(f"{len(pending)} files are pending: the elapsed or byte budget stopped this pass; the previous generation stays published.")
        moved = []
        if not pending:
            # Files that changed while this pass ran: re-check once; what still moves is reported, not hidden.
            stage = time.monotonic()
            current = self.store.file_rows(changed_paths)
            moved = [p for p in changed_paths if stat_signature(self.project, p) != current.get(p, {}).get("signature")]
            for path in moved:
                signature = stat_signature(self.project, path)
                text, sha, used, reason = self._read(path, self.config["max_admitted_bytes"]) if signature else (None, None, 0, "unreadable or unsafe path")
                row = self._row(path, signature, text, sha, used, reason)
                with self.store.transaction():
                    self.store.upsert_files(generation, [row])
                    if row["status"] == "indexed":
                        self.store.replace_symbols(generation, path, symbol_rows(path, row["record"], text))
            self._time("recheck_ms", stage)
            self.counters["changed_during_build"] = len(moved)
        coverage = self._coverage(paths, complete, excluded, pending, generation)
        coverage["deleted_in_worktree"] = len(missing)
        if pending or not complete:
            with self.store.transaction():
                self.store.abandon(generation, coverage)
            self.counters["published"] = 0
            return self.report(generation, coverage, snapshot, published=False)
        # Current membership is every row this generation touched; history and rename aliases are computed while
        # the rows of renamed-away files still exist, then obsolete rows are swept.
        rows = self.store.file_rows(generation=generation, with_record=True)
        records = {p: r["record"] for p, r in rows.items() if r["status"] == "indexed" and r["record"]}
        path_only = [p for p, r in rows.items() if r["status"] == "oversized"]
        universe = set(records) | set(path_only)
        history_stage = time.monotonic()
        commits, horizon = self._history(universe, published, snapshot)
        self._time("history_ms", history_stage)
        partners = cochange_from(commits, self.config)
        stage = time.monotonic()
        with self.store.transaction():
            self.counters["aliases_added"] = rename_aliases(self.store, generation, commits, set(changed_paths))
            removed = self.store.sweep(generation)
            self.counters["swept"] = len(removed)
        self._time("sweep_ms", stage)
        # Relationships are resolved over every current record: a changed import, definition or module name
        # retargets edges in files that did not change. Measured, not hidden.
        stage = time.monotonic()
        index = self.facts["RepoIndex"](records, self.context["_kind"], None, path_only) if records else None
        edges = edge_rows(index) if index else []
        with self.store.transaction():
            self.store.replace_edges(generation, edges)
            self.counters["edges_written"] = len(edges)
            self.store.replace_history(commits, partners, horizon)
            self.counters["history_commits"] = len(commits)
            self.counters["inferences_invalidated"] = self.store.invalidate_inferences({p: rows[p]["sha256"] for p in rows})
        self._time("relationships_ms", stage)
        coverage["relationships"] = relationship_coverage(index) if index else {}
        coverage["relationships"]["edges"] = len(edges)
        coverage["history"] = horizon
        coverage["complete_within_policy"] = True
        with self.store.transaction():
            self.store.publish(generation, coverage, snapshot)
        self.counters["published"] = 1
        return self.report(generation, coverage, snapshot, published=True)

    def _history(self, universe, published, snapshot):
        previous = self.store.meta("history") or {}
        old_head, new_head = previous.get("head"), snapshot["head"]
        if new_head and old_head and old_head != new_head and _ancestor(self.project, old_head, new_head) and self.store.counts()["commits"]:
            fresh, horizon = fetch_history(self.project, universe, self.config, self.scrub, since=old_head)
            older = filter_commits(self.store.commits(), universe)
            commits = (fresh + older)[:self.config["history"]["max_commits"]]
            horizon.update(commits=len(commits), truncated=horizon["truncated"] or previous.get("truncated", False), incremental=True)
            self.counters["history_incremental"] = 1
            return commits, horizon
        if new_head and old_head == new_head and self.store.counts()["commits"]:
            commits = filter_commits(self.store.commits(), universe)
            self.counters["history_reused"] = 1
            return commits, dict(previous, reused=True)
        commits, horizon = fetch_history(self.project, universe, self.config, self.scrub)
        if old_head and new_head and old_head != new_head:
            horizon["rebuilt"] = "history lineage changed (branch switch, rebase or non-ancestor HEAD)"
        return commits, horizon

    def _coverage(self, paths, complete, excluded, pending, generation):
        rows = self.store.file_rows(generation=generation)
        statuses = Counter(row["status"] for row in rows.values())
        languages = Counter(row["lang"] or "none" for row in rows.values() if row["status"] == "indexed")
        subsystems = {}
        for path in paths:
            top = path.split("/", 1)[0] if "/" in path else "(root)"
            item = subsystems.setdefault(top, Counter())
            item["discovered"] += 1
            row = rows.get(path)
            if row is None:
                item["excluded_or_pending"] += 1
            else:
                item[row["status"]] += 1
        ordered = sorted(subsystems.items(), key=lambda kv: (-kv[1]["discovered"], kv[0]))[:40]
        return {"discovered": len(paths), "enumeration_complete": complete, "policy_excluded": dict(sorted(excluded.items())),
                "indexed": statuses.get("indexed", 0), "oversized": statuses.get("oversized", 0), "binary": statuses.get("binary", 0),
                "failed": statuses.get("failed", 0), "pending": len(pending),
                "omitted": max(0, self.counters["enumerated"] - len(paths)),
                "unsupported_parser": sum(count for lang, count in languages.items() if lang in ("other", "python-unparsed")),
                "languages": dict(sorted(languages.items())), "by_subsystem": {name: dict(item) for name, item in ordered},
                "complete_within_policy": bool(complete and not pending)}

    def report(self, generation, coverage, snapshot, *, published):
        return {"generation": generation, "published": published, "coverage": coverage, "snapshot": snapshot,
                "counters": dict(self.counters), "timings_ms": self.timings, "diagnostics": list(dict.fromkeys(self.diagnostics)),
                "model_calls": 0, "elapsed_ms": round((time.monotonic() - self.started) * 1000, 1)}


# ---------------------------------------------------------------- read-only status


def freshness(store, project, *, sample=200):
    """Read-only, bounded: is the published generation current for the working tree? Metadata only."""
    generation = store.published()
    if generation is None:
        return {"status": "absent"}
    context = _sibling("context")
    diagnostics = []
    paths, complete = enumerate_inventory(project, 10**9, diagnostics)
    admitted = [p for p in paths if not context["_skip"](p)]
    rows = store.file_rows(generation=generation["id"])
    missing = [p for p in admitted if p not in rows]
    deleted = [p for p in rows if p not in set(admitted)]
    checked, stale = 0, []
    step = max(1, len(admitted) // sample) if sample else 1
    for path in admitted[::step][:sample]:
        row = rows.get(path)
        if row is None:
            continue
        checked += 1
        if stat_signature(project, path) != row["signature"]:
            stale.append(path)
    git = git_state(project)
    head_changed = generation["snapshot"] and generation["snapshot"].get("head") != git["head"]
    status = "stale" if (missing or deleted or stale or head_changed) else "fresh"
    return {"status": status, "generation": generation["id"], "enumeration_complete": complete, "new_paths": len(missing),
            "deleted_paths": len(deleted), "sampled": checked, "sample_changed": len(stale), "head_changed": bool(head_changed),
            "worktree_changes": git["changes"], "diagnostics": diagnostics,
            "note": "metadata sample; strict verification re-hashes content"}


# ---------------------------------------------------------------- trusted user settings


def settings_path():
    explicit = os.environ.get("AGENT_DISPATCHER_INDEX_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    config = os.environ.get("XDG_CONFIG_HOME")
    return (Path(config) if config and Path(config).is_absolute() else Path.home() / ".config") / "agent-dispatcher" / "repository-intelligence.json"


def load_settings(path=None, project=None):
    """Settings live outside every project; a repository must never switch a model call or memory on."""
    location = Path(path).expanduser() if path else settings_path()
    if project is not None:
        try:
            inside = location.resolve().is_relative_to(Path(project).expanduser().resolve())
        except OSError:
            inside = False
        if inside:
            raise BuildError("Repository-intelligence settings must live outside the inspected project.")
    try:
        if location.stat().st_size > MAX_SETTINGS_BYTES:
            raise BuildError("Repository-intelligence settings are too large.")
        loaded = json.loads(location.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _merge(SETTINGS, {})
    except (OSError, ValueError):
        raise BuildError("Repository-intelligence settings could not be read.") from None
    if not isinstance(loaded, dict):
        raise BuildError("Repository-intelligence settings must be a JSON object.")
    settings = _merge(SETTINGS, {key: value for key, value in loaded.items() if key in SETTINGS})
    if settings["index"]["use"] not in ("auto", "off", "require"):
        raise BuildError("index.use must be auto, off or require.")
    eligible = settings["experience"]["eligible_outcomes"]
    if not isinstance(eligible, list) or any(not isinstance(v, str) for v in eligible):
        raise BuildError("experience.eligible_outcomes must be a list of outcome names.")
    return settings
