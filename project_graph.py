#!/usr/bin/env python3
"""Bounded structural evidence from the context selector's already-read sources.

Python AST resolution describes static declarations, not runtime dispatch or test
coverage. This helper never scans, imports project modules, or executes sources.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict, deque
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from types import SimpleNamespace
import warnings

OWNER = "agent-dispatcher-project-graph"
SCHEMA_VERSION = 1
STATE_FILE = "project-graph.json"
MAX_BYTES = 256 * 1024
MAX_SOURCES = 80
MAX_NODES = 240
MAX_EDGES = 400
MAX_VIEW_CHARS = 5900  # Reserve space for the final token-estimate field.
NODE_KINDS = {"file", "function", "class"}
EDGE_METHODS = {"contains": {"file-membership", "python-ast-definition"},
                "imports": {"python-ast-import", "relative-import-regex"},
                "calls": {"python-ast-direct-call"},
                "test_candidate": {"test-name-and-import"}}


class GraphError(ValueError):
    pass


def _map_helper():
    path = Path(__file__).resolve().with_name("project_map.py")
    namespace = {"__name__": "_dispatcher_graph_map", "__file__": str(path)}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    return SimpleNamespace(**namespace)


def _id(*parts):
    return hashlib.sha256("\0".join(map(str, parts)).encode()).hexdigest()[:20]


def _source(path, line=1):
    return {"path": path, "line": line}


def _walk_scope(node):
    """Visit one lexical scope, excluding bodies/decorators of nested definitions."""
    pending = list(reversed(node.body))
    while pending:
        child = pending.pop()
        yield child
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            pending.extend(reversed(list(ast.iter_child_nodes(child))))


def _bindings(node):
    names = Counter()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for argument in ast.walk(node.args):
            if isinstance(argument, ast.arg):
                names[argument.arg] += 1
    for child in _walk_scope(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names[child.name] += 1
        elif isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            names[child.id] += 1
        elif isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                names[alias.asname or (alias.name.split(".")[0] if isinstance(child, ast.Import) else alias.name)] += 1
        elif isinstance(child, ast.ExceptHandler) and child.name:
            names[child.name] += 1
    return names


def _module(path):
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _import_base(path, node):
    if not node.level:
        return node.module or ""
    package = _module(path).split(".")
    if PurePosixPath(path).name != "__init__.py":
        package = package[:-1]
    if node.level > len(package):
        return None
    package = package[:len(package) - node.level + 1]
    return ".".join(package + ([node.module] if node.module else []))


def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return base + "." + node.attr if base else None
    return None


def _test_file(path):
    name = PurePosixPath(path).name
    return bool(re.search(r"(?:^test[_-]|[_-]test\.|\.(?:test|spec)\.)", name) or
                {"test", "tests", "__tests__"} & set(PurePosixPath(path).parts[:-1]))


def derive_graph(snapshot, helper, scrub):
    """Pure bounded extraction from redacted text. Missing facts stay unknown."""
    context = helper._context()
    paths = sorted(path for path in snapshot["texts"]
                   if helper._safe_path(path) and scrub(path) == path
                   and not context._skip(path))
    paths.sort(key=lambda path: (0 if path.endswith(".py") else 1 if context._kind(path) in {"source", "test"} else 2, path))
    # Caller exclusions remain an enforced no-use boundary even with a supplied
    # snapshot; no fallback opens excluded files to resolve a relationship.
    paths = [p for p in paths if not context._excluded(p, snapshot.get("exclude_paths", ()))][:MAX_SOURCES]
    sources = [{"path": p, "sha256": snapshot["hashes"][p]} for p in paths]
    nodes, edges, node_ids, edge_keys = [], [], set(), set()
    omitted = {"sources": max(0, len(snapshot["texts"]) - len(paths)), "nodes": 0, "edges": 0,
               "unresolved_calls": 0, "parse_failures": 0}

    def node(kind, label, path, line=1, qualifier=""):
        identity = _id(kind, path, qualifier, line)
        if identity in node_ids:
            return identity
        if len(nodes) >= MAX_NODES:
            omitted["nodes"] += 1
            return None
        nodes.append({"id": identity, "kind": kind, "label": label[:120], "source": _source(path, line)})
        node_ids.add(identity)
        return identity

    def edge(start, end, kind, path, line, method, confidence="resolved"):
        if not start or not end or start == end:
            return
        key = (start, end, kind, path, line)
        if key in edge_keys:
            return
        if len(edges) >= MAX_EDGES:
            omitted["edges"] += 1
            return
        edges.append({"from": start, "to": end, "kind": kind, "confidence": confidence,
                      "method": method, "evidence": _source(path, line)})
        edge_keys.add(key)

    files = {p: node("file", PurePosixPath(p).name, p) for p in paths}
    modules = defaultdict(list)
    trees, functions, definitions = {}, {}, {}
    for path in paths:
        if not path.endswith(".py"):
            continue
        modules[_module(path)].append(path)
        try:
            # Parser warnings can include repository source snippets on stderr.
            # Treat warnings as opaque parsing detail, not another output path.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                trees[path] = ast.parse(snapshot["texts"][path])
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            omitted["parse_failures"] += 1
            continue
        functions[path] = []
        definitions[path] = {}
        pending = [(child, files[path], "") for child in reversed(trees[path].body)]
        while pending:
            child, parent, prefix = pending.pop()
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualname = prefix + child.name
                kind = "class" if isinstance(child, ast.ClassDef) else "function"
                symbol = node(kind, qualname, path, child.lineno, qualname)
                edge(parent, symbol, "contains", path, child.lineno, "python-ast-definition")
                if not prefix and kind == "function":
                    definitions[path][child.name] = symbol
                # Nested scopes, bound methods and dynamic dispatch remain
                # definition locations, without speculative call resolution.
                if kind == "function" and symbol and not prefix:
                    functions[path].append((child, symbol))
                pending.extend((nested, symbol, qualname + ".") for nested in reversed(child.body))
            elif hasattr(child, "body") and isinstance(child.body, list):
                pending.extend((nested, parent, prefix) for nested in reversed(child.body))

    def local_module(name):
        candidates = modules.get(name, ())
        return candidates[0] if len(candidates) == 1 else None

    module_bindings_by_path = {path: _bindings(tree) for path, tree in trees.items()}
    attribute_writes = {path: {_dotted(child) for child in ast.walk(tree)
                              if isinstance(child, ast.Attribute) and isinstance(child.ctx, (ast.Store, ast.Del))}
                        for path, tree in trees.items()}
    global_writes = {}
    for path, tree in trees.items():
        rebound = set()
        for scope in ast.walk(tree):
            if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                declared = {name for child in _walk_scope(scope) if isinstance(child, ast.Global) for name in child.names}
                rebound.update(declared & _bindings(scope).keys())
        global_writes[path] = rebound
    wildcard_modules = {path for path, tree in trees.items()
                        if any(isinstance(child, ast.ImportFrom) and any(alias.name == "*" for alias in child.names)
                               for child in _walk_scope(tree))}
    for path, tree in trees.items():
        module_bindings = module_bindings_by_path[path]
        imports, imported_functions = {}, {}
        # Every import is structural evidence; only top-level bindings can be
        # used to resolve a global call from the supported callable scopes.
        top_level = {id(child) for child in tree.body}
        for child in ast.walk(tree):
            if isinstance(child, ast.Import):
                rows = [(alias, alias.name, None) for alias in child.names]
            elif isinstance(child, ast.ImportFrom):
                base = _import_base(path, child)
                rows = [(alias, base, alias.name) for alias in child.names] if base is not None else []
            else:
                continue
            for alias, module, member in rows:
                target = local_module(module)
                # `from package import module` can name a submodule instead of
                # a callable; resolve only when the snapshot has that module.
                submodule = local_module(module + "." + member) if member and member != "*" else None
                package_has_no_member = (target in trees and PurePosixPath(target).name == "__init__.py"
                                         and not module_bindings_by_path[target][member]
                                         and member not in global_writes[target]
                                         and "__getattr__" not in module_bindings_by_path[target]
                                         and target not in wildcard_modules)
                if submodule and (not target or package_has_no_member):
                    target, member = submodule, None
                if not target:
                    continue
                edge(files[path], files[target], "imports", path, child.lineno, "python-ast-import")
                if _test_file(path):
                    edge(files[path], files[target], "test_candidate", path, child.lineno,
                         "test-name-and-import", "inferred")
                if alias.name == "*" or id(child) not in top_level:
                    continue
                if member is None:
                    imports[alias.asname or alias.name] = target
                else:
                    imported_functions[alias.asname or alias.name] = (target, member)
        for function, identity in functions[path]:
            local_bindings = _bindings(function)
            wildcard = path in wildcard_modules or any(
                isinstance(child, ast.ImportFrom) and any(alias.name == "*" for alias in child.names)
                for child in _walk_scope(function))
            for child in _walk_scope(function):
                if not isinstance(child, ast.Call):
                    continue
                name = _dotted(child.func)
                target, member = None, None
                if (not wildcard and name and name.split(".")[0] not in local_bindings
                        and name.split(".")[0] not in global_writes[path]):
                    if "." not in name and module_bindings[name] == 1:
                        if name in definitions[path]:
                            target, member = path, name
                        elif name in imported_functions:
                            target, member = imported_functions[name]
                    elif "." in name:
                        prefix, member = name.rsplit(".", 1)
                        parts = name.split(".")
                        # An attribute assignment anywhere in this module can
                        # replace this target before a later call. Do not turn
                        # the original declaration into a claimed call target.
                        rebound = any(".".join(parts[:end]) in attribute_writes[path] for end in range(2, len(parts) + 1))
                        if not rebound and prefix in imports and module_bindings[prefix.split(".")[0]] == 1:
                            target = imports[prefix]
                destination = definitions.get(target, {}).get(member)
                # A callee's own module must not redefine or reassign its name.
                if (destination and target not in wildcard_modules and member not in global_writes[target]
                        and module_bindings_by_path[target][member] == 1):
                    edge(identity, destination, "calls", path, child.lineno, "python-ast-direct-call")
                else:
                    omitted["unresolved_calls"] += 1

    # Other supported files contribute only literal relative import candidates.
    # Regex evidence deliberately never participates in execution-path queries.
    extensions = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
    for path in paths:
        if not path.endswith(extensions):
            continue
        for number, line in enumerate(snapshot["texts"][path].splitlines(), 1):
            match = re.match(r"\s*(?:import\b.*?\bfrom\s*|import\s*|export\b.*?\bfrom\s*)['\"](\.[^'\"]+)['\"]", line)
            if not match:
                continue
            parts = list(PurePosixPath(path).parent.parts)
            for part in PurePosixPath(match.group(1)).parts:
                if part == "..":
                    if parts:
                        parts.pop()
                    else:
                        parts = []
                        break
                elif part != ".":
                    parts.append(part)
            base = "/".join(parts)
            candidates = [candidate for candidate in [base] + [base + ext for ext in extensions] +
                          [base + "/index" + ext for ext in extensions] if candidate in files]
            if len(candidates) == 1:
                target = candidates[0]
                edge(files[path], files[target], "imports", path, number, "relative-import-regex", "inferred")
                if _test_file(path):
                    edge(files[path], files[target], "test_candidate", path, number, "test-name-and-import", "inferred")
    scan = helper._scan_record(snapshot)
    data = {"owner": OWNER, "schema_version": SCHEMA_VERSION, "scan": scan,
            "sources": sources, "nodes": nodes, "edges": edges, "omitted": omitted}
    return _valid_graph(data)


def _valid_graph(data):
    """Validate structure, size, references, evidence, and extraction vocabulary."""
    if (not isinstance(data, dict) or set(data) != {"owner", "schema_version", "scan", "sources", "nodes", "edges", "omitted"}
            or data.get("owner") != OWNER or type(data.get("schema_version")) is not int
            or data["schema_version"] != SCHEMA_VERSION):
        raise GraphError("Unsupported graph cache; existing state left untouched.")
    helper = _map_helper()
    scan = data["scan"]
    if (not isinstance(scan, dict) or set(scan) != {"complete", "files", "readable_files", "bytes", "path_fingerprint", "content_fingerprint"}
            or type(scan["complete"]) is not bool
            or any(type(scan[k]) is not int or scan[k] < 0 for k in ("files", "readable_files", "bytes"))
            or any(not isinstance(scan[k], str) or not helper.HEX.fullmatch(scan[k]) for k in ("path_fingerprint", "content_fingerprint"))):
        raise GraphError("Invalid graph scan metadata.")
    if (not isinstance(data["sources"], list) or len(data["sources"]) > MAX_SOURCES
            or not isinstance(data["nodes"], list) or len(data["nodes"]) > MAX_NODES
            or not isinstance(data["edges"], list) or len(data["edges"]) > MAX_EDGES):
        raise GraphError("Graph exceeds its bounded limits.")
    sources = {}
    for source in data["sources"]:
        if (not isinstance(source, dict) or set(source) != {"path", "sha256"}
                or not helper._safe_path(source["path"]) or source["path"] in sources
                or not isinstance(source["sha256"], str) or not helper.HEX.fullmatch(source["sha256"])):
            raise GraphError("Invalid graph source fingerprint.")
        sources[source["path"]] = source["sha256"]

    def evidence(value):
        return (isinstance(value, dict) and set(value) == {"path", "line"}
                and isinstance(value["path"], str) and value["path"] in sources
                and type(value["line"]) is int and 1 <= value["line"] <= 262144)

    ids = set()
    kinds = {}
    for node in data["nodes"]:
        if (not isinstance(node, dict) or set(node) != {"id", "kind", "label", "source"}
                or not isinstance(node["id"], str) or not re.fullmatch(r"[a-f0-9]{20}", node["id"])
                or node["id"] in ids or node["kind"] not in NODE_KINDS
                or not isinstance(node["label"], str) or not 0 < len(node["label"]) <= 120
                or any(ord(char) < 32 or ord(char) == 127 for char in node["label"])
                or not evidence(node["source"])):
            raise GraphError("Invalid graph node.")
        ids.add(node["id"])
        kinds[node["id"]] = node["kind"]
    keys = set()
    for edge in data["edges"]:
        if (not isinstance(edge, dict) or set(edge) != {"from", "to", "kind", "confidence", "method", "evidence"}
                or edge["from"] not in ids or edge["to"] not in ids or edge["from"] == edge["to"]
                or edge["kind"] not in EDGE_METHODS or edge["method"] not in EDGE_METHODS[edge["kind"]]
                or edge["confidence"] not in {"resolved", "inferred"} or not evidence(edge["evidence"])
                or (edge["method"] in {"relative-import-regex", "test-name-and-import"} and edge["confidence"] != "inferred")
                or (edge["kind"] == "calls" and (edge["confidence"] != "resolved" or kinds[edge["from"]] != "function"
                                                or kinds[edge["to"]] != "function"))
                or (edge["kind"] in {"imports", "test_candidate"} and
                    (kinds[edge["from"]] != "file" or kinds[edge["to"]] != "file"))):
            raise GraphError("Invalid graph relationship.")
        key = (edge["from"], edge["to"], edge["kind"], edge["evidence"]["path"], edge["evidence"]["line"])
        if key in keys:
            raise GraphError("Duplicate graph relationship.")
        keys.add(key)
    if (not isinstance(data["omitted"], dict) or set(data["omitted"]) !=
            {"sources", "nodes", "edges", "unresolved_calls", "parse_failures"}
            or any(type(n) is not int or n < 0 for n in data["omitted"].values())):
        raise GraphError("Invalid graph coverage metadata.")
    return data


def _reach(seeds, adjacency, depth=2):
    distances = {seed: 0 for seed in seeds}
    queue = deque(seeds)
    while queue:
        current = queue.popleft()
        if distances[current] >= depth:
            continue
        for following in sorted(adjacency.get(current, ())):
            if following not in distances:
                distances[following] = distances[current] + 1
                queue.append(following)
    return [identity for identity, distance in sorted(distances.items(), key=lambda row: (row[1], row[0])) if distance]


def _project(data, task, role, context, changed=()):
    """Task-seeded bounded graph diffusion, with a small role tie-breaker."""
    terms, identifiers, phrases, paths = context._terms(task)
    terms |= {value.lower() for value in identifiers + phrases + paths}
    nodes = {node["id"]: node for node in data["nodes"]}
    lexical = {identity: sum(term in (node["label"] + " " + node["source"]["path"]).lower() for term in terms)
               for identity, node in nodes.items()}
    seeds = sorted((identity for identity in nodes if lexical[identity]), key=lambda i: (-lexical[i], i))[:4]
    # Changed paths augment a relevant task seed; they never invent a task when
    # the user's request has no match in the supported structural evidence.
    if not seeds:
        return {"nodes": [], "edges": [], "sources": [], "seed_ids": [], "source_priorities": {},
                "upstream": [], "downstream": [], "possible_paths": []}
    support, callers, dependencies, calls = defaultdict(set), defaultdict(set), defaultdict(set), defaultdict(set)
    for edge in data["edges"]:
        start, end = edge["from"], edge["to"]
        support[start].add(end)
        support[end].add(start)
        if edge["confidence"] == "resolved" and edge["kind"] in {"imports", "calls"}:
            callers[end].add(start)
            dependencies[start].add(end)
        if edge["kind"] == "calls" and edge["confidence"] == "resolved":
            calls[start].add(end)
    reachable = set(seeds + _reach(seeds, support, 2))
    seed_weight = {i: float(lexical[i]) if i in seeds else 0.25 if nodes[i]["source"]["path"] in changed else 0.0
                   for i in reachable}
    total = sum(seed_weight.values())
    personal = {i: value / total for i, value in seed_weight.items()}
    rank = dict(personal)
    # Fixed iterations and deterministic traversal keep offline output stable.
    for _ in range(16):
        updated = {i: 0.25 * personal[i] for i in reachable}
        for identity in sorted(reachable):
            adjacent = support[identity] & reachable
            if adjacent:
                for target in sorted(adjacent):
                    updated[target] += 0.75 * rank[identity] / len(adjacent)
            else:
                for target in sorted(reachable):
                    updated[target] += 0.75 * rank[identity] * personal[target]
        rank = updated
    testing = role in {"tester", "reviewer", "debugger"}
    ordered = sorted(reachable, key=lambda i: (-rank[i] * (1.3 if testing and _test_file(nodes[i]["source"]["path"]) else 1), i))
    selected_ids = list(dict.fromkeys(seeds + ordered))[:12]
    selected = set(selected_ids)
    edges = [edge for edge in data["edges"] if edge["from"] in selected and edge["to"] in selected]
    edges.sort(key=lambda e: (0 if e["kind"] == "calls" else 1 if e["kind"] == "imports" else 2, e["from"], e["to"]))
    priorities = {}
    for identity in selected_ids:
        node = nodes[identity]
        path = node["source"]["path"]
        if path not in priorities and len(priorities) >= 8:
            continue
        value = priorities.setdefault(path, {"score": 0, "lines": [], "reasons": []})
        value["score"] = max(value["score"], 4 if identity in seeds else 3 if testing and _test_file(path) else 2)
        if node["source"]["line"] not in value["lines"] and len(value["lines"]) < 3:
            value["lines"].append(node["source"]["line"])
        reason = "task seed" if identity in seeds else "candidate test relationship" if _test_file(path) else "structurally related source"
        if reason not in value["reasons"]:
            value["reasons"].append(reason)
    possible = []
    for seed in seeds:
        for target in sorted(calls.get(seed, ())):
            if target not in selected:
                continue
            tails = sorted((calls.get(target, set()) & selected) - {seed, target})
            possible.append([seed, target] + tails[:1])
            if len(possible) == 2:
                break
        if len(possible) == 2:
            break
    result = {"nodes": [nodes[i] for i in selected_ids], "edges": edges[:16], "seed_ids": seeds,
              "source_priorities": priorities, "upstream": [i for i in _reach(seeds, callers) if i in selected][:6],
              "downstream": [i for i in _reach(seeds, dependencies) if i in selected][:6],
              "possible_paths": possible, "sources": []}
    _prune(result, data["sources"])
    return result


def _prune(view, sources):
    ids = {node["id"] for node in view["nodes"]}
    view["edges"] = [e for e in view["edges"] if e["from"] in ids and e["to"] in ids]
    calls = {(e["from"], e["to"]) for e in view["edges"] if e["kind"] == "calls" and e["confidence"] == "resolved"}
    view["possible_paths"] = [path for path in view["possible_paths"]
                              if all(pair in calls for pair in zip(path, path[1:]))]
    view["seed_ids"] = [identity for identity in view["seed_ids"] if identity in ids]
    callers, dependencies = defaultdict(set), defaultdict(set)
    for edge in view["edges"]:
        if edge["confidence"] == "resolved" and edge["kind"] in {"imports", "calls"}:
            callers[edge["to"]].add(edge["from"])
            dependencies[edge["from"]].add(edge["to"])
    view["upstream"] = _reach(view["seed_ids"], callers)[:6]
    view["downstream"] = _reach(view["seed_ids"], dependencies)[:6]
    paths = {node["source"]["path"] for node in view["nodes"]} | {e["evidence"]["path"] for e in view["edges"]}
    view["sources"] = [source for source in sources if source["path"] in paths]
    view["source_priorities"] = {path: value for path, value in view["source_priorities"].items() if path in paths}


def query_graph(project, task, role=None, pack=None, snapshot=None, *, maintain=False,
                preview=False, writable_paths=None):
    """Return a small task view and source-priority hints; never enumerate/read sources."""
    maintenance = {"requested": maintain, "action": "not_requested", "persisted": False}
    base = {"schema_version": SCHEMA_VERSION, "status": "unavailable", "cache_status": "unavailable",
            "evidence_origin": "none", "maintenance": maintenance,
            "coverage": {"scan_complete": bool(snapshot and snapshot.get("complete")),
                         "task_filtered": bool(snapshot and snapshot.get("exclude_paths")),
                         "excluded_files": len(snapshot.get("task_excluded_paths", ())) if snapshot else 0},
            "nodes": [], "edges": [], "sources": [], "seed_ids": [], "source_priorities": {},
            "upstream": [], "downstream": [], "possible_paths": [], "diagnostics": [],
            "limits": ["Static declarations and candidate relationships; not runtime execution or test coverage."]}
    try:
        helper = _map_helper()
        root = helper._root(project)
        context = helper._context()
        scrub = context._scrubber(context.find_pack(pack))
        if (snapshot is None or not isinstance(task, str) or len(task) > context.MAX_TASK_CHARS or type(maintain) is not bool):
            raise GraphError("Graph queries require a safe context snapshot and a bounded task.")
        scope = context._cache_write_scope(task, helper.STATE_DIR + "/" + STATE_FILE,
                                           preview=preview, writable_paths=writable_paths, snapshot=snapshot)
        if maintain:
            maintenance["write_scope"] = scope
        existing, safe_state = None, True
        try:
            existing = helper._load(root, state_file=STATE_FILE, validator=_valid_graph, max_bytes=MAX_BYTES)
        except (ValueError, TypeError, KeyError, OSError):
            safe_state = False
            base["diagnostics"].append("Graph cache is malformed, foreign, or unsafe; left untouched. Current source evidence is used instead.")
        data = derive_graph(snapshot, helper, scrub)
        partial = not snapshot["complete"] or bool(snapshot.get("exclude_paths")) or bool(snapshot.get("task_excluded_paths"))
        status = "unavailable" if not safe_state else "missing" if existing is None else "fresh" if data == existing else "stale"
        if partial and safe_state:
            status = "partial"
        changed = set(snapshot.get("changed_paths", ()))
        if existing is not None:
            old = {s["path"]: s["sha256"] for s in existing["sources"]}
            changed |= {s["path"] for s in data["sources"] if old.get(s["path"]) != s["sha256"]}
        if maintain:
            if not scope["allowed"]:
                maintenance["action"] = "deferred"
                base["diagnostics"].append("Graph persistence deferred by the cache write scope; current evidence is read-only and no cache was saved.")
            elif not safe_state:
                maintenance["action"] = "unavailable"
            elif partial:
                maintenance["action"] = "deferred"
                base["diagnostics"].append("Graph persistence deferred for this partial or task-filtered scan; existing global state retained.")
            elif data == existing:
                maintenance["action"] = "unchanged"
            else:
                try:
                    helper._write(root, data, refresh=existing is not None, expected=existing,
                                  state_file=STATE_FILE, validator=_valid_graph, max_bytes=MAX_BYTES)
                    maintenance.update(action="refreshed" if existing is not None else "built", persisted=True)
                    status = "fresh"
                except (ValueError, TypeError, KeyError, OSError):
                    maintenance["action"] = "unavailable"
                    base["diagnostics"].append("Graph cache could not be saved safely; current evidence is available without a persisted refresh.")
        base.update(_project(data, scrub(task), role, context, changed), status=status, cache_status=status,
                    evidence_origin="stored" if status == "fresh" else "current_scan", omitted=data["omitted"])
        # The output budget covers sources, fingerprints, retrieval hints, and
        # all metadata, not just the displayed relationships.
        while len(json.dumps(base, ensure_ascii=False)) > MAX_VIEW_CHARS and (base["edges"] or base["nodes"]):
            if base["edges"]:
                base["edges"].pop()
            elif base["nodes"]:
                base["nodes"].pop()
            _prune(base, data["sources"])
        base["estimated_tokens"] = (len(json.dumps(base, ensure_ascii=False)) + 3) // 4
        return base
    except (ValueError, TypeError, KeyError, OSError, SyntaxError, RecursionError):
        if maintain:
            maintenance["action"] = "unavailable"
        base["diagnostics"].append("Structural graph unavailable; ordinary context and legacy map facts remain usable.")
        base["estimated_tokens"] = (len(json.dumps(base, ensure_ascii=False)) + 3) // 4
        return base
