#!/usr/bin/env python3
"""Retrieval engine: decides which repository facts matter for one task, and says why.

    request -> query analysis -> independent candidate retrievers -> rank fusion -> seeds
            -> structural + history expansion -> rerank -> (context_budget) -> optional explorer

Deterministic, local and offline: no model, embedding or network call. Facts live in
`repo_index`; every number that shapes a ranking lives in DEFAULTS below. Each candidate
keeps its provenance from the retriever that found it to the final packet.

Security: this module only ever sees a RepoIndex built from the context scan's admitted
texts. Nothing here reads a file, runs git or resolves a path outside that universe, so a
symbol, edge, co-change pair or explorer request cannot reach an excluded file.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import copy
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import time

DEFAULTS = {
    "query_analysis": True,  # False: the legacy bag of equally weighted request words.
    "retrievers": ["path", "rare_terms", "bm25", "symbol_definitions", "symbol_references", "phrases"],
    "candidate_limit": 50,  # Per retriever.
    "fusion": "rrf",  # "rrf" | "combsum" (max-normalized score sum, kept for ablation).
    "rrf_k": 20,  # Tuned on the benchmark's train split: 10-20 beat the customary 60, which mostly counts lists.
    "rrf_weights": {"git": 0.5},  # Vote weight per source; unlisted sources vote 1.0.
    "query_weights": {"path": 4.0, "symbol": 3.0, "identifier": 3.0, "concept": 1.0, "subtoken_factor": 0.5},
    "path": {"explicit": 10.0, "module": 6.0, "package": 1.5, "stem_exact": 3.0, "stem_token": 2.0,
             "directory": 1.0, "partial": 0.5, "partial_min_chars": 5},
    "bm25": {"k1": 1.2, "b": 0.75},
    "symbols": {"inexact_case": 0.6, "qualified": 2.0, "method": 0.8},
    "seed_count": 5,
    "graph": {"enabled": True, "max_hops": 1, "hop_decay": [1.0, 0.5, 0.2], "max_neighbors_per_seed": 8,
              "max_candidates": 20, "include_seeds": True, "degree_damping": "log",  # or "sqrt"
              "edge_priors": {"calls": 1.0, "called_by": 1.0, "references": 0.8, "referenced_by": 0.8,
                              "inherits": 0.8, "inherited_by": 0.8, "tested_by": 0.7, "tests": 0.7,
                              "imports": 0.5, "imported_by": 0.5, "same_module": 0.3}},
    "git": {"enabled": True, "max_commits": 2000, "max_commit_files": 30, "min_support": 2,
            "min_score": 0.1, "half_life_days": None, "max_candidates": 10},
    # Implementation-versus-test weighting and other kind priors; lifted when the request asks for that kind.
    "kind_weights": {"source": 1.0, "test": 0.5, "doc": 0.5, "config": 0.7, "manifest": 0.7, "schema": 0.8,
                     "migration": 0.8, "workflow": 0.5, "other": 0.5},
    "pin_named_paths": True,
    # Fused scores within this relative distance of their group's leader count as a tie, settled by evidence
    # (definition, then named path, then identifier, then structure) instead of by a hair of lexical rank.
    # Benchmark-neutral at 0.05 (0.10 and 0.20 cost recall); 0 compares exact scores only.
    "tie_tolerance": 0.05,
    "context": {"optimizer": True, "max_bytes": 20000, "max_files": 10, "max_tokens": None,
                "radius": 6, "narrow_radius": 2, "max_definition_lines": 40, "max_excerpts_per_file": 3,
                "max_test_share": 0.34,
                "count": "packet"},  # "packet": the whole rendered section; "excerpts": excerpt text only.
    "explorer": {"enabled": False, "max_iterations": 2, "max_new_symbols": 10, "max_new_files": 5,
                 "stop_confidence": 0.8},
    # Optional LLM layer (llm_retrieval.py), inert here: `role_summary` is in no default retriever list and is silent
    # until representations are attached to the index; reranking happens only when a caller supplies a reranker,
    # which only the user's own settings file creates. No model is ever called from this module.
    "role_summary": {"k1": 1.2, "b": 0.75, "fields": {"path": 3.0, "symbols": 3.0, "role": 2.0, "responsibilities": 2.0,
                                                       "concepts": 2.0, "interactions": 1.0, "likely_tasks": 1.0}},
    "llm_rerank": {"enabled": False, "candidate_limit": 20, "placement": "pre_graph",  # or "post_graph": rerank the final order
                   # "replace": the model's order leads, behind files the request names | "weighted" | "rrf": one more voter |
                   # "seeds": graph seeds only. Placement and integration were chosen on the benchmark's validation split.
                   "integration": "replace",
                   "weight": 2.0, "when": "always",  # "ambiguous": skip the model when deterministic evidence is decisive
                   "min_agreement": 3, "min_gap": 0.15, "shadow": False,
                   # Prompt experiments; None keeps the user's settings.
                   "content": None, "order": None, "evidence": None, "max_prompt_chars": None},
}

_LADDER = [
    ("bm25", {"query_analysis": False, "retrievers": ["bm25"], "fusion": "combsum", "graph": {"enabled": False},
              "git": {"enabled": False}, "kind_weights": None, "pin_named_paths": False,
              "context": {"optimizer": False}}),
    ("+query-analysis", {"query_analysis": True}),
    ("+path", {"retrievers": ["bm25", "path"]}),
    ("+rare-terms", {"retrievers": ["bm25", "path", "rare_terms", "phrases"]}),
    ("+symbols", {"retrievers": DEFAULTS["retrievers"]}),
    ("+rrf", {"fusion": "rrf"}),
    ("+graph", {"graph": {"enabled": True}}),
    ("+git", {"git": {"enabled": True}}),
    ("+rerank", {"kind_weights": DEFAULTS["kind_weights"], "pin_named_paths": True}),
    ("+context-optimizer", {"context": {"optimizer": True}}),
    ("+explorer", {"explorer": {"enabled": True}}),
]


def _merge(base, overrides):
    out = copy.deepcopy(base)
    for key, value in overrides.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else copy.deepcopy(value)
    return out


def _strategies():
    """Cumulative ladder for ablation, friendly aliases, and one leave-one-out per component."""
    out, current = {}, DEFAULTS
    for name, change in _LADDER:
        current = out[name] = _merge(current, change)
    out.update({"hybrid": out["+rrf"], "hybrid+graph": out["+graph"], "full": out["+context-optimizer"],
                "full+explorer": out["+explorer"]})
    full = out["full"]
    for name in DEFAULTS["retrievers"]:
        out["full-" + name] = _merge(full, {"retrievers": [r for r in DEFAULTS["retrievers"] if r != name]})
    out["full-graph"] = _merge(full, {"graph": {"enabled": False}})
    out["full-git"] = _merge(full, {"git": {"enabled": False}})
    out["full-rerank"] = _merge(full, {"kind_weights": None, "pin_named_paths": False})
    out["full-query-analysis"] = _merge(full, {"query_analysis": False})
    out["full-rrf"] = _merge(full, {"fusion": "combsum"})
    # Representation experiments: raw source (`+query-analysis`) against role summaries, alone and fused.
    out["role-only"] = _merge(out["+query-analysis"], {"retrievers": ["role_summary"]})
    out["bm25+role"] = _merge(out["+query-analysis"], {"retrievers": ["bm25", "role_summary"], "fusion": "rrf"})
    # The role voter's weight was chosen on the benchmark's validation split (0.5, 1 and 2 tried; see docs/retrieval-benchmark.md).
    out["full+role"] = _merge(full, {"retrievers": DEFAULTS["retrievers"] + ["role_summary"], "rrf_weights": {"role_summary": 2.0}})
    out["full+rerank"] = _merge(full, {"llm_rerank": {"enabled": True}})
    out["full+role+rerank"] = _merge(out["full+role"], {"llm_rerank": {"enabled": True}})
    return out


STRATEGIES = _strategies()


def configure(strategy="full", overrides=None):
    if strategy not in STRATEGIES:
        raise ValueError("Unknown retrieval strategy.")
    return dict(_merge(STRATEGIES[strategy], overrides or {}), name=strategy)


_SIBLINGS = {}


def _sibling(name):
    """Packaged code by exact path; never an import that could resolve inside the inspected project."""
    if name not in _SIBLINGS:
        path = Path(__file__).resolve().with_name(name + ".py")
        namespace = {"__name__": "_dispatcher_" + name, "__file__": str(path)}
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
        _SIBLINGS[name] = namespace
    return _SIBLINGS[name]


# ---------------------------------------------------------------- query analysis

GENERIC = set(
    "a an the and or of in on at for to from with this that it its is are was were be been by as not no but if then "
    "than so such i we you me my our your they them their he she his her please can could would should may might must "
    "will shall do does did done have has had want need make makes made add adds added fix fixes fixed update updates "
    "updated change changes changed implement improve review check find show use uses used using work works working "
    "keep keeps handle handles handled handling support supports supported ensure ensures allow allows allowed when "
    "where which while what why how who also only just still now new old get gets set sets see seems like into out "
    "over under after before about between both each some any all more most other another same there here these those "
    "file files code project repo repository task source target existing current currently instead rather correctly "
    "properly issue issues problem bug bugs behavior behaviour expected actual actually result results following "
    "example examples case cases via etc thanks thank hello hi version versions description steps reproduce "
    "src lib app py js ts tsx jsx json md yaml yml toml css html txt "
    # Process talk that task prompts carry and no file is about.
    "welcome finish finished finishing summarize summary claim claims claiming verify verified verifying adding "
    "updating offline".split())
KNOWN_SUFFIXES = {"py", "js", "jsx", "ts", "tsx", "mjs", "cjs", "go", "rs", "java", "rb", "c", "h", "cpp", "cs", "swift",
                  "kt", "php", "vue", "svelte", "css", "scss", "sh", "md", "rst", "txt", "json", "toml", "yaml", "yml",
                  "ini", "cfg", "html", "sql", "lock", "xml"}
_URL = re.compile(r"\b(?:https?|ssh|git)://\S+")
_PATHISH = re.compile(r"(?<![\w/.-])(?:\./)?(?:[\w.@-]+/)*[\w@-]+(?:\.[\w@-]+)+")
_SLASHED = re.compile(r"(?<![\w/.-])(?:\./)?(?:[\w.@-]+/)+[\w.@-]+")
_DOTTED = re.compile(r"(?<![\w.])[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+(?![\w])")
# `name(` is a call; `name (` is prose with a parenthetical ("in this checkout (see planner.py)"), never a symbol.
_CALL = re.compile(r"(?<![\w.])([A-Za-z_][\w.]*)\(")
_CODE_SPAN = re.compile(r"`([^`\n]{2,120})`")
_QUOTED = re.compile(r"[`\"']([^`\"'\n]{6,160})[`\"']")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,79}")


def analyze_query(task, config=None):
    """Split a request into what it names (paths, modules, symbols, identifiers) and what it talks about."""
    config = config or DEFAULTS
    index = _sibling("repo_index")
    weights = config["query_weights"]
    text = _URL.sub(" ", task)
    raw = _WORD.findall(text)
    paths, dotted, symbols, qualified, identifiers = [], [], [], [], []
    for value in _SLASHED.findall(text) + _PATHISH.findall(text):
        value = re.sub(r"(?::\d+(?:[:-]\d+)?|#L\d+(?:-L?\d+)?)$", "", value).strip(".")
        suffix = value.rsplit(".", 1)[-1].lower() if "." in value else ""
        if ("/" in value or suffix in KNOWN_SUFFIXES) and value not in paths:
            paths.append(value)
    for value in _DOTTED.findall(text):
        parts = value.split(".")
        if (value not in paths and parts[-1].lower() not in KNOWN_SUFFIXES and all(len(p) > 1 for p in parts)
                and any(len(p) > 2 for p in parts) and value not in dotted):
            dotted.append(value)
    for value in _CALL.findall(text):
        name = value.rsplit(".", 1)[-1]
        if len(name) > 2 and name.lower() not in GENERIC and name not in symbols:
            symbols.append(name)
        if "." in value:
            parent = value.split(".")[-2]
            if (parent, name) not in qualified:
                qualified.append((parent, name))
    for value in dotted:
        parts = value.split(".")
        if parts[-1][0].isupper() and (parts[-2], parts[-1]) not in qualified and len(parts) > 2:
            qualified.append((parts[-2], parts[-1]))
    for value in _CODE_SPAN.findall(text):
        if _WORD.fullmatch(value) and value.lower() not in GENERIC and value not in symbols:
            symbols.append(value)
    for word in raw:
        camel = any(c.isupper() for c in word[1:]) and any(c.islower() for c in word)
        if ("_" in word.strip("_") or camel or (word.isupper() and any(c.isdigit() for c in word))) and word not in identifiers:
            identifiers.append(word)
    named = set(symbols) | set(identifiers) | {part for value in dotted for part in value.split(".")}
    concepts, generic = [], []
    for word in raw:
        lower = word.lower()
        if word in named or len(lower) < 3:
            continue
        bucket = generic if lower in GENERIC else concepts
        if lower not in bucket:
            bucket.append(lower)
    terms, symbol_names = {}, {}

    def lexical(identifier, weight):
        # expand() puts the exact compound identifier first; its subtokens follow at reduced weight.
        for position, term in enumerate(index["expand"](identifier)):
            if position and term in GENERIC:
                continue
            terms[term] = max(terms.get(term, 0.0), weight * (weights["subtoken_factor"] if position else 1.0))

    for name in symbols:
        symbol_names[name] = max(symbol_names.get(name, 0.0), weights["symbol"])
        lexical(name, weights["symbol"])
    for name in identifiers:
        symbol_names[name] = max(symbol_names.get(name, 0.0), weights["identifier"])
        lexical(name, weights["identifier"])
    for value in dotted:
        for part in value.split("."):
            symbol_names[part] = max(symbol_names.get(part, 0.0), weights["identifier"])
            lexical(part, weights["identifier"])
    for value in paths:
        for part in _WORD.findall(PurePosixPath(value).name.split(".")[0]):
            lexical(part, weights["identifier"])
    for word in concepts:
        term = index["normalize"](word)
        terms[term] = max(terms.get(term, 0.0), weights["concept"])
        symbol_names.setdefault(word, weights["concept"])
    phrases = [p.strip() for p in _QUOTED.findall(text) if not _WORD.fullmatch(p.strip()) and p.strip() not in paths]
    return {"raw_tokens": len(raw), "paths": paths[:12], "dotted": dotted[:12], "symbols": symbols[:24],
            "qualified": qualified[:12], "identifiers": identifiers[:40], "concept_terms": concepts[:60],
            "generic_terms": generic, "phrases": phrases[:8], "terms": terms, "symbol_names": symbol_names,
            "wants": {"test": bool(re.search(r"\b(?:tests?|testing|pytest|unittest|spec|coverage)\b", text, re.I)),
                      "doc": bool(re.search(r"\b(?:docs?|documentation|readme|changelog|docstrings?|typos?)\b", text, re.I)),
                      "config": bool(re.search(r"\b(?:config\w*|settings?|manifest|dependenc\w+|workflow|ci)\b", text, re.I))}}


def legacy_query(task):
    """The pre-upgrade view of a request: every non-stop word, equally weighted."""
    index = _sibling("repo_index")
    words = [w.lower() for w in dict.fromkeys(_WORD.findall(task))][:80]
    terms = {index["normalize"](w): 1.0 for w in words if w not in GENERIC}
    return {"raw_tokens": len(words), "paths": [], "dotted": [], "symbols": [], "qualified": [], "identifiers": [],
            "concept_terms": sorted(terms), "generic_terms": [], "phrases": [], "terms": terms,
            "symbol_names": {}, "wants": {"test": False, "doc": False, "config": False}}


# ---------------------------------------------------------------- candidate retrievers
# The CandidateRetriever interface is a function (query, index, config) -> [candidate], registered in
# RETRIEVERS. A candidate is {"file", "score", "reason", "value"}; its rank is its position. Retrievers
# never see each other's scores: each answers one question, and fusion lets them vote.


def _ranked(scores, reasons, limit, source):
    rows = sorted(scores.items(), key=lambda item: (-item[1], len(item[0]), item[0]))[:limit]
    return [{"file": path, "rank": rank, "score": round(score, 4), "source": source, "reason": reasons[path][0],
             "value": reasons[path][1], **({"via": reasons[path][3]} if reasons[path][3] else {})}
            for rank, (path, score) in enumerate(rows, 1) if score > 0]


def _note(reasons, path, gain, reason, value, via=None):
    """Keep the single strongest explanation per file for this retriever."""
    if path not in reasons or gain > reasons[path][2]:
        reasons[path] = (reason, value, gain, via)


def path_retriever(query, index, config):
    """What file looks explicitly named? Path evidence is scored on its own, never length-normalized."""
    weights, scores, reasons, decisive = config["path"], defaultdict(float), {}, set()
    for value in query["paths"]:
        cleaned = value[2:] if value.startswith("./") else value
        for path in index.paths:
            if path == cleaned or path.endswith("/" + cleaned):
                scores[path] += weights["explicit"]
                decisive.add(path)
                _note(reasons, path, math.inf, "explicit path in request", value)  # Always the reason shown.
    for value in query["dotted"]:
        parts = value.split(".")
        # `a.b.Symbol` may resolve as `a.b`; falling all the way back to a bare top-level package would
        # promote an unrelated `__init__`, so a single segment only counts for `module.symbol`.
        for end in range(len(parts), 0 if len(parts) == 2 else 1, -1):
            target = index.module_path(".".join(parts[:end]))
            if not target:
                continue
            gain = weights["module"] * end / len(parts)
            scores[target] += gain
            if end > 1:
                decisive.add(target)
            _note(reasons, target, math.inf if end > 1 else gain, "dotted name resolves to this module", ".".join(parts[:end]))
            package = PurePosixPath(target).parent.as_posix() + "/"
            if PurePosixPath(target).name.split(".")[0] in {"__init__", "index", "mod"}:
                for path in index.paths:
                    if path.startswith(package) and path != target:
                        scores[path] += weights["package"]
                        _note(reasons, path, weights["package"], "inside the named package", ".".join(parts[:end]))
            break
    for term, weight in query["terms"].items():
        rarity = index.path_idf(term)
        if rarity <= 0:
            continue
        for path in index.paths:
            stem, stem_tokens, directory_tokens = index.path_parts[path]
            if term == stem:
                kind, label = "stem_exact", "exact file name match"
            elif term in stem_tokens:
                kind, label = "stem_token", "file name contains request term"
            elif term in directory_tokens:
                kind, label = "directory", "directory matches request term"
            elif len(term) >= weights["partial_min_chars"] and term in stem:
                kind, label = "partial", "file name partially matches request term"
            else:
                continue
            gain = weights[kind] * rarity * weight
            scores[path] += gain
            _note(reasons, path, gain, label, term)
    # The request named these outright (a path, or a dotted name that resolves to one).
    return [dict(row, decisive=True) if row["file"] in decisive else row
            for row in _ranked(scores, reasons, config["candidate_limit"], "path")]


def rare_term_retriever(query, index, config):
    """Where does this unusual concept occur? Presence x squared rarity, damped by vocabulary size."""
    scores, reasons = defaultdict(float), {}
    average = sum(len(r["terms"]) for r in index.records.values()) / index.size or 1.0
    for term, weight in query["terms"].items():
        rarity = index.idf(term)
        if rarity <= 0:
            continue
        for path, record in index.records.items():
            if term in record["terms"]:
                gain = weight * rarity * rarity
                scores[path] += gain
                _note(reasons, path, gain, "contains rare repository term", term)
    for path in scores:
        scores[path] /= 1.0 + math.log1p(len(index.records[path]["terms"]) / average)
    return _ranked(scores, reasons, config["candidate_limit"], "rare_terms")


def bm25_retriever(query, index, config):
    """Classic length-normalized lexical relevance over identifier subtokens."""
    k1, b = config["bm25"]["k1"], config["bm25"]["b"]
    scores, reasons = defaultdict(float), {}
    for term, weight in query["terms"].items():
        rarity = index.idf(term)
        if rarity <= 0:
            continue
        for path, record in index.records.items():
            frequency = record["terms"].get(term)
            if frequency:
                norm = frequency + k1 * (1 - b + b * record["len"] / index.average_length)
                gain = weight * rarity * frequency * (k1 + 1) / norm
                scores[path] += gain
                _note(reasons, path, gain, "lexical relevance (BM25)", term)
    return _ranked(scores, reasons, config["candidate_limit"], "bm25")


def symbol_definition_retriever(query, index, config):
    """Where is this thing defined? Spread across few files counts for more than across many."""
    tuning, scores, reasons = config["symbols"], defaultdict(float), {}
    for name, weight in query["symbol_names"].items():
        exact = index.definitions.get(name)
        names = [name] if exact else sorted(index.lower_definitions.get(name.lower(), ()))
        for found in names:
            rows = index.definitions[found]
            spread = math.sqrt(len({row[0] for row in rows}))
            for path, line, _, kind, parent in rows:
                gain = weight * (1.0 if found == name else tuning["inexact_case"]) / spread
                if kind == "method":
                    gain *= tuning["method"]
                if (parent, found) in query["qualified"]:
                    gain *= tuning["qualified"]
                scores[path] += gain
                _note(reasons, path, gain, f"defines {kind}", f"{parent + '.' if parent else ''}{found}:{line}")
    return _ranked(scores, reasons, config["candidate_limit"], "symbol_definitions")


def symbol_reference_retriever(query, index, config):
    """Who uses this thing? Only names the request treats as code, never plain prose words."""
    floor = config["query_weights"]["identifier"]
    scores, reasons = defaultdict(float), {}
    for name, weight in query["symbol_names"].items():
        if weight < floor:
            continue
        found = index.referencing(name)
        for path, count in found.items():
            gain = weight * (1.0 + math.log(count)) / math.log(2 + len(found))
            scores[path] += gain
            _note(reasons, path, gain, "references symbol", name)
    return _ranked(scores, reasons, config["candidate_limit"], "symbol_references")


def phrase_retriever(query, index, config):
    """Quoted literals (error messages, SQL, flags) found verbatim."""
    scores, reasons = defaultdict(float), {}
    for phrase in query["phrases"]:
        for path, text in index.texts.items():
            if phrase in text:
                scores[path] += 1.0
                _note(reasons, path, 1.0, "contains quoted literal", phrase[:60])
    return _ranked(scores, reasons, config["candidate_limit"], "phrases")


def role_summary_retriever(query, index, config):
    """What does a model-written role summary say this file is responsible for? Silent until representations are attached."""
    if not getattr(index, "representations", None):
        return []
    scores, reasons = _sibling("llm_retrieval")["summary_scores"](query, index, config["role_summary"])
    return _ranked(scores, reasons, config["candidate_limit"], "role_summary")


RETRIEVERS = {"path": path_retriever, "rare_terms": rare_term_retriever, "bm25": bm25_retriever,
              "symbol_definitions": symbol_definition_retriever, "symbol_references": symbol_reference_retriever,
              "phrases": phrase_retriever, "role_summary": role_summary_retriever}


# ---------------------------------------------------------------- fusion and expansion


def fuse(lists, config):
    """Reciprocal rank fusion: sum of weight / (k + rank). Ranks, not raw scores, cross retrievers."""
    scores = defaultdict(float)
    for source, rows in lists.items():
        weight = config["rrf_weights"].get(source, 1.0)
        top = max((row["score"] for row in rows), default=0) or 1.0
        for row in rows:
            scores[row["file"]] += (weight / (config["rrf_k"] + row["rank"]) if config["fusion"] == "rrf"
                                    else weight * row["score"] / top)
    return scores


# Why a neighbor matters, told from the neighbor's side of the edge.
_EDGE_REASONS = {"imports": "one-hop local import; imported by {origin}", "imported_by": "imports {origin}",
                 "calls": "called by {origin}", "called_by": "calls {origin}",
                 "references": "referenced by {origin}", "referenced_by": "references {origin}",
                 "inherits": "base class of {origin}", "inherited_by": "subclasses {origin}",
                 "tested_by": "paired test for {origin}", "tests": "implementation tested by {origin}",
                 "same_module": "same directory as {origin}"}


def graph_candidates(seeds, index, config, known=()):
    """Bounded neighbor expansion from strong seeds, decayed per hop and damped by in-degree."""
    tuning = config["graph"]
    scores, reasons = defaultdict(float), {}
    frontier = [(path, 1.0 / rank) for rank, path in enumerate(seeds, 1)]
    for hop in range(1, tuning["max_hops"] + 1):
        decay = tuning["hop_decay"][min(hop, len(tuning["hop_decay"]) - 1)]
        following = []
        for origin, strength in frontier:
            found = {}
            for other, kind, detail in index.neighbors(origin):
                if other in seeds and not tuning["include_seeds"]:
                    continue
                damping = math.sqrt(1 + index.in_degree[other]) if tuning["degree_damping"] == "sqrt" else math.log(2 + index.in_degree[other])
                value = strength * decay * tuning["edge_priors"].get(kind, 0.0) / damping
                if value > found.get(other, (0,))[0]:
                    found[other] = (value, kind, detail)
            # Sharing a directory is weak: it may reinforce a file something else found, never introduce one.
            siblings = ([other for other in index.same_directory(origin) if other in known and other not in seeds]
                        if tuning["edge_priors"].get("same_module") else [])
            for other in siblings:
                value = strength * decay * tuning["edge_priors"]["same_module"] / math.log(2 + len(siblings))
                if value > found.get(other, (0,))[0]:
                    found[other] = (value, "same_module", PurePosixPath(origin).parent.as_posix())
            best = sorted(found.items(), key=lambda item: (-item[1][0], item[0]))[:tuning["max_neighbors_per_seed"]]
            for other, (value, kind, detail) in best:
                scores[other] += value
                _note(reasons, other, value, _EDGE_REASONS[kind].format(origin=origin), str(detail), origin)
                following.append((other, value))
        frontier = sorted(following, key=lambda item: (-item[1], item[0]))[:tuning["max_candidates"]]
    return _ranked(scores, reasons, tuning["max_candidates"], "graph")


def git_candidates(seeds, index, config):
    """Files that historically change with a seed. A modest second opinion, never a first one."""
    tuning, scores, reasons = config["git"], defaultdict(float), {}
    for rank, seed in enumerate(seeds, 1):
        for other, score, support in index.partners.get(seed, ()):
            if score >= tuning["min_score"] and support >= tuning["min_support"]:
                scores[other] += score / rank
                _note(reasons, other, score / rank, f"frequently co-changed with {seed}", f"jaccard {score}, {support} commits", seed)
    return _ranked(scores, reasons, tuning["max_candidates"], "git")


_IDENTIFIER_SOURCES = {"path", "symbol_definitions", "symbol_references", "phrases", "explorer"}


def _rerank(scores, evidence, index, query, config, named, role):
    lifted = {kind for kind, wanted in query["wants"].items() if wanted}
    if role in {"debugger", "tester", "reviewer"}:
        lifted.add("test")
    if query["wants"]["config"]:
        lifted.update({"manifest", "workflow", "schema"})
    rows = []
    for path, score in scores.items():
        kind = index.kinds.get(path, "other")
        prior = 1.0 if kind in lifted or path in named else (config["kind_weights"] or {}).get(kind, 1.0)
        sources = {item["source"] for item in evidence[path]}
        # Evidence-based tie-breaks; the path is only the final deterministic fallback.
        rows.append({"path": path, "value": round(score * prior, 9), "pinned": path in named and config["pin_named_paths"],
                     "evidence": (-("symbol_definitions" in sources), -("path" in sources), -len(sources & _IDENTIFIER_SOURCES),
                                  -len(sources & {"graph", "git"}), index.in_degree[path])})
    rows.sort(key=lambda row: (-row["pinned"], -row["value"], row["evidence"], row["path"]))
    # Scores within `tie_tolerance` of their group's leader count as a tie and are reordered by evidence.
    ordered, group = [], []
    for row in rows:
        if group and (row["pinned"] != group[0]["pinned"] or row["value"] < group[0]["value"] * (1 - config["tie_tolerance"])):
            ordered += sorted(group, key=lambda r: (r["evidence"], -r["value"], r["path"]))
            group = []
        group.append(row)
    ordered += sorted(group, key=lambda r: (r["evidence"], -r["value"], r["path"]))
    return [(row["path"], row["value"]) for row in ordered]


def _confidence(first, lists, pinned):
    """How decisive deterministic evidence already is: a named file, retrievers agreeing on the leader, its lead."""
    leader = first[0][0] if first else None
    return {"pinned": bool(pinned), "agreement": sum(1 for rows in lists.values() if rows[0]["file"] == leader),
            "gap": round((first[0][1] - first[1][1]) / first[0][1], 4) if len(first) > 1 and first[0][1] else 1.0}


def _llm_opinion(task, order, evidence, index, config, reranker):
    """Ask the optional reranker to order the top candidates, and nothing else -> (record, evidence rows).

    The reranker never raises for model trouble; it answers {"error": ...} and the ranking stays
    deterministic. Whatever it answers is re-checked here: only supplied candidates can be ordered.
    """
    rows = [{"path": path, "rank": rank, "evidence": sorted(evidence[path], key=lambda e: (e["rank"], e["source"]))}
            for rank, path in enumerate(order[:config["llm_rerank"]["candidate_limit"]], 1)]
    started = time.perf_counter()
    prompt = {key: config["llm_rerank"][key] for key in ("content", "order", "evidence", "max_prompt_chars")
              if config["llm_rerank"][key] is not None}
    answer = reranker(task, rows, index, prompt) if rows else {"error": "no candidates"}
    record = {"candidates": [row["path"] for row in rows], **{key: answer[key] for key in ("error", "usage", "invalid", "request") if key in answer}}
    record["ms"] = round((time.perf_counter() - started) * 1000, 1)
    ordered = list(dict.fromkeys(path for path in answer.get("order", ()) if path in set(record["candidates"])))
    if not ordered:
        record.setdefault("error", "no usable ranking")
        return record, []
    record["order"] = ordered + [path for path in record["candidates"] if path not in ordered]  # Unranked keep their order, last.
    reasons, labels = answer.get("reasons", {}), answer.get("labels", {})
    record["reasons"] = {path: reasons[path] for path in record["order"][:5] if reasons.get(path)}
    return record, [{"file": path, "rank": rank, "score": round(1 / rank, 4), "source": "llm_rerank",
                     "reason": "model reranker opinion, not a repository fact" + (": " + reasons[path] if reasons.get(path) else ""),
                     "value": labels.get(path) or "ranked"} for rank, path in enumerate(record["order"], 1)]


def _integrate(order, rows, lists, evidence, index, query, config, pinned, role):
    """Where a model's ordering of the top candidates meets the deterministic ranking: evidence, never the only evidence."""
    tuning = config["llm_rerank"]
    for row in rows:
        evidence[row["file"]].append(row)
    if tuning["integration"] == "seeds":
        return order
    if tuning["integration"] == "rrf":
        lists["llm_rerank"] = rows
        scores = fuse(lists, _merge(config, {"rrf_weights": {"llm_rerank": tuning["weight"]}}))
        for path in pinned:
            scores.setdefault(path, 0.0)
        return _rerank(scores, evidence, index, query, config, pinned, role)
    position = {row["file"]: row["rank"] for row in rows}
    fixed = pinned if config["pin_named_paths"] else set()  # A file the request names outright is not the model's to demote.
    if tuning["integration"] == "replace":
        value = dict(order)
        return ([item for item in order if item[0] in fixed]
                + [(path, value.get(path, 0.0)) for path in sorted(position, key=position.get) if path not in fixed]
                + [item for item in order if item[0] not in fixed and item[0] not in position])
    k = config["rrf_k"]  # "weighted": two voters, the deterministic final order and the model's.
    blended = [(path, round(1 / (k + rank) + (tuning["weight"] / (k + position[path]) if path in position else 0.0), 9), rank)
               for rank, (path, _) in enumerate(order, 1)]
    return [(path, score) for path, score, _ in sorted(blended, key=lambda row: (row[0] not in fixed, -row[1], row[2]))]


