"""Private SQLite stores for the deep repository index and task experience.

Both files live in the owner-only private state directory outside the project (the same
place as the project map and graph), never inside a working tree. Their trust model:

* The index store holds **derived facts only**, never source text. Every per-file record is
  bound to the fingerprint of the source it was computed from, and a reader uses a record only
  when the current scan reports that fingerprint (or strict verification re-hashed the file).
  Excerpts always come from the current, policy-filtered scan. A forged store can therefore
  affect ranking at worst; it cannot inject text, resurrect an excluded file, or grant a read.
* Readers never mix generations: a query sees the last *published* generation plus rows the
  current scan has just verified. A build that dies mid-way leaves a `building` generation
  that the next build resumes or the next reader ignores.
* Status and dry-run inspection open the file read-only and create nothing.

Why SQLite (standard library) instead of the HMAC-signed JSON parser cache: the index has
independent layers (files, terms, symbols, edges, history, inferences, experience) that must be
updated in small transactions without rewriting a 64 MiB blob, must survive interruption with
a resumable checkpoint, and must outgrow the parser cache's 12,000-entry ceiling. The parser
cache keeps its own contract untouched; only redacted *text* reuse still goes through it.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import time

SCHEMA = 1
INDEX_FILE = "repository-index.sqlite"
EXPERIENCE_FILE = "experience.sqlite"
BUSY_MS = 5000
MAX_EVENTS = 2000
FAILURES = (sqlite3.Error, OSError, ValueError, TypeError, KeyError, OverflowError)
EVIDENCE_KINDS = ("observation", "derived", "inference", "experience")


class StoreError(ValueError):
    """A bounded diagnostic; input values and file contents are never echoed."""


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _sibling(name):
    namespace = {"__name__": "_dispatcher_store_" + name, "__file__": str(Path(__file__).resolve().with_name(name + ".py"))}
    exec(compile(Path(namespace["__file__"]).read_text(encoding="utf-8"), namespace["__file__"], "exec"), namespace)
    return namespace


def state_directory(project, identity=None):
    """Private per-project directory; `identity` is an explicit, harness-controlled name that maps
    successive temporary workspaces of one benchmark sequence to one store."""
    private = _sibling("parser_cache")
    if identity:
        if not isinstance(identity, str) or not 0 < len(identity) <= 200 or "/" in identity or "\0" in identity:
            raise StoreError("Index identity must be a short name.")
        base = os.environ.get("XDG_CACHE_HOME", "")
        home = Path(base).resolve() if base and Path(base).is_absolute() else Path.home().resolve() / ".cache"
        return home / "agent-dispatcher" / "state-v1" / ("id-" + _digest({"identity": identity}))
    return private["state_directory"](project)


def provenance(record_id, kind, producer, method, version, *, repository=None, path=None, symbol=None, span=None,
               fingerprint=None, supports=(), snapshot=None, timestamp=None, status="current", invalidation=None, model=None):
    """One shape for every piece of repository knowledge, whatever produced it.

    `kind` says what a reader may make of it: an observation (a declaration exists, a commit
    touched a path), a derived structural or statistical fact (a resolved import target, a
    co-change score), a model inference (a subsystem responsibility), or task experience.
    """
    if kind not in EVIDENCE_KINDS:
        raise StoreError("Unknown evidence kind.")
    out = {"id": record_id, "kind": kind, "producer": producer, "method": method, "version": version,
           "repository": repository, "path": path, "symbol": symbol, "span": span, "fingerprint": fingerprint,
           "supports": list(supports), "snapshot": snapshot, "timestamp": timestamp, "status": status,
           "invalidation": invalidation}
    if model is not None:
        out["model"] = model
    return out


class _Base:
    """Hardened open: owner-only directory walk, regular 0600 file we own, rollback journal so
    a read-only open creates no side files."""

    file_name = None
    tables = ()

    def __init__(self, directory, *, create=False, readonly=False):
        self.directory = Path(directory)
        self.path = self.directory / self.file_name
        self.readonly = bool(readonly)
        self.connection = None
        self.created = False
        private = _sibling("parser_cache")
        try:
            with private["private_directory"](self.directory, create=create) as fd:
                try:
                    info = os.stat(self.file_name, dir_fd=fd, follow_symlinks=False)
                    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                        raise StoreError("Private index file is unsafe; left untouched.")
                except FileNotFoundError:
                    if not create:
                        raise StoreError("No repository index exists.") from None
                    handle = os.open(self.file_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                    os.close(handle)
                    self.created = True
        except FileNotFoundError:
            raise StoreError("No repository index exists.") from None
        except (OSError, ValueError) as exc:
            if isinstance(exc, StoreError):
                raise
            raise StoreError("Private state directory is unsafe or inaccessible.") from None
        uri = "file:" + str(self.path).replace("?", "%3f") + ("?mode=ro" if self.readonly else "?mode=rw")
        try:
            self.connection = sqlite3.connect(uri, uri=True, timeout=BUSY_MS / 1000, isolation_level=None)
            self.connection.execute("PRAGMA busy_timeout=%d" % BUSY_MS)
            if not self.readonly:
                self.connection.execute("PRAGMA journal_mode=DELETE")
                self.connection.execute("PRAGMA synchronous=NORMAL")
                self._migrate()
            else:
                self._check()
        except StoreError:
            self.close()  # A schema refusal is a StoreError, not a sqlite3.Error; the connection must not outlive it.
            raise
        except sqlite3.Error as exc:
            self.close()
            raise StoreError("Repository index is locked, corrupt or incompatible: " + type(exc).__name__) from None

    def _migrate(self):
        with self.transaction():
            for statement in self.tables:
                self.connection.execute(statement)
            row = self.connection.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
            if row is None:
                self.connection.execute("INSERT INTO meta(key, value) VALUES('schema', ?)", (str(SCHEMA),))
            elif row[0] != str(SCHEMA):
                raise StoreError("Repository index schema is incompatible; rebuild it.")

    def _check(self):
        try:
            row = self.connection.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        except sqlite3.Error:
            raise StoreError("Repository index is empty, corrupt or incompatible.") from None
        if row is None or row[0] != str(SCHEMA):
            raise StoreError("Repository index schema is incompatible; rebuild it.")

    @contextmanager
    def transaction(self):
        if self.readonly:
            raise StoreError("Store opened read-only.")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")

    def meta(self, key, default=None):
        row = self.connection.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row and key != "schema" else (row[0] if row else default)

    def set_meta(self, key, value):
        self.connection.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, json.dumps(value, sort_keys=True)))

    def integrity(self):
        try:
            return self.connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        except sqlite3.Error:
            return False

    def disk_bytes(self):
        try:
            return self.path.stat().st_size
        except OSError:
            return None

    def close(self):
        if self.connection is not None:
            try:
                self.connection.close()
            except sqlite3.Error:
                pass
            self.connection = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class IndexStore(_Base):
    """Deep repository index: inventory, records, corpus statistics, symbols, edges, history, inferences."""

    file_name = INDEX_FILE
    tables = (
        "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS generations(id INTEGER PRIMARY KEY, status TEXT NOT NULL, mode TEXT NOT NULL,"
        " started INTEGER NOT NULL, finished INTEGER, snapshot TEXT, coverage TEXT, policy TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, sha256 TEXT, signature TEXT, size INTEGER, lang TEXT,"
        " kind TEXT, status TEXT NOT NULL, reason TEXT, record TEXT, generation INTEGER NOT NULL, verified INTEGER)",
        "CREATE INDEX IF NOT EXISTS files_generation ON files(generation)",
        "CREATE TABLE IF NOT EXISTS terms(term TEXT PRIMARY KEY, df INTEGER NOT NULL)",
        "CREATE TABLE IF NOT EXISTS symbols(id TEXT PRIMARY KEY, path TEXT NOT NULL, name TEXT NOT NULL, qualname TEXT NOT NULL,"
        " kind TEXT NOT NULL, line INTEGER NOT NULL, end_line INTEGER NOT NULL, parent TEXT, fingerprint TEXT, status TEXT NOT NULL,"
        " generation INTEGER NOT NULL)",
        "CREATE INDEX IF NOT EXISTS symbols_path ON symbols(path)",
        "CREATE INDEX IF NOT EXISTS symbols_name ON symbols(name)",
        "CREATE TABLE IF NOT EXISTS symbol_aliases(id TEXT NOT NULL, alias_of TEXT NOT NULL, method TEXT NOT NULL, status TEXT NOT NULL,"
        " generation INTEGER NOT NULL, PRIMARY KEY(id, alias_of))",
        "CREATE TABLE IF NOT EXISTS edges(source TEXT NOT NULL, target TEXT NOT NULL, kind TEXT NOT NULL, method TEXT NOT NULL,"
        " status TEXT NOT NULL, detail TEXT, generation INTEGER NOT NULL, PRIMARY KEY(source, target, kind))",
        "CREATE INDEX IF NOT EXISTS edges_target ON edges(target)",
        "CREATE TABLE IF NOT EXISTS commits(sha TEXT PRIMARY KEY, stamp INTEGER NOT NULL, subject TEXT, paths TEXT NOT NULL,"
        " renames TEXT NOT NULL, touched INTEGER NOT NULL, position INTEGER NOT NULL)",
        "CREATE TABLE IF NOT EXISTS partners(path TEXT NOT NULL, other TEXT NOT NULL, score REAL NOT NULL, support INTEGER NOT NULL,"
        " PRIMARY KEY(path, other))",
        "CREATE TABLE IF NOT EXISTS inferences(id TEXT PRIMARY KEY, kind TEXT NOT NULL, producer TEXT NOT NULL, question TEXT,"
        " text TEXT NOT NULL, evidence TEXT NOT NULL, uncertainty TEXT, alternatives TEXT, status TEXT NOT NULL, reason TEXT,"
        " created INTEGER NOT NULL, model TEXT, generation INTEGER NOT NULL)",
    )

    # ---------------------------------------------------------------- generations

    def published(self):
        row = self.connection.execute("SELECT id, snapshot, coverage, policy, mode, started, finished FROM generations"
                                      " WHERE status='published' ORDER BY id DESC LIMIT 1").fetchone()
        return self._generation(row)

    def building(self):
        row = self.connection.execute("SELECT id, snapshot, coverage, policy, mode, started, finished FROM generations"
                                      " WHERE status='building' ORDER BY id DESC LIMIT 1").fetchone()
        return self._generation(row)

    @staticmethod
    def _generation(row):
        if row is None:
            return None
        return {"id": row[0], "snapshot": json.loads(row[1]) if row[1] else None, "coverage": json.loads(row[2]) if row[2] else None,
                "policy": row[3], "mode": row[4], "started": row[5], "finished": row[6]}

    def start_generation(self, policy, mode, snapshot):
        self.connection.execute("UPDATE generations SET status='abandoned', finished=? WHERE status='building'", (int(time.time()),))
        cursor = self.connection.execute("INSERT INTO generations(status, mode, started, snapshot, policy) VALUES('building', ?, ?, ?, ?)",
                                         (mode, int(time.time()), json.dumps(snapshot, sort_keys=True), policy))
        return cursor.lastrowid

    def update_generation(self, generation, *, snapshot=None, coverage=None):
        if snapshot is not None:
            self.connection.execute("UPDATE generations SET snapshot=? WHERE id=?", (json.dumps(snapshot, sort_keys=True), generation))
        if coverage is not None:
            self.connection.execute("UPDATE generations SET coverage=? WHERE id=?", (json.dumps(coverage, sort_keys=True), generation))

    def publish(self, generation, coverage, snapshot):
        """Atomic: one statement flips the new generation live and retires the previous one."""
        now = int(time.time())
        self.connection.execute("UPDATE generations SET status='superseded', finished=COALESCE(finished, ?) WHERE status='published'", (now,))
        self.connection.execute("UPDATE generations SET status='published', finished=?, coverage=?, snapshot=? WHERE id=?",
                                (now, json.dumps(coverage, sort_keys=True), json.dumps(snapshot, sort_keys=True), generation))
        self.connection.execute("DELETE FROM generations WHERE status='superseded' AND id NOT IN"
                                " (SELECT id FROM generations WHERE status='superseded' ORDER BY id DESC LIMIT 3)")

    def abandon(self, generation, coverage):
        self.connection.execute("UPDATE generations SET status='partial', finished=?, coverage=? WHERE id=?",
                                (int(time.time()), json.dumps(coverage, sort_keys=True), generation))

    # ---------------------------------------------------------------- files and corpus statistics

    def file_rows(self, paths=None, *, generation=None, with_record=False):
        columns = "path, sha256, signature, size, lang, kind, status, reason, generation, verified" + (", record" if with_record else "")
        if paths is None:
            if generation is None:
                rows = self.connection.execute(f"SELECT {columns} FROM files").fetchall()
            else:
                rows = self.connection.execute(f"SELECT {columns} FROM files WHERE generation=?", (generation,)).fetchall()
        else:
            rows = []
            paths = list(paths)
            for start in range(0, len(paths), 500):
                chunk = paths[start:start + 500]
                rows += self.connection.execute(f"SELECT {columns} FROM files WHERE path IN ({','.join('?' * len(chunk))})", chunk).fetchall()
        out = {}
        for row in rows:
            item = {"path": row[0], "sha256": row[1], "signature": json.loads(row[2]) if row[2] else None, "size": row[3],
                    "lang": row[4], "kind": row[5], "status": row[6], "reason": row[7], "generation": row[8], "verified": row[9]}
            if with_record:
                item["record"] = json.loads(row[10]) if row[10] else None
            out[row[0]] = item
        return out

    def records(self, hashes):
        """Records whose stored fingerprint equals the caller's current one: the only records a reader may use."""
        found = {}
        rows = self.file_rows(list(hashes), with_record=True)
        for path, row in rows.items():
            if row["status"] == "indexed" and row["record"] is not None and row["sha256"] == hashes[path]:
                found[path] = row["record"]
        return found

    def upsert_files(self, generation, rows):
        """Batch upsert. Never deletes: membership is reconciled separately, after a complete enumeration.

        Each row: {path, sha256, signature, size, lang, kind, status, reason, record}. Corpus term
        frequencies are kept exact by removing the old record's terms and adding the new one's.
        """
        delta = {}
        old = self.file_rows([row["path"] for row in rows], with_record=True)
        for row in rows:
            previous = old.get(row["path"])
            if previous and previous.get("record"):
                for term in previous["record"].get("terms", {}):
                    delta[term] = delta.get(term, 0) - 1
            record = row.get("record")
            if record:
                for term in record.get("terms", {}):
                    delta[term] = delta.get(term, 0) + 1
            self.connection.execute(
                "INSERT OR REPLACE INTO files(path, sha256, signature, size, lang, kind, status, reason, record, generation, verified)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (row["path"], row.get("sha256"), json.dumps(row.get("signature")) if row.get("signature") is not None else None,
                 row.get("size"), row.get("lang"), row.get("kind"), row["status"], row.get("reason"),
                 json.dumps(record, separators=(",", ":")) if record else None, generation, int(time.time())))
        self._apply_terms(delta)

    def touch(self, generation, paths, signatures=None):
        """Mark unchanged files as seen by this generation (and refresh their metadata signature)."""
        now = int(time.time())
        for path in paths:
            if signatures and path in signatures:
                self.connection.execute("UPDATE files SET generation=?, verified=?, signature=? WHERE path=?",
                                        (generation, now, json.dumps(signatures[path]), path))
            else:
                self.connection.execute("UPDATE files SET generation=?, verified=? WHERE path=?", (generation, now, path))

    def sweep(self, generation):
        """Remove rows an earlier generation left behind. Only valid after a complete enumeration."""
        stale = self.file_rows(generation=None, with_record=True)
        removed = [path for path, row in stale.items() if row["generation"] < generation]
        delta = {}
        for path in removed:
            record = stale[path].get("record") or {}
            for term in record.get("terms", {}):
                delta[term] = delta.get(term, 0) - 1
        self.delete_files(removed)
        self._apply_terms(delta)
        return removed

    def delete_files(self, paths):
        for start in range(0, len(paths), 500):
            chunk = paths[start:start + 500]
            marks = ",".join("?" * len(chunk))
            self.connection.execute(f"DELETE FROM files WHERE path IN ({marks})", chunk)
            self.connection.execute(f"DELETE FROM symbols WHERE path IN ({marks})", chunk)
            self.connection.execute(f"DELETE FROM edges WHERE source IN ({marks}) OR target IN ({marks})", chunk + chunk)
            self.connection.execute(f"DELETE FROM partners WHERE path IN ({marks}) OR other IN ({marks})", chunk + chunk)

    def _apply_terms(self, delta):
        for term, change in delta.items():
            if not change:
                continue
            self.connection.execute("INSERT INTO terms(term, df) VALUES(?, ?) ON CONFLICT(term) DO UPDATE SET df=df+excluded.df", (term, change))
        self.connection.execute("DELETE FROM terms WHERE df <= 0")

    def term_df(self, terms):
        out = {}
        terms = list(terms)
        for start in range(0, len(terms), 500):
            chunk = terms[start:start + 500]
            for term, df in self.connection.execute(f"SELECT term, df FROM terms WHERE term IN ({','.join('?' * len(chunk))})", chunk):
                out[term] = df
        return out

    def recount_terms(self):
        """Rebuild the corpus statistics from records; used to prove incremental bookkeeping stays exact."""
        counts = {}
        for row in self.connection.execute("SELECT record FROM files WHERE status='indexed' AND record IS NOT NULL"):
            for term in json.loads(row[0]).get("terms", {}):
                counts[term] = counts.get(term, 0) + 1
        return counts

    def stored_terms(self):
        return dict(self.connection.execute("SELECT term, df FROM terms").fetchall())

    # ---------------------------------------------------------------- symbols and edges

    def replace_symbols(self, generation, path, rows):
        self.connection.execute("DELETE FROM symbols WHERE path=?", (path,))
        self.connection.executemany(
            "INSERT OR REPLACE INTO symbols(id, path, name, qualname, kind, line, end_line, parent, fingerprint, status, generation)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(r["id"], path, r["name"], r["qualname"], r["kind"], r["line"], r["end_line"], r.get("parent"), r.get("fingerprint"),
              r.get("status", "current"), generation) for r in rows])

    def symbols(self, path=None, name=None, limit=200):
        query, args = "SELECT id, path, name, qualname, kind, line, end_line, parent, fingerprint, status FROM symbols", []
        if path is not None:
            query, args = query + " WHERE path=?", [path]
        elif name is not None:
            query, args = query + " WHERE name=? OR qualname=?", [name, name]
        rows = self.connection.execute(query + " ORDER BY path, line LIMIT ?", args + [limit]).fetchall()
        keys = ("id", "path", "name", "qualname", "kind", "line", "end_line", "parent", "fingerprint", "status")
        return [dict(zip(keys, row)) for row in rows]

    def search_symbols(self, needle, limit=50):
        pattern = "%" + needle.replace("%", "").replace("_", "\\_") + "%"
        rows = self.connection.execute("SELECT id, path, name, qualname, kind, line, end_line, parent, fingerprint, status FROM symbols"
                                       " WHERE name LIKE ? ESCAPE '\\' ORDER BY length(name), path, line LIMIT ?", (pattern, limit)).fetchall()
        keys = ("id", "path", "name", "qualname", "kind", "line", "end_line", "parent", "fingerprint", "status")
        return [dict(zip(keys, row)) for row in rows]

    def add_alias(self, generation, symbol_id, alias_of, method, status):
        self.connection.execute("INSERT OR REPLACE INTO symbol_aliases(id, alias_of, method, status, generation) VALUES(?,?,?,?,?)",
                                (symbol_id, alias_of, method, status, generation))

    def aliases(self, symbol_id=None):
        query, args = "SELECT id, alias_of, method, status FROM symbol_aliases", ()
        if symbol_id is not None:
            query, args = query + " WHERE id=? OR alias_of=?", (symbol_id, symbol_id)
        return [dict(zip(("id", "alias_of", "method", "status"), row)) for row in self.connection.execute(query, args)]

    def replace_edges(self, generation, edges, sources=None):
        """`edges`: rows {source, target, kind, method, status, detail}. With `sources`, only edges from those files are replaced."""
        if sources is None:
            self.connection.execute("DELETE FROM edges")
        else:
            sources = list(sources)
            for start in range(0, len(sources), 500):
                chunk = sources[start:start + 500]
                self.connection.execute(f"DELETE FROM edges WHERE source IN ({','.join('?' * len(chunk))})", chunk)
        self.connection.executemany(
            "INSERT OR REPLACE INTO edges(source, target, kind, method, status, detail, generation) VALUES(?,?,?,?,?,?,?)",
            [(e["source"], e["target"], e["kind"], e["method"], e["status"], str(e.get("detail", ""))[:240], generation) for e in edges])

    def edges_of(self, path, limit=200):
        rows = self.connection.execute("SELECT source, target, kind, method, status, detail FROM edges WHERE source=? OR target=?"
                                       " ORDER BY source, target, kind LIMIT ?", (path, path, limit)).fetchall()
        return [dict(zip(("source", "target", "kind", "method", "status", "detail"), row)) for row in rows]

    def edge_count(self):
        return self.connection.execute("SELECT count(*) FROM edges").fetchone()[0]

    # ---------------------------------------------------------------- history

    def replace_history(self, commits, partners, horizon):
        self.connection.execute("DELETE FROM commits")
        self.connection.execute("DELETE FROM partners")
        self.append_history(commits, partners, horizon, position=0)

    def append_history(self, commits, partners, horizon, position=None):
        if position is None:
            row = self.connection.execute("SELECT COALESCE(MAX(position), -1) FROM commits").fetchone()
            position = row[0] + 1
        self.connection.executemany(
            "INSERT OR REPLACE INTO commits(sha, stamp, subject, paths, renames, touched, position) VALUES(?,?,?,?,?,?,?)",
            [(c["sha"], c["stamp"], c.get("subject"), json.dumps(c["paths"]), json.dumps(c.get("renames", [])),
              -c["touched"] - 1 if c.get("capped") else c["touched"], position + n) for n, c in enumerate(commits)])
        self.connection.execute("DELETE FROM partners")
        self.connection.executemany("INSERT OR REPLACE INTO partners(path, other, score, support) VALUES(?,?,?,?)",
                                    [(path, other, score, support) for path, rows in partners.items() for other, score, support in rows])
        self.set_meta("history", horizon)

    def commits(self, limit=None):
        query = "SELECT sha, stamp, subject, paths, renames, touched FROM commits ORDER BY position"
        rows = self.connection.execute(query + (" LIMIT ?" if limit else ""), (limit,) if limit else ()).fetchall()
        return [{"sha": r[0], "stamp": r[1], "subject": r[2], "paths": json.loads(r[3]), "renames": json.loads(r[4]),
                 "touched": -r[5] - 1 if r[5] < 0 else r[5], "capped": r[5] < 0} for r in rows]

    def history_of(self, path, limit=20):
        rows = self.connection.execute("SELECT sha, stamp, subject, paths, renames FROM commits ORDER BY position").fetchall()
        found = []
        for sha, stamp, subject, paths, renames in rows:
            paths, renames = json.loads(paths), json.loads(renames)
            if path in paths or any(path in pair[:2] for pair in renames):
                found.append({"sha": sha, "stamp": stamp, "subject": subject, "touched": len(paths),
                              "renames": [pair for pair in renames if path in pair[:2]]})
                if len(found) >= limit:
                    break
        return found

    def partners_map(self):
        out = {}
        for path, other, score, support in self.connection.execute("SELECT path, other, score, support FROM partners ORDER BY path, score DESC, other"):
            out.setdefault(path, []).append([other, score, support])
        return out

    # ---------------------------------------------------------------- inferences

    def put_inference(self, generation, item):
        self.connection.execute(
            "INSERT OR REPLACE INTO inferences(id, kind, producer, question, text, evidence, uncertainty, alternatives, status, reason,"
            " created, model, generation) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (item["id"], item["kind"], item["producer"], item.get("question"), item["text"], json.dumps(item["evidence"]),
             item.get("uncertainty"), json.dumps(item.get("alternatives", [])), item.get("status", "current"), item.get("reason"),
             item.get("created", int(time.time())), json.dumps(item.get("model")) if item.get("model") is not None else None, generation))

    def inferences(self, status=None, limit=500):
        query, args = "SELECT id, kind, producer, question, text, evidence, uncertainty, alternatives, status, reason, created, model, generation FROM inferences", []
        if status is not None:
            query, args = query + " WHERE status=?", [status]
        rows = self.connection.execute(query + " ORDER BY created, id LIMIT ?", args + [limit]).fetchall()
        return [{"id": r[0], "kind": r[1], "producer": r[2], "question": r[3], "text": r[4], "evidence": json.loads(r[5]),
                 "uncertainty": r[6], "alternatives": json.loads(r[7] or "[]"), "status": r[8], "reason": r[9], "created": r[10],
                 "model": json.loads(r[11]) if r[11] else None, "generation": r[12]} for r in rows]

    def set_inference_status(self, ident, status, reason=None):
        self.connection.execute("UPDATE inferences SET status=?, reason=? WHERE id=?", (status, reason, ident))

    def delete_inferences(self, ids=None):
        if ids is None:
            self.connection.execute("DELETE FROM inferences")
            return
        self.connection.executemany("DELETE FROM inferences WHERE id=?", [(i,) for i in ids])

    def invalidate_inferences(self, current_hashes):
        """An inference whose cited evidence no longer matches the current source is stale, never silently kept."""
        changed = 0
        for item in self.inferences(status="current"):
            for evidence in item["evidence"]:
                path = evidence.get("path")
                if path and current_hashes.get(path) != evidence.get("sha256"):
                    self.set_inference_status(item["id"], "stale", "evidence changed: " + path)
                    changed += 1
                    break
        return changed

    # ---------------------------------------------------------------- counts

    def counts(self):
        return {"files": self.connection.execute("SELECT count(*) FROM files").fetchone()[0],
                "indexed": self.connection.execute("SELECT count(*) FROM files WHERE status='indexed'").fetchone()[0],
                "terms": self.connection.execute("SELECT count(*) FROM terms").fetchone()[0],
                "symbols": self.connection.execute("SELECT count(*) FROM symbols").fetchone()[0],
                "edges": self.edge_count(),
                "commits": self.connection.execute("SELECT count(*) FROM commits").fetchone()[0],
                "inferences": self.connection.execute("SELECT count(*) FROM inferences").fetchone()[0]}


