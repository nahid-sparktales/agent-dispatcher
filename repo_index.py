"""Repository index: source-grounded facts, with no task and no retrieval scores.

Built only from the texts the context scan already admitted (after exclusion, credential
and size rules, and redaction), so nothing an excluded file contains or is named can be
reached through a symbol, an edge or history. Per-file records are a pure function of one
file, which is what makes the index incremental: a changed file recomputes one record and
resolution (imports, references, tests) is cheap dictionary work over all records.

Python uses `ast`; every other language falls back to declaration regexes and simply knows
less (no calls, no inheritance). Unknown relationships stay unknown.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import PurePosixPath
import re
import warnings

SCHEMA = 1
SHARDS = 16  # Record cache granularity: one changed file rewrites 1/16 of the cached records.
MAX_DEFS = 2000
MAX_CALLS = 1500
MAX_TERMS = 20000
MAX_DEF_FILES = 3  # A name defined in more files than this is too ambiguous to be an edge.
MAX_PARTNERS = 10  # Co-change partners kept per file.
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,79}")
CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
GENERIC_DEF = re.compile(
    r"^([ \t]*)(?:(?:export|default|declare|async|public|private|protected|static|abstract|final|unsafe|extern|pub(?:\([a-z]+\))?)\s+)*"
    r"(function\*?|class|interface|type|enum|struct|trait|impl|fn|func|def|module|namespace|const|let|var)\s+"
    r"(?:\([^)\n]*\)\s*)?([A-Za-z_$][\w$]*)", re.M)
JS_IMPORT = re.compile(r"(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)['\"](\.{1,2}/[^'\"\n]+|\.{1,2})['\"]")
JS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
_EXPANSIONS = {}


def normalize(term):
    """Lowercase plus a plural fold, applied identically to documents and queries."""
    term = term.lower()
    if len(term) > 4 and term.endswith("ies"):
        return term[:-3] + "y"
    if len(term) > 3 and term.endswith("s") and not term.endswith(("ss", "us", "is")):
        return term[:-1]
    return term


def expand(identifier):
    """`execute_table` -> exact `execute_table` plus `execute`, `table`; `QueryPlanner` likewise."""
    cached = _EXPANSIONS.get(identifier)
    if cached is None:
        parts = [normalize(p) for chunk in identifier.split("_") for p in CAMEL.findall(chunk) if len(p) > 1]
        compound = len(parts) > 1 or any(c.isupper() for c in identifier)
        cached = _EXPANSIONS[identifier] = tuple(dict.fromkeys(([identifier] if compound else []) + parts))
        if len(_EXPANSIONS) > 200000:
            _EXPANSIONS.clear()
    return cached


def is_test(path):
    pure = PurePosixPath(path)
    return bool({"tests", "test", "__tests__", "testing"} & set(pure.parts[:-1])
                or re.search(r"(?:^test[_-]|[_-]test\.|\.(?:test|spec)\.|^conftest\.py$)", pure.name))


def test_stem(path):
    name = PurePosixPath(path).name.split(".")[0]
    return re.sub(r"^test[_-]|[_-]test$", "", name).lower()


def _python_facts(text):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tree = ast.parse(text)
    defs, imports, calls, bases = [], [], set(), []
    pending = [(node, "", False) for node in reversed(tree.body)]
    while pending:
        node, parent, in_class = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.append([node.name, "method" if in_class else "function", node.lineno, node.end_lineno or node.lineno, parent])
        elif isinstance(node, ast.ClassDef):
            defs.append([node.name, "class", node.lineno, node.end_lineno or node.lineno, parent])
            for base in node.bases:
                name = base.attr if isinstance(base, ast.Attribute) else base.id if isinstance(base, ast.Name) else None
                if name:
                    bases.append([node.name, name, node.lineno])
            pending.extend((child, node.name, True) for child in reversed(node.body))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                if isinstance(target, ast.Name) and target.id.isupper() and len(target.id) > 2:
                    defs.append([target.id, "constant", node.lineno, node.end_lineno or node.lineno, parent])
        elif isinstance(node, (ast.If, ast.Try)) and not in_class:
            pending.extend((child, parent, in_class) for child in reversed(node.body))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else None
            if name and len(name) > 2:
                calls.add(name)
        elif isinstance(node, ast.Import):
            imports.extend([alias.name, 0, [], node.lineno] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append([node.module or "", node.level, [alias.name for alias in node.names][:40], node.lineno])
    return defs, imports, sorted(calls), bases


def _generic_facts(path, text):
    defs = []
    for match in GENERIC_DEF.finditer(text):
        indent, keyword, name = match.groups()
        if keyword in {"const", "let", "var"}:
            if indent:
                continue  # Locals are not addressable symbols.
            line_end = text.find("\n", match.end())
            rest = text[match.end():line_end if line_end >= 0 else len(text)]
            kind = "function" if "=>" in rest or "function" in rest else "constant"
        else:
            kind = "function" if keyword.rstrip("*") in {"function", "fn", "func", "def"} else "class"
        line = text.count("\n", 0, match.start(3)) + 1
        defs.append([name, "method" if indent and kind == "function" else kind, line, line, ""])
    imports = []
    if path.endswith(JS_SUFFIXES) or path.endswith((".vue", ".svelte")):
        for match in JS_IMPORT.finditer(text):
            imports.append([match.group(1), -1, [], text.count("\n", 0, match.start()) + 1])
    return defs, imports, [], []


def file_record(path, text):
    """Everything the index knows about one file; depends on nothing but this file."""
    counts = Counter(IDENT.findall(text))
    terms = Counter()
    for identifier, count in counts.items():
        for term in expand(identifier):
            terms[term] += count
    if len(terms) > MAX_TERMS:
        terms = Counter(dict(terms.most_common(MAX_TERMS)))
    language, facts = "other", None
    if path.endswith(".py"):
        language = "python"
        try:
            facts = _python_facts(text)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            language = "python-unparsed"
    if facts is None:
        facts = _generic_facts(path, text)
    defs, imports, calls, bases = facts
    return {"v": SCHEMA, "lang": language, "len": sum(counts.values()), "lines": text.count("\n") + 1,
            "terms": dict(terms), "defs": defs[:MAX_DEFS], "imports": imports[:400],
            "calls": calls[:MAX_CALLS], "bases": bases[:400]}


def _shard(path):
    return int(hashlib.sha256(path.encode("utf-8")).hexdigest()[:4], 16) % SHARDS


def load_records(texts, hashes, cache=None, stats=None):
    """Reuse a record whose source fingerprint is unchanged; recompute only the rest.

    `cache` is anything with get(kind, key)/put(kind, key, value): the private parser cache
    in production, a dict-backed memo in the benchmark. Shards are JSON strings so the cache's
    defensive copies stay cheap. Only paths in `texts` are ever looked up or written back.
    """
    stats = stats if stats is not None else {}
    stats.update(record_hits=0, record_misses=0)
    shards, dirty, records = {}, set(), {}
    for path, text in texts.items():
        number = _shard(path)
        if number not in shards:
            stored = cache.get("index-shard", [SCHEMA, number]) if cache is not None else None
            try:
                shards[number] = json.loads(stored) if isinstance(stored, str) else {}
            except ValueError:
                shards[number] = {}
        entry = shards[number].get(path)
        if (isinstance(entry, list) and len(entry) == 2 and entry[0] == hashes[path]
                and isinstance(entry[1], dict) and entry[1].get("v") == SCHEMA):
            records[path] = entry[1]
            stats["record_hits"] += 1
            continue
        records[path] = file_record(path, text)
        shards[number][path] = [hashes[path], records[path]]
        dirty.add(number)
        stats["record_misses"] += 1
    if cache is not None:
        for number, shard in shards.items():
            live = {path: entry for path, entry in shard.items() if path in texts}
            if number in dirty or len(live) != len(shard):
                cache.put("index-shard", [SCHEMA, number], json.dumps(live, separators=(",", ":")))
    return records


def parse_git_log(raw, universe, max_commit_files):
    """`git log --name-only --format=%x01%ct` -> [(timestamp, [paths])], universe paths only.

    Filtering happens before anything is counted: a path outside the retrieval universe never
    contributes to, or appears in, any co-change statistic.
    """
    commits = []
    for block in raw.split("\x01")[1:]:
        lines = block.split("\n")
        try:
            stamp = int(lines[0].strip())
        except ValueError:
            continue
        paths = sorted({line for line in lines[1:] if line in universe})
        if 2 <= len(paths) <= max_commit_files:
            commits.append((stamp, paths))
    return commits


def cochange(commits, *, min_support, half_life_days=None):
    """Jaccard co-change: commits touching both / commits touching either.

    Jaccard normalizes both sides, so a high-churn file does not look related to everything
    the way raw counts or P(B|A) would make it. `min_support` drops coincidences. With a
    half-life, each commit counts 0.5 ** (age / half_life) relative to the newest commit.
    """
    newest = max((stamp for stamp, _ in commits), default=0)
    changes, pairs, support = Counter(), Counter(), Counter()
    for stamp, paths in commits:
        weight = 0.5 ** ((newest - stamp) / 86400 / half_life_days) if half_life_days else 1.0
        for path in paths:
            changes[path] += weight
        for i, first in enumerate(paths):
            for second in paths[i + 1:]:
                pairs[first, second] += weight
                support[first, second] += 1
    partners = defaultdict(list)
    for (first, second), both in pairs.items():
        if support[first, second] < min_support:
            continue
        score = both / (changes[first] + changes[second] - both)
        partners[first].append([second, round(score, 4), support[first, second]])
        partners[second].append([first, round(score, 4), support[first, second]])
    return {path: sorted(rows, key=lambda row: (-row[1], -row[2], row[0]))[:MAX_PARTNERS]
            for path, rows in partners.items()}


class RepoIndex:
    """Facts assembled from per-file records. Queryable; knows nothing about any task."""

    def __init__(self, records, kind_of, partners=None, path_only=()):
        self.records = records
        self.path_only = set(path_only) - set(records)  # Known files whose content was not indexed.
        self.paths = sorted(set(records) | self.path_only)
        self.kinds = {path: ("test" if is_test(path) else kind_of(path)) for path in self.paths}
        self.size = max(1, len(records))
        self.average_length = sum(r["len"] for r in records.values()) / self.size or 1.0
        self._df = {}
        known = set(self.paths)
        self.partners = {path: [row for row in rows if row[0] in known]
                         for path, rows in (partners or {}).items() if path in known}
        self.path_parts, self.path_df = {}, Counter()
        for path in self.paths:
            pure = PurePosixPath(path)
            stem = pure.name.split(".")[0]
            stem_tokens = {normalize(stem)} | set(expand(stem)) | ({test_stem(path)} if is_test(path) else set())
            directory_tokens = {t for part in pure.parts[:-1] for t in (normalize(part), *expand(part))}
            self.path_parts[path] = (normalize(test_stem(path) if is_test(path) else stem), stem_tokens, directory_tokens)
            self.path_df.update(stem_tokens | directory_tokens)
        self.definitions = defaultdict(list)
        for path, record in records.items():
            for name, kind, line, end, parent in record["defs"]:
                self.definitions[name].append((path, line, end, kind, parent))
        self.lower_definitions = defaultdict(set)
        for name in self.definitions:
            self.lower_definitions[name.lower()].add(name)
        # Dotted names for every language (`pkg.mod` -> pkg/mod.ts too); Python wins a collision
        # because only Python import resolution depends on exactness.
        self.modules, suffixes = {}, defaultdict(set)
        for path in sorted(self.paths, key=lambda p: (not p.endswith(".py"), p)):
            pure = PurePosixPath(path)
            parts = list(pure.parts[:-1]) + [pure.name.split(".")[0]]
            if parts[-1] in {"__init__", "index", "mod"}:
                parts.pop()
            if parts and all(IDENT.fullmatch(part) or len(part) == 1 for part in parts):
                self.modules.setdefault(".".join(parts), path)
                for start in range(1, len(parts)):
                    suffixes[".".join(parts[start:])].add(path)
        self.module_suffixes = {name: sorted(found) for name, found in suffixes.items()}
        self.edges = defaultdict(lambda: defaultdict(dict))
        self._resolve_edges()
        self.reverse, self.in_degree = defaultdict(dict), Counter()
        for start, targets in self.edges.items():
            for end, kinds in targets.items():
                self.reverse[end][start] = kinds
                if {"imports", "references", "calls", "inherits"} & set(kinds):
                    self.in_degree[end] += 1

    def df(self, term):
        if term not in self._df:
            self._df[term] = sum(1 for record in self.records.values() if term in record["terms"])
        return self._df[term]

    def idf(self, term):
        """Continuous rarity, always positive: a term in every file is worth almost nothing (never a
        cliff, and a three-file project still retrieves), a term in one file is worth most."""
        found = self.df(term)
        return math.log(1 + (self.size - found + 0.5) / (found + 0.5))

    def path_idf(self, token):
        found = self.path_df.get(token, 0)
        return math.log(1 + (len(self.paths) - found + 0.5) / (found + 0.5))

    def module_path(self, dotted):
        """`pkg.mod` -> file, by exact module name, else a unique path suffix (`src/pkg/mod.py`)."""
        if dotted in self.modules:
            return self.modules[dotted]
        found = self.module_suffixes.get(dotted, ())
        return found[0] if len(found) == 1 else None

    def _edge(self, start, end, kind, detail):
        if start != end and (end in self.records or end in self.path_only):
            self.edges[start][end].setdefault(kind, detail)

    def _resolve_edges(self):
        for path, record in self.records.items():
            parent = PurePosixPath(path).parent
            package = list(parent.parts)
            for spec, level, names, line in record["imports"]:
                if level < 0:  # Relative JS/TS specifier.
                    base = (parent / spec).as_posix()
                    parts = []
                    for part in base.split("/"):
                        if part == "..":
                            if not parts:
                                break
                            parts.pop()
                        elif part not in {".", ""}:
                            parts.append(part)
                    else:
                        joined = "/".join(parts)
                        options = [joined] + [joined + s for s in JS_SUFFIXES] + [joined + "/index" + s for s in JS_SUFFIXES]
                        target = next((o for o in options if o in self.records or o in self.path_only), None)
                        if target:
                            self._edge(path, target, "imports", line)
                    continue
                if level:
                    if level - 1 > len(package):
                        continue
                    spec = ".".join(package[:len(package) - level + 1] + ([spec] if spec else []))
                # `from pkg import mod` targets the submodule; only otherwise the package or module itself.
                targets = {self.module_path(spec + "." + name) for name in names if name != "*"} - {None} if spec else set()
                if not targets and spec:
                    targets = {self.module_path(spec)}
                for target in sorted(t for t in targets if t):
                    self._edge(path, target, "imports", line)
            own = {row[0] for row in record["defs"]}  # A name this file defines resolves here, not elsewhere.
            for kind, names in (("calls", record["calls"]), ("references", record["terms"])):
                for name in names:
                    found = self.definitions.get(name) if name not in own else None
                    # Short all-lowercase names collide with ordinary words and subtokens.
                    if not found or not (len(name) > 4 or any(c.isupper() or c == "_" for c in name)):
                        continue
                    files = {row[0] for row in found if row[3] != "method" or kind == "calls"}
                    if 0 < len(files) <= MAX_DEF_FILES:
                        for target in files:
                            self._edge(path, target, kind, name)
            for _, base, _ in record["bases"]:
                files = {row[0] for row in self.definitions.get(base, ()) if row[3] == "class"}
                if 0 < len(files) <= MAX_DEF_FILES:
                    for target in files:
                        self._edge(path, target, "inherits", base)
        by_stem = defaultdict(list)
        for path in self.records:
            if self.kinds[path] == "source":
                by_stem[normalize(PurePosixPath(path).name.split(".")[0])].append(path)
        for path in self.records:
            if is_test(path):
                named = by_stem.get(normalize(test_stem(path)), ())
                imported = [t for t, kinds in self.edges.get(path, {}).items() if "imports" in kinds and self.kinds[t] == "source"]
                for target in set(named) | set(imported):
                    self._edge(target, path, "tested_by", "test name" if target in named else "test import")

    def neighbors(self, path):
        """(other, kind, detail) in both directions. Reverse kinds are named from `path`'s side."""
        reverse = {"imports": "imported_by", "calls": "called_by", "references": "referenced_by",
                   "inherits": "inherited_by", "tested_by": "tests"}
        rows = [(other, kind, detail) for other, kinds in self.edges.get(path, {}).items() for kind, detail in kinds.items()]
        rows.extend((other, reverse[kind], detail) for other, kinds in self.reverse.get(path, {}).items()
                    for kind, detail in kinds.items())
        return sorted(rows, key=lambda row: (row[0], row[1]))

    def same_directory(self, path):
        parent = PurePosixPath(path).parent
        return [other for other in self.records
                if other != path and PurePosixPath(other).parent == parent and not is_test(other)]

    def symbols_in(self, path):
        return [row[0] for row in self.records[path]["defs"]] if path in self.records else []

    def referencing(self, name):
        """Files that mention `name` as an identifier without defining it."""
        defining = {row[0] for row in self.definitions.get(name, ())}
        return {path: record["terms"][name] for path, record in self.records.items()
                if name in record["terms"] and path not in defining}