def retrieve(task, index, config=None, *, named=(), role=None, extra=None, boost_only=(), fallback=None, reranker=None):  # noqa: C901
    """Run the pipeline once.

    `extra` carries candidate lists from outside (worktree, explorer). Sources in `boost_only` may
    strengthen a file another retriever found but never introduce one. `fallback` rows join the
    very end of the ranking when nothing else found them. `reranker` is the optional model-backed
    callable from llm_retrieval.py; without it this function is exactly the deterministic pipeline.
    """
    config = config or STRATEGIES["full"]
    started = time.perf_counter()
    query = analyze_query(task, config) if config["query_analysis"] else legacy_query(task)
    lists = {name: RETRIEVERS[name](query, index, config) for name in config["retrievers"]}
    found = {row["file"] for rows in lists.values() for row in rows}
    for name, rows in (extra or {}).items():
        lists[name] = [row for row in rows if name not in boost_only or row["file"] in found]
    lists = {name: rows for name, rows in lists.items() if rows}
    first = sorted(fuse(lists, config).items(), key=lambda item: (-item[1], item[0]))
    # A file the request names outright (a path, or a dotted name that resolves to it) is decisive evidence.
    resolved = [row["file"] for row in lists.get("path", ()) if row.get("decisive")] if config["pin_named_paths"] else []
    pinned = list(dict.fromkeys([path for path in named if path in index.kinds] + resolved))
    tuning, llm, llm_rows = config["llm_rerank"], None, []
    confidence = _confidence(first, lists, pinned)
    decisive = confidence["pinned"] or (confidence["agreement"] >= tuning["min_agreement"] and confidence["gap"] >= tuning["min_gap"])
    asking = reranker is not None and tuning["enabled"] and not (tuning["when"] == "ambiguous" and decisive)
    if asking and tuning["placement"] == "pre_graph":
        found_by = defaultdict(list)
        for rows in lists.values():
            for row in rows:
                found_by[row["file"]].append(row)
        llm, llm_rows = _llm_opinion(task, [path for path, _ in first], found_by, index, config, reranker)
    semantic = [] if tuning["shadow"] else [row["file"] for row in llm_rows]  # Variant A: the model's order picks the graph seeds.
    seeds = list(dict.fromkeys(pinned + semantic + [path for path, _ in first]))[:config["seed_count"]]
    before = {row["file"] for rows in lists.values() for row in rows}
    if config["graph"]["enabled"] and seeds:
        lists["graph"] = graph_candidates(seeds, index, config, before)
    if config["git"]["enabled"] and seeds:
        lists["git"] = git_candidates(seeds, index, config)
    lists = {name: rows for name, rows in lists.items() if rows}
    evidence = defaultdict(list)
    for rows in lists.values():
        for row in rows:
            evidence[row["file"]].append(row)
    scores = fuse(lists, config)
    for path in pinned:
        scores.setdefault(path, 0.0)
        if path in named:
            evidence[path].append({"file": path, "rank": 1, "score": 0.0, "source": "named",
                                   "reason": "explicit project path", "value": path})
    order = _rerank(scores, evidence, index, query, config, set(pinned), role)
    if asking and tuning["placement"] == "post_graph":
        llm, llm_rows = _llm_opinion(task, [path for path, _ in order], evidence, index, config, reranker)
    if llm_rows and not tuning["shadow"]:
        order = _integrate(order, llm_rows, lists, evidence, index, query, config, set(pinned), role)
    for row in fallback or ():
        if row["file"] not in scores and row["file"] in index.records:
            order.append((row["file"], 0.0))
            evidence[row["file"]].append(row)
    ranked = [{"path": path, "rank": rank, "score": round(score, 6), "kind": index.kinds.get(path, "other"),
               "evidence": sorted(evidence[path], key=lambda e: (e["rank"], e["source"]))}
              for rank, (path, score) in enumerate(order, 1)]
    sources = sorted(lists)
    trace = {"raw_tokens": query["raw_tokens"],
             "identifiers": len(query["paths"]) + len(query["dotted"]) + len(query["symbols"]) + len(query["identifiers"]),
             "concepts": len(query["concept_terms"]), "ignored": len(query["generic_terms"]),
             "candidates": {name: len(rows) for name, rows in lists.items()},
             "union": len(before), "seeds": seeds,
             "graph_additions": len({r["file"] for r in lists.get("graph", ())} - before),
             "git_additions": len({r["file"] for r in lists.get("git", ())} - before
                                  - {r["file"] for r in lists.get("graph", ())}),
             "overlap": {f"{a}&{b}": len({r["file"] for r in lists[a]} & {r["file"] for r in lists[b]})
                         for i, a in enumerate(sources) for b in sources[i + 1:]},
             "final": len(ranked), "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
    result = {"query": query, "lists": lists, "ranked": ranked, "trace": trace,
              "first": [path for path, _ in first[:50]]}  # Fused candidates before expansion: what a reranker can choose from.
    if reranker is not None and tuning["enabled"]:
        trace["confidence"] = confidence
        trace["llm"] = {"asked": asking, "placement": tuning["placement"], "integration": tuning["integration"],
                        "shadow": tuning["shadow"], **{key: llm[key] for key in ("error", "ms", "invalid", "usage") if llm and key in llm},
                        "candidates": len(llm["candidates"]) if llm else 0}
        result["llm"] = llm
    represented = getattr(index, "representations", None)
    if represented:
        result["roles"] = {row["path"]: represented[row["path"]]["role"] for row in ranked[:10] if row["path"] in represented}
    return result


# ---------------------------------------------------------------- explorer (optional, bounded)

REQUEST_TYPES = ("symbol", "path", "callers", "references", "neighbors")


def normalize_findings(findings, config):
    """Accept the documented explorer contract in either spelling; drop anything else, then bound it."""
    limits = config["explorer"]
    if not isinstance(findings, dict):
        return {"stop": True, "confidence": 0.0, "reason": "invalid findings", "requests": []}
    requests = [r for r in findings.get("requests", []) if isinstance(r, dict)]
    requests += [{"type": "symbol", "value": v} for v in findings.get("new_symbols", [])]
    requests += [{"type": "path", "value": v} for v in findings.get("new_paths", [])]
    requests += [{"type": {"callers": "callers", "references": "references"}.get(r.get("relationship"), "neighbors"),
                  "value": r.get("symbol") or r.get("path")} for r in findings.get("follow_relationships", []) if isinstance(r, dict)]
    clean = []
    for request in requests:
        value = request.get("value", request.get("symbol", request.get("path")))
        if request.get("type") in REQUEST_TYPES and isinstance(value, str) and 0 < len(value) <= 240:
            clean.append({"type": request["type"], "value": value})
    confidence = findings.get("confidence", 0.0)
    confidence = float(confidence) if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else 0.0
    stop = bool(findings.get("stop")) or findings.get("status") == "sufficient" or confidence >= limits["stop_confidence"]
    return {"stop": stop, "confidence": confidence, "reason": str(findings.get("reason", ""))[:240],
            "requests": clean[:limits["max_new_symbols"]]}


def resolve_requests(requests, index, config):
    """Answer explorer requests from the index alone. An excluded target simply does not exist here."""
    scores, reasons = defaultdict(float), {}
    for position, request in enumerate(requests, 1):
        kind, value, gain = request["type"], request["value"], 1.0 / position
        if kind == "symbol":
            found = [(row[0], f"defines {value}") for row in index.definitions.get(value, ())]
        elif kind == "path":
            cleaned = value[2:] if value.startswith("./") else value
            found = [(p, "requested path") for p in index.paths if p == cleaned or p.endswith("/" + cleaned)]
        elif kind in {"callers", "references"}:
            users = index.referencing(value)
            found = [(p, f"{'calls' if kind == 'callers' else 'references'} {value}")
                     for p in sorted(users, key=lambda p: (-users[p], p))
                     if kind == "references" or value in index.records[p]["calls"] or index.records[p]["lang"] != "python"]
        else:
            found = [(other, f"{edge.replace('_', ' ')} {value}") for other, edge, _ in index.neighbors(value)] if value in index.records else []
        for path, reason in found[:config["explorer"]["max_new_files"]]:
            scores[path] += gain
            _note(reasons, path, gain, "explorer request: " + reason, value)
    return _ranked(scores, reasons, config["explorer"]["max_new_files"], "explorer")


def deterministic_explorer(view):
    """Model-free reconnaissance: which named symbols are still undefined or unused in the context?

    `view` is what any explorer sees: the analyzed request and the selected files with their
    symbols and relationships. Confidence is a stopping signal, not a probability.
    """
    wanted = [name for name, weight in view["query"]["symbol_names"].items() if weight >= 3.0]
    files = view["files"]
    defined = {symbol for item in files for symbol in item["symbols"]}
    related = " ".join(rel for item in files for rel in item["relationships"])
    requests = [{"type": "symbol", "value": name} for name in wanted if name not in defined]
    requests += [{"type": "callers", "value": name} for name in wanted
                 if name in defined and "called by" not in related and "referenced by" not in related]
    if files and not any(item["kind"] == "test" for item in files):
        requests.append({"type": "neighbors", "value": files[0]["path"]})
    covered = sum(name in defined for name in wanted) / len(wanted) if wanted else 1.0
    used = not wanted or "called by" in related or "referenced by" in related
    confidence = round(0.5 * covered + 0.5 * bool(files and used), 2)
    return {"status": "expand" if requests else "sufficient", "confidence": confidence,
            "reason": "Named symbols lack a definition, a caller or a test in context." if requests
                      else "Definitions and their users are present.", "requests": requests}


def apply_findings(result, findings, index, config, protected=None):
    """Answer one round of explorer findings and insert the new files directly below the seeds.

    Answers never reorder what retrieval already ranked: an explorer adds missing evidence, it does
    not overrule primary evidence. Returns the step record (what was asked, what was added).
    """
    findings = normalize_findings(findings, config)
    step = {**{k: findings[k] for k in ("stop", "confidence", "reason")}, "requests": findings["requests"], "added": []}
    if findings["stop"] or not findings["requests"]:
        return step
    protected = config["seed_count"] if protected is None else protected
    shown = {row["path"] for row in result["ranked"][:config["context"]["max_files"]]}
    fresh = [row for row in resolve_requests(findings["requests"], index, config) if row["file"] not in shown]
    result["lists"]["explorer"] = result["lists"].get("explorer", []) + fresh
    rows = {row["path"]: row for row in result["ranked"]}
    moved = []
    for row in fresh:
        entry = rows.get(row["file"]) or {"path": row["file"], "score": 0.0, "kind": index.kinds.get(row["file"], "other"), "evidence": []}
        entry["evidence"] = [row] + entry["evidence"]
        moved.append(entry)
    step["added"] = [entry["path"] for entry in moved]
    kept = [row for row in result["ranked"] if row["path"] not in set(step["added"])]
    result["ranked"] = kept[:protected] + moved + kept[protected:]
    for rank, row in enumerate(result["ranked"], 1):
        row["rank"] = rank
    return step


def explore(task, index, config, view_of, *, explorer=deterministic_explorer, **options):
    """initial retrieval -> explorer asks -> deterministic targeted retrieval, at most max_iterations times."""
    result = retrieve(task, index, config, **options)
    result["exploration"] = []
    protected = config["seed_count"]
    for iteration in range(1, config["explorer"]["max_iterations"] + 1):
        step = dict(apply_findings(result, explorer(view_of(result)), index, config, protected), iteration=iteration)
        result["exploration"].append(step)
        protected += len(step["added"])
        if not step["added"]:
            break
    return result


# ---------------------------------------------------------------- one call for the context helper


def build_index(texts, hashes, kind_of, *, cache=None, history=None, config=None, path_only=(), stats=None):
    """Facts for the admitted universe. `history` is raw `git log` text, or None when unavailable."""
    config = config or STRATEGIES["full"]
    facts = _sibling("repo_index")
    stats = stats if stats is not None else {}
    started = time.perf_counter()
    records = facts["load_records"](texts, hashes, cache, stats)
    partners = None
    if history and config["git"]["enabled"]:
        commits = facts["parse_git_log"](history, set(texts) | set(path_only), config["git"]["max_commit_files"])
        partners = facts["cochange"](commits, min_support=config["git"]["min_support"],
                                     half_life_days=config["git"]["half_life_days"])
        stats["history_commits"] = len(commits)
    index = facts["RepoIndex"](records, kind_of, partners, path_only)
    index.texts, index.hashes = texts, hashes
    stats["index_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return index


def run(task, index, config=None, *, anchors=None, explorer=None, findings=None, iteration=1, **options):
    """Retrieve, optionally explore, then budget. Returns ranking, packet and a full trace."""
    config = config or STRATEGIES["full"]
    budget = _sibling("context_budget")

    def packet_of(result):
        return budget["build_packet"](result["ranked"], index, result["query"], config, anchors=anchors or {})

    def view_of(result):
        return {"query": result["query"], "files": packet_of(result)["files"]}

    if config["explorer"]["enabled"]:
        result = explore(task, index, config, view_of, explorer=explorer or deterministic_explorer, **options)
    else:
        result = retrieve(task, index, config, **options)
    if findings is not None:  # One round asked for by the host acting as explorer (`retrieval.py expand`).
        result.setdefault("exploration", []).append(dict(apply_findings(result, findings, index, config), iteration=iteration))
    started = time.perf_counter()
    result["packet"] = packet_of(result)
    result["trace"].update(context_files=len(result["packet"]["files"]), context_bytes=result["packet"]["bytes"],
                           context_tokens=result["packet"]["tokens"],
                           context_ms=round((time.perf_counter() - started) * 1000, 2))
    return result


# ---------------------------------------------------------------- explainability


def render_query(query):
    lines = ["IDENTIFIERS"] + [f"  {v}" for v in query["paths"] + query["dotted"] + query["symbols"] + query["identifiers"]]
    lines += ["", "CONCEPT TERMS"] + [f"  {v}" for v in query["concept_terms"]]
    lines += ["", "IGNORED/LOW-WEIGHT TERMS"] + [f"  {v}" for v in query["generic_terms"]]
    if query["phrases"]:
        lines += ["", "QUOTED LITERALS"] + [f"  {v}" for v in query["phrases"]]
    return "\n".join(lines)


def render_explain(result, verbose=False, top=10):
    query, trace, packet = result["query"], result["trace"], result.get("packet")
    kept = {item["path"] for item in packet["files"]} if packet else set()
    dropped = {item["path"]: item["reason"] for item in packet["dropped"]} if packet else {}
    lines = ["QUERY ANALYSIS", render_query(query), "", "TOP FILES"]
    for row in result["ranked"][:top]:
        state = "in context" if row["path"] in kept else "not in context: " + dropped.get(row["path"], "below file limit")
        lines.append(f"{row['rank']}. {row['path']}  [{row['kind']}; fused {row['score']}; {state}]")
        lines += [f"   + {e['source']} rank #{e['rank']}: {e['reason']} ({e['value']})" for e in row["evidence"]]
        if verbose and row["path"] in result.get("roles", {}):
            lines.append("   ~ role summary (model-written retrieval aid): " + result["roles"][row["path"]])
    request = (result.get("llm") or {}).get("request")
    if request:
        lines += ["", "RERANK REQUEST (host step: order these candidates for the request above, then run "
                      "`retrieval.py rerank` with --ranking '{\"ranking\": [{\"id\": \"C..\", \"label\": \"primary|supporting|weak\", "
                      "\"reason\": \"...\"}, ...]}'; only supplied ids count)", request]
    for step in result.get("exploration", []):
        lines += ["", f"EXPLORER iteration {step.get('iteration', 1)}: confidence {step['confidence']}, "
                      f"{'stop' if step['stop'] else 'expand'} - {step['reason']}"]
        lines += [f"   ? {r['type']} {r['value']}" for r in step["requests"]]
        lines += [f"   + {path}" for path in step["added"]]
    if verbose:
        lines += ["", "PIPELINE", f"QUERY              {trace['raw_tokens']} raw tokens",
                  f"FILTER             {trace['concepts']} concepts, {trace['identifiers']} identifiers, {trace['ignored']} ignored"]
        lines += [f"{name.upper():<19}{count} candidates" for name, count in trace["candidates"].items()
                  if name not in {"graph", "git", "llm_rerank"}]
        model = trace.get("llm")
        if model:
            usage = model.get("usage") or {}
            lines.append("LLM RERANK         " + (f"fell back to deterministic ranking: {model['error']}" if model.get("error") else
                         "skipped: deterministic evidence was decisive" if not model["asked"] else
                         f"{model['candidates']} candidates, {model['placement']}, {model['integration']}"
                         f"{' (shadow: recorded, not applied)' if model['shadow'] else ''}, "
                         f"{usage.get('input_tokens', 0)} in / {usage.get('output_tokens', 0)} out tokens, {model.get('ms', 0)} ms"))
        lines += [f"MERGED             {trace['union']} unique files", f"SEEDS              {len(trace['seeds'])}: {', '.join(trace['seeds'])}",
                  f"GRAPH EXPANSION    {trace['graph_additions']} additional candidates",
                  f"GIT CO-CHANGE      {trace['git_additions']} additional candidates",
                  f"FINAL RERANK       {trace['final']} files"]
        if packet:
            lines.append(f"CONTEXT            {trace['context_files']} files, {trace['context_bytes'] / 1000:.1f} KB, "
                         f"~{trace['context_tokens']} estimated tokens")
        lines += [f"LATENCY            {trace['latency_ms']} ms retrieval"
                  + (f", {trace['context_ms']} ms context" if packet else ""),
                  "OVERLAP            " + ", ".join(f"{k}={v}" for k, v in trace["overlap"].items() if v)]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="retrieval.py", description="Inspect repository retrieval decisions. Read-only.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("explain", "explain-query", "expand", "rerank"):
        command = sub.add_parser(name)
        command.add_argument("task")
        if name != "explain-query":
            command.add_argument("--project", default=".")
            command.add_argument("--strategy", default="full", choices=sorted(STRATEGIES))
            command.add_argument("--exclude-path", action="append", default=[])
            command.add_argument("--pack")
            command.add_argument("--verbose", action="store_true")
            command.add_argument("--no-llm", action="store_true", help="Ignore the user's LLM retrieval settings; deterministic only")
            command.add_argument("--json", action="store_true")
        if name == "expand":
            command.add_argument("--findings", required=True, help="Explorer findings as JSON (see docs/repository-intelligence.md)")
            command.add_argument("--iteration", type=int, default=1)
        if name == "rerank":
            command.add_argument("--ranking", required=True, help="The host's answer to a RERANK REQUEST, as JSON (see docs/llm-assisted-retrieval.md)")
    args = parser.parse_args(argv)
    if args.command == "explain-query":
        print(render_query(analyze_query(args.task)))
        return 0
    context = _sibling("context")
    try:
        findings = ranking = None
        if args.command == "rerank":
            ranking = json.loads(args.ranking)
        if args.command == "expand":
            if not 1 <= args.iteration <= DEFAULTS["explorer"]["max_iterations"]:
                raise context["ContextError"]("Explorer iteration limit reached; no further expansion.")
            findings = json.loads(args.findings)
        result = context["explain_retrieval"](args.project, args.task, strategy=args.strategy, pack=args.pack,
                                              exclude_paths=args.exclude_path, findings=findings,
                                              iteration=getattr(args, "iteration", 1), llm=not args.no_llm, ranking=ranking)
    except (context["ContextError"], ValueError, OSError) as exc:
        print(str(exc) if isinstance(exc, context["ContextError"]) else "Retrieval input could not be used; values withheld.", file=sys.stderr)
        return 2
    if args.json:
        result = {key: result[key] for key in ("query", "ranked", "trace", "packet", "exploration", "llm", "roles") if key in result}
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(render_explain(result, args.verbose))
        print("\n" + _sibling("context_budget")["render_packet"](result["packet"]) if args.verbose else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