class ExperienceStore(_Base):
    """Task experience events, corrections and forgetting; aggregates are recomputed from events on use."""

    file_name = EXPERIENCE_FILE
    tables = (
        "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, task_id TEXT NOT NULL, recorded INTEGER NOT NULL, outcome TEXT NOT NULL,"
        " status TEXT NOT NULL, superseded_by TEXT, record TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS events_task ON events(task_id)",
        "CREATE TABLE IF NOT EXISTS corrections(id INTEGER PRIMARY KEY, event_id TEXT NOT NULL, path TEXT, verdict TEXT NOT NULL,"
        " note TEXT, created INTEGER NOT NULL)",
    )

    def add_event(self, event):
        if self.connection.execute("SELECT 1 FROM events WHERE id=?", (event["id"],)).fetchone():
            return False
        self.connection.execute("INSERT INTO events(id, task_id, recorded, outcome, status, superseded_by, record) VALUES(?,?,?,?,?,?,?)",
                                (event["id"], event["task_id"], event["recorded"], event["outcome"], "current", None,
                                 json.dumps(event, separators=(",", ":"), sort_keys=True)))
        # Retention: the oldest current events beyond the cap are retired, never silently dropped from inspection.
        excess = self.connection.execute("SELECT id FROM events WHERE status='current' ORDER BY recorded DESC, id LIMIT -1 OFFSET ?",
                                         (MAX_EVENTS,)).fetchall()
        for (ident,) in excess:
            self.connection.execute("UPDATE events SET status='retired' WHERE id=?", (ident,))
        return True

    def events(self, *, status="current", task_id=None, limit=MAX_EVENTS):
        query, args = "SELECT record, status, superseded_by FROM events", []
        clauses = []
        if status is not None:
            clauses.append("status=?")
            args.append(status)
        if task_id is not None:
            clauses.append("task_id=?")
            args.append(task_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        rows = self.connection.execute(query + " ORDER BY recorded, id LIMIT ?", args + [limit]).fetchall()
        out = []
        for record, state, superseded in rows:
            item = json.loads(record)
            item["status"], item["superseded_by"] = state, superseded
            out.append(item)
        return out

    def get_event(self, ident):
        row = self.connection.execute("SELECT record, status, superseded_by FROM events WHERE id=?", (ident,)).fetchone()
        if row is None:
            return None
        item = json.loads(row[0])
        item["status"], item["superseded_by"] = row[1], row[2]
        return item

    def supersede(self, old, new):
        self.connection.execute("UPDATE events SET status='superseded', superseded_by=? WHERE id=?", (new, old))

    def forget(self, *, event_id=None, task_id=None):
        if event_id is not None:
            self.connection.execute("DELETE FROM corrections WHERE event_id=?", (event_id,))
            return self.connection.execute("DELETE FROM events WHERE id=?", (event_id,)).rowcount
        if task_id is not None:
            ids = [row[0] for row in self.connection.execute("SELECT id FROM events WHERE task_id=?", (task_id,))]
            for ident in ids:
                self.connection.execute("DELETE FROM corrections WHERE event_id=?", (ident,))
            return self.connection.execute("DELETE FROM events WHERE task_id=?", (task_id,)).rowcount
        self.connection.execute("DELETE FROM corrections")
        return self.connection.execute("DELETE FROM events").rowcount

    def correct(self, event_id, path, verdict, note):
        if self.connection.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone() is None:
            raise StoreError("Unknown experience event.")
        self.connection.execute("INSERT INTO corrections(event_id, path, verdict, note, created) VALUES(?,?,?,?,?)",
                                (event_id, path, verdict, note, int(time.time())))

    def corrections(self, event_id=None):
        query, args = "SELECT id, event_id, path, verdict, note, created FROM corrections", ()
        if event_id is not None:
            query, args = query + " WHERE event_id=?", (event_id,)
        return [dict(zip(("id", "event_id", "path", "verdict", "note", "created"), row))
                for row in self.connection.execute(query + " ORDER BY id", args)]

    def counts(self):
        rows = self.connection.execute("SELECT status, count(*) FROM events GROUP BY status").fetchall()
        return {"events": dict(rows), "corrections": self.connection.execute("SELECT count(*) FROM corrections").fetchone()[0]}
