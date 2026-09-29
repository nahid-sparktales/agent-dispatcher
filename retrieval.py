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
from collections import Counter, defaultdict
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
    "rrf_weights": {"git": 0.5, "experience": 0.5, "inference": 0.5},  # Vote weight per source; unlisted sources vote 1.0.
    # Correlated voters: sources in a group are fused among themselves first and then vote once, as the group.
    # None keeps every retriever as its own voter. Example: {"lexical": {"sources": ["bm25", "rare_terms",
    # "symbol_references"], "weight": 1.0}}.
    "fusion_groups": None,
    "query_weights": {"path": 4.0, "symbol": 3.0, "identifier": 3.0, "concept": 1.0, "subtoken_factor": 0.5},
    # How a request word earns identifier weight; benchmark ablation switches, the defaults are the shipped behavior.
    # case_only "shape": a word whose only code signal is its capitalization (MySQL, GraphQL) is an identifier;
    # "resolved": weighed by what it denotes in the index (analyze_query). slash_words "path": every A/B token is a
    # query path; "resolved": only one that names indexed files, other A/B prose is read as words.
    "names": {"case_only": "shape", "slash_words": "path"},
    "path": {"explicit": 10.0, "module": 6.0, "package": 1.5, "stem_exact": 3.0, "stem_token": 2.0,
             "directory": 1.0, "partial": 0.5, "partial_min_chars": 5},
    "bm25": {"k1": 1.2, "b": 0.75},
    "symbols": {"inexact_case": 0.6, "qualified": 2.0, "method": 0.8},
    "seed_count": 5,
    "graph": {"enabled": True, "max_hops": 1, "hop_decay": [1.0, 0.5, 0.2], "max_neighbors_per_seed": 8,
              "max_candidates": 20, "include_seeds": True, "degree_damping": "log",  # or "sqrt"
              # A neighbor tied to a seed by several kinds of edge (calls + imports + references): "max" counts the
              # strongest edge only, "sum" every edge, "soft" the strongest plus half of the rest.
              "multi_edge": "max",
              "edge_priors": {"calls": 1.0, "called_by": 1.0, "references": 0.8, "referenced_by": 0.8,
                              "inherits": 0.8, "inherited_by": 0.8, "tested_by": 0.7, "tests": 0.7,
                              "imports": 0.5, "imported_by": 0.5, "same_module": 0.3}},
    "git": {"enabled": True, "max_commits": 2000, "max_commit_files": 30, "min_support": 2,
            "min_score": 0.1, "half_life_days": None, "max_candidates": 10,
            # Association measure over the eligible events (repo_index.cochange): "jaccard" (default, measured),
            # "conditional" (P(partner | seed), `shrinkage` events added to the denominator) or "lift" (gated by
            # `min_lift`). Ablation switches; the same seeds, support floor and partner cap apply to each.
            "statistic": "jaccard", "shrinkage": 0.0, "min_lift": 1.0},
    # Implementation-versus-test weighting and other kind priors; lifted when the request asks for that kind.
    "kind_weights": {"source": 1.0, "test": 0.5, "doc": 0.5, "config": 0.7, "manifest": 0.7, "schema": 0.8,
                     "migration": 0.8, "workflow": 0.5, "other": 0.5},
    "pin_named_paths": True,
    # Stack-trace frames in the request (`File "x.py", line 12, in f`; `at f (src/x.ts:12:5)`): each frame's path is
    # matched by its longest suffix that exists in the index and votes in the path retriever; the innermost frame
    # counts double; its line anchors the excerpt; the frame's function name is a symbol. Never pinned.
    "frames": {"enabled": True, "weight": 1.0, "innermost_bonus": 1.0, "max_frames": 12, "max_matches": 3},
    # Admitted files over the read limit contribute their definitions, imports and calls (structural records
    # computed without retaining the text) instead of their name alone.
    "structural_records": True,
    # ...and their terms from the same bounded read, with excerpts re-read on demand. Ablation switch: False keeps only
    # the definitions (the structural-only behavior before lexical coverage), with no excerpt.
    # `references`: whether those terms also become term-reference graph edges. A file read up to 4 MiB mentions nearly
    # every name in the repository, so as a graph seed it expanded into unrelated files; off, its terms still match requests
    # and its imports, calls and definitions keep their edges (strategy `full-oversized-references` turns it back on).
    "oversized": {"lexical": True, "references": False},
    # Hub files: a file whose distinct terms are at least `min_share` of the repository's vocabulary shares words with
    # almost any request, so the lexical voters in `sources` find it for unrelated tasks (sqlglot/generator.py, 17% of the
    # vocabulary, was in every pilot packet). Query-independent. Ablation switch, off at 0.0 (strategy `full+hubs`): those
    # votes are scaled by (1 - damping); a definition, path or graph vote is never damped.
    "hubs": {"damping": 0.0, "min_share": 0.15, "sources": ["bm25", "rare_terms", "symbol_references"]},
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
    # Deep repository index layers (repository_intelligence.py), inert here: `experience` and `inference` are in no
    # default retriever list and are silent until the context helper attaches eligible records to the index.
    # Experience: prior checked tasks whose request resembles this one vote for the files they changed. Bounded,
    # explainable, never an override: a fixed vote weight, a candidate cap, a similarity floor and support counts.
    "experience": {"min_similarity": 0.2, "min_support": 1, "max_candidates": 10, "half_life_days": 180,
                   "changed_file_factor": 0.5, "outcome_weights": {"checked_success": 1.0, "accepted": 0.8, "grader_passed": 1.0}},
    # Inference: model-written subsystem/architecture claims with validated evidence files. A claim votes for its
    # evidence files, split among them, and is always labeled as an inference rather than a repository fact.
    "inference": {"max_candidates": 10, "max_files_per_claim": 8},
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
    out["full-frames"] = _merge(full, {"frames": {"enabled": False}})
    out["full-structure"] = _merge(full, {"structural_records": False})
    out["full-oversized-structural"] = _merge(full, {"oversized": {"lexical": False}})
    out["full-oversized-references"] = _merge(full, {"oversized": {"references": True}})
    out["full+hubs"] = _merge(full, {"hubs": {"damping": 0.5}})
    # Representation experiments: raw source (`+query-analysis`) against role summaries, alone and fused.
    out["role-only"] = _merge(out["+query-analysis"], {"retrievers": ["role_summary"]})
    out["bm25+role"] = _merge(out["+query-analysis"], {"retrievers": ["bm25", "role_summary"], "fusion": "rrf"})
    # The role voter's weight was chosen on the benchmark's validation split (0.5, 1 and 2 tried; see docs/retrieval-benchmark.md).
    out["full+role"] = _merge(full, {"retrievers": DEFAULTS["retrievers"] + ["role_summary"], "rrf_weights": {"role_summary": 2.0}})
    out["full+rerank"] = _merge(full, {"llm_rerank": {"enabled": True}})
    out["full+role+rerank"] = _merge(out["full+role"], {"llm_rerank": {"enabled": True}})
    # Deep repository index layers, each ablatable on its own: `full+experience`, `full+inference`, both as `full+deep`.
    out["full+experience"] = _merge(full, {"retrievers": DEFAULTS["retrievers"] + ["experience"]})
    out["full+inference"] = _merge(full, {"retrievers": DEFAULTS["retrievers"] + ["inference"]})
    out["full+deep"] = _merge(full, {"retrievers": DEFAULTS["retrievers"] + ["experience", "inference"]})
    out["full+deep-experience"] = out["full+inference"]
    out["full+deep-inference"] = out["full+experience"]
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
_PY_FRAME = re.compile(r"File \"([^\"\n]{1,400})\", line (\d{1,7})(?:, in ([A-Za-z_][\w.<>]*))?")
_JS_FRAME = re.compile(r"\bat (?:([\w.$<>\[\] ]{1,120}?) \()?((?:[A-Za-z]:)?[^\s():]{1,400}\.(?:m?[jt]sx?|cjs|vue|svelte)):(\d{1,7})(?::\d+)?\)?")


def _frames(text, limit):
    """Traceback frames in order of appearance -> [{path (no drive or leading slash), line, function, innermost}]."""
    found = []
    for match in _PY_FRAME.finditer(text):
        found.append({"path": match.group(1), "line": int(match.group(2)), "function": match.group(3), "kind": "python"})
    for match in _JS_FRAME.finditer(text):
        found.append({"path": match.group(2), "line": int(match.group(3)), "function": match.group(1), "kind": "js"})
    frames = []
    for frame in found[:limit]:
        raw = frame["path"].replace("\\", "/")
        raw = re.sub(r"^[A-Za-z]:", "", raw).lstrip("/")
        if raw.startswith("./"):
            raw = raw[2:]
        parts = [part for part in raw.split("/") if part not in ("", ".", "..")]
        if not parts or "<" in raw:
            continue  # `<stdin>`, `<string>` and the like name no file.
        function = frame["function"]
        if function and (function in {"<module>", "<lambda>"} or "<" in function):
            function = None
        frames.append({"path": "/".join(parts), "line": frame["line"], "function": function.rsplit(".", 1)[-1] if function else None,
                       "kind": frame["kind"], "innermost": False})
    if frames:  # Python lists the innermost frame last; JavaScript first.
        python = [f for f in frames if f["kind"] == "python"]
        (python[-1] if python else frames[0])["innermost"] = True
    return frames


def frame_matches(frame, index, max_matches=3):
    """Index paths that end with the longest suffix of a frame path; a bare file name counts only when unique."""
    parts = frame["path"].split("/")
    for size in range(len(parts), 0, -1):
        suffix = "/".join(parts[-size:])
        matches = [p for p in index.paths if p == suffix or p.endswith("/" + suffix)]
        if matches and (size > 1 or len(matches) == 1) and len(matches) <= max_matches:
            return matches, size
        if len(matches) > max_matches:
            return [], size
    return [], 0


def frame_anchors(query, index, config):
    """{path: line} from frames that resolve to exactly one indexed file; the innermost frame wins a conflict."""
    tuning = config["frames"]
    anchors = {}
    if not tuning["enabled"]:
        return anchors
    for frame in sorted(query.get("frames", []), key=lambda f: f["innermost"]):
        matches, _ = frame_matches(frame, index, tuning["max_matches"])
        if len(matches) == 1:
            anchors[matches[0]] = frame["line"]
    return anchors


def _names_files(value, index):
    """A slash token names indexed files: it ends an indexed path (extension optional) or is a run of its directories.
    `value` is the raw token: trailing dots (sentence end) and leading ./ or ../ are dropped, a leading dot (.github) kept."""
    value = re.sub(r"^(?:\.{1,2}/)+", "", value.rstrip("."))
    # ponytail: one scan of the paths per slash token; index path suffixes if pasted logs with many tokens get slow.
    return any(("/" + p).endswith("/" + value) or ("/" + re.sub(r"\.[^./]*$", "", p)).endswith("/" + value)
               or ("/" + value + "/") in ("/" + p) for p in index.paths)


def _calibrate(identifiers, explicit, raw, index, weights):
    """names.case_only "resolved": a word that looks like code only by its capitalization is weighed by what it denotes
    in the index. No definition: a concept. Its definitions plus same-stem non-test files (its family) count n: one file
    keeps identifier weight, n files get concept + (identifier - concept) / sqrt(n), except that the strictly
    most-mentioned of two or more such ambiguous names keeps identifier weight. Never below concept weight."""
    facts = _sibling("repo_index")
    names = [n for n in identifiers if n not in explicit and "_" not in n.strip("_") and not (n.isupper() and any(c.isdigit() for c in n))]
    if not names:
        return {}
    stems = defaultdict(set)
    for path in index.paths:
        if index.kinds[path] != "test":
            stems[index.path_parts[path][0]].add(path)
    found = {name: ({row[0] for row in index.definitions.get(name, ())}, stems.get(facts["normalize"](name.lower()), set()),
                    raw.count(name)) for name in names}
    # ponytail: dominance counts exact-case mentions in the request; a tie demotes every tied name.
    counts = sorted((m for d, f, m in found.values() if d and len(d | f) > 1), reverse=True)
    out = {}
    for name, (defines, family, mentions) in found.items():
        n = len(defines | family)
        if not defines:
            weight, reason = weights["concept"], "no definition"
        elif n == 1:
            weight, reason = weights["identifier"], "denotes one file"
        elif len(counts) > 1 and mentions == counts[0] > counts[1]:
            weight, reason = weights["identifier"], "most mentioned of the ambiguous names"
        else:
            weight, reason = weights["concept"] + (weights["identifier"] - weights["concept"]) / math.sqrt(n), f"ambiguous: denotes {n} files"
        out[name] = {"weight": weight, "defines": len(defines), "family": len(family), "mentions": mentions, "reason": reason}
    return out


def analyze_query(task, config=None, index=None):
    """Split a request into what it names (paths, modules, symbols, identifiers) and what it talks about.

    `index` (a RepoIndex) is consulted only by the `names` switches set to "resolved"; without it, or with the
    default switches, the analysis depends on the request text alone."""
    config = config or DEFAULTS
    facts = _sibling("repo_index")
    weights = config["query_weights"]
    names = config.get("names", DEFAULTS["names"])
    resolve_slashes, resolve_case = (index is not None and names[key] == "resolved" for key in ("slash_words", "case_only"))
    text = _URL.sub(" ", task)
    raw = _WORD.findall(text)
    paths, dotted, symbols, qualified, identifiers = [], [], [], [], []
    for value in _SLASHED.findall(text) + _PATHISH.findall(text):
        token = re.sub(r"(?::\d+(?:[:-]\d+)?|#L\d+(?:-L?\d+)?)$", "", value)
        value = token.strip(".")
        suffix = value.rsplit(".", 1)[-1].lower() if "." in value else ""
        if (("/" in value or suffix in KNOWN_SUFFIXES) and value not in paths
                and (suffix in KNOWN_SUFFIXES or not resolve_slashes or _names_files(token, index))):
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
    frames = _frames(text, config.get("frames", DEFAULTS["frames"])["max_frames"]) if config.get("frames", DEFAULTS["frames"])["enabled"] else []
    for frame in frames:
        name = frame["function"]
        if name and len(name) > 2 and name.lower() not in GENERIC and name not in symbols and _WORD.fullmatch(name):
            symbols.append(name)
    for word in raw:
        camel = any(c.isupper() for c in word[1:]) and any(c.islower() for c in word)
        if ("_" in word.strip("_") or camel or (word.isupper() and any(c.isdigit() for c in word))) and word not in identifiers:
            identifiers.append(word)
    calibration = {}
    if resolve_case:
        explicit = (set(symbols) | {part for value in dotted for part in value.split(".")}
                    | {word for value in paths for word in _WORD.findall(PurePosixPath(value).name.split(".")[0])})  # a named file
        calibration = _calibrate(identifiers, explicit, raw, index, weights)
        identifiers = [name for name in identifiers if name not in calibration or calibration[name]["defines"]]  # Else a concept.
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
        for position, term in enumerate(facts["expand"](identifier)):
            if position and term in GENERIC:
                continue
            terms[term] = max(terms.get(term, 0.0), weight * (weights["subtoken_factor"] if position else 1.0))

    for name in symbols:
        symbol_names[name] = max(symbol_names.get(name, 0.0), weights["symbol"])
        lexical(name, weights["symbol"])
    for name in identifiers:
        weight = calibration[name]["weight"] if name in calibration else weights["identifier"]
        symbol_names[name] = max(symbol_names.get(name, 0.0), weight)
        lexical(name, weight)
        if weight >= weights["identifier"] and calibration.get(name, {}).get("family"):  # MySQL -> the mysql file family.
            stem = facts["normalize"](name.lower())
            terms[stem] = max(terms.get(stem, 0.0), weights["concept"])
    for value in dotted:
        for part in value.split("."):
            symbol_names[part] = max(symbol_names.get(part, 0.0), weights["identifier"])
            lexical(part, weights["identifier"])
    for value in paths:
        for part in _WORD.findall(PurePosixPath(value).name.split(".")[0]):
            lexical(part, weights["identifier"])
    for word in concepts:
        term = facts["normalize"](word)
        terms[term] = max(terms.get(term, 0.0), weights["concept"])
        symbol_names.setdefault(word, weights["concept"])
    for name, row in calibration.items():  # No definition: the exact spelling stays a concept term, without its subtokens.
        if not row["defines"]:
            terms[name] = max(terms.get(name, 0.0), weights["concept"])
    phrases = [p.strip() for p in _QUOTED.findall(text) if not _WORD.fullmatch(p.strip()) and p.strip() not in paths]
    return {"raw_tokens": len(raw), "paths": paths[:12], "dotted": dotted[:12], "symbols": symbols[:24], "frames": frames,
            "qualified": qualified[:12], "identifiers": identifiers[:40], "concept_terms": concepts[:60],
            "generic_terms": generic, "phrases": phrases[:8], "terms": terms, "symbol_names": symbol_names,
            "wants": {"test": bool(re.search(r"\b(?:tests?|testing|pytest|unittest|spec|coverage)\b", text, re.I)),
                      "doc": bool(re.search(r"\b(?:docs?|documentation|readme|changelog|docstrings?|typos?)\b", text, re.I)),
                      "config": bool(re.search(r"\b(?:config\w*|settings?|manifest|dependenc\w+|workflow|ci)\b", text, re.I))},
            **({"calibration": calibration} if calibration else {})}


def legacy_query(task):
    """The pre-upgrade view of a request: every non-stop word, equally weighted."""
    index = _sibling("repo_index")
    words = [w.lower() for w in dict.fromkeys(_WORD.findall(task))][:80]
    terms = {index["normalize"](w): 1.0 for w in words if w not in GENERIC}
    return {"raw_tokens": len(words), "paths": [], "dotted": [], "symbols": [], "frames": [], "qualified": [], "identifiers": [],
            "concept_terms": sorted(terms), "generic_terms": [], "phrases": [], "terms": terms,
            "symbol_names": {}, "wants": {"test": False, "doc": False, "config": False}}


# ---------------------------------------------------------------- candidate retrievers
# The CandidateRetriever interface is a function (query, index, config) -> [candidate], registered in
# RETRIEVERS. A candidate is {"file", "score", "reason", "value"}; its rank is its position. Retrievers
# never see each other's scores: each answers one question, and fusion lets them vote.


def _ranked(scores, reasons, limit, source):
    rows = sorted(scores.items(), key=lambda item: (-item[1], len(item[0]), item[0]))[:limit]
    return [{"file": path, "rank": rank, "score": round(score, 4), "source": source, "reason": reasons[path][0],
             "value": reasons[path][1], **({"via": reasons[path][3]} if reasons[path][3] else {}),
             **({"detail": reasons[path][4]} if len(reasons[path]) > 4 and reasons[path][4] else {})}
            for rank, (path, score) in enumerate(rows, 1) if score > 0]


def _note(reasons, path, gain, reason, value, via=None, detail=None):
    """Keep the single strongest explanation per file for this retriever. `detail` (the statistic's
    denominators, for instance) is shown by explain and never enters a packet."""
    if path not in reasons or gain > reasons[path][2]:
        reasons[path] = (reason, value, gain, via, detail)


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
    frames = config["frames"]
    if frames["enabled"]:
        for frame in query.get("frames", []):
            matches, size = frame_matches(frame, index, frames["max_matches"])
            if not matches:
                continue
            gain = weights["explicit"] * frames["weight"] * (1 + frames["innermost_bonus"] if frame["innermost"] else 1.0) / len(matches)
            for path in matches:
                scores[path] += gain
                _note(reasons, path, gain, "traceback frame names this file" + (" (innermost)" if frame["innermost"] else ""),
                      f"{'/'.join(frame['path'].split('/')[-size:])}:{frame['line']}")
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


def experience_retriever(query, index, config):
    """Which files did earlier, checked tasks like this one change? Silent until experience records are attached."""
    events = getattr(index, "experience", None)
    if not events:
        return []
    scores, reasons = _sibling("experience")["scores"](query, index, events, config["experience"])
    return _ranked(scores, reasons, config["experience"]["max_candidates"], "experience")


def inference_retriever(query, index, config):
    """Which architectural claims (model inferences with validated evidence) match the request? Silent until attached."""
    items = getattr(index, "inferences", None)
    if not items:
        return []
    facts = _sibling("repo_index")
    tuning, scores, reasons = config["inference"], defaultdict(float), {}
    documents = []
    for item in items:
        terms = set()
        for identifier in facts["IDENT"].findall(item.get("text", "") + " " + item.get("question", "")):
            terms.update(facts["expand"](identifier))
        documents.append((item, terms))
    frequency = defaultdict(int)
    for _, terms in documents:
        for term in terms:
            frequency[term] += 1
    for item, terms in documents:
        gain = sum(weight * math.log(1 + (len(documents) - frequency[term] + 0.5) / (frequency[term] + 0.5))
                   for term, weight in query["terms"].items() if term in terms)
        if gain <= 0:
            continue
        files = list(dict.fromkeys(e["path"] for e in item.get("evidence", []) if e.get("path") in index.kinds))[:tuning["max_files_per_claim"]]
        for path in files:
            share = gain / math.sqrt(len(files))
            scores[path] += share
            _note(reasons, path, share, "cited by an architectural inference (model inference, not a repository fact)",
                  item.get("text", "")[:80])
    return _ranked(scores, reasons, tuning["max_candidates"], "inference")


RETRIEVERS = {"path": path_retriever, "rare_terms": rare_term_retriever, "bm25": bm25_retriever,
              "symbol_definitions": symbol_definition_retriever, "symbol_references": symbol_reference_retriever,
              "phrases": phrase_retriever, "role_summary": role_summary_retriever,
              "experience": experience_retriever, "inference": inference_retriever}


def damp_hubs(lists, index, config):
    """Scale hub files' votes in the `hubs.sources` lists by (1 - damping) and re-rank those lists (stable, so
    every other file keeps its order). A hub's distinct terms are at least `min_share` of the repository's vocabulary."""
    tuning = config.get("hubs") or {}
    if not tuning.get("damping"):
        return lists
    vocabulary = set()
    for record in index.records.values():
        vocabulary.update(record["terms"])
    shares = {path: len(record["terms"]) / len(vocabulary) for path, record in index.records.items() if vocabulary}
    hubs = {path for path, share in shares.items() if share >= tuning["min_share"]}
    factor, out = 1.0 - tuning["damping"], dict(lists)
    for source in [name for name in tuning["sources"] if name in lists] if hubs else ():
        rows = [dict(row, score=round(row["score"] * factor, 4),
                     detail=f"hub file: {shares[row['file']]:.0%} of the repository's terms; vote x{factor:g}")
                if row["file"] in hubs else row for row in lists[source]]
        rows = sorted((row for row in rows if row["score"] > 0), key=lambda row: -row["score"])
        out[source] = [dict(row, rank=rank) for rank, row in enumerate(rows, 1)]
    return out


# ---------------------------------------------------------------- fusion and expansion


def fuse(lists, config):
    """Reciprocal rank fusion: sum of weight / (k + rank). Ranks, not raw scores, cross retrievers.

    With `fusion_groups`, the members of a group are fused among themselves first and the group's
    ranking votes once: three retrievers reading the same tokens no longer outvote one path match.
    """
    lists = dict(lists)
    for name, group in (config.get("fusion_groups") or {}).items():
        members = {source: lists.pop(source) for source in group["sources"] if source in lists}
        if members:
            inner = fuse(members, dict(config, fusion_groups=None, rrf_weights={}))
            ordered = sorted(inner.items(), key=lambda item: (-item[1], item[0]))
            lists[name] = [{"file": path, "rank": rank, "score": round(score, 6)} for rank, (path, score) in enumerate(ordered, 1)]
            config = dict(config, rrf_weights={**config["rrf_weights"], name: group.get("weight", 1.0)})
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
            found, edges = {}, defaultdict(list)
            for other, kind, detail in index.neighbors(origin):
                if other in seeds and not tuning["include_seeds"]:
                    continue
                damping = math.sqrt(1 + index.in_degree[other]) if tuning["degree_damping"] == "sqrt" else math.log(2 + index.in_degree[other])
                edges[other].append((strength * decay * tuning["edge_priors"].get(kind, 0.0) / damping, kind, detail))
            for other, rows in edges.items():
                rows.sort(key=lambda row: -row[0])
                value, kind, detail = rows[0]
                if tuning.get("multi_edge", "max") == "sum":
                    value = sum(row[0] for row in rows)
                elif tuning.get("multi_edge") == "soft":
                    value += 0.5 * sum(row[0] for row in rows[1:])
                if value > 0:
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
    """Files that historically change with a seed. A modest second opinion, never a first one.

    The evidence names its denominators: "changed in n(A,B) of the n(A) eligible events containing A" over
    N eligible events, so a percentage never travels without its support count and window.
    """
    tuning, scores, reasons = config["git"], defaultdict(float), {}
    statistic = tuning.get("statistic", "jaccard")
    floor = tuning.get("min_lift", 1.0) if statistic == "lift" else tuning["min_score"]
    stats = getattr(index, "history_stats", None) or {}
    for rank, seed in enumerate(seeds, 1):
        for other, score, support in index.partners.get(seed, ()):
            if score >= floor and support >= tuning["min_support"]:
                scores[other] += score / rank
                _note(reasons, other, score / rank, f"frequently co-changed with {seed}", f"{statistic} {score}, {support} commits", seed,
                      cochange_evidence(seed, support, stats))
    return _ranked(scores, reasons, tuning["max_candidates"], "git")


def cochange_evidence(seed, support, stats):
    """A partner's denominators spelled out; counts that are unavailable are said to be, never zero."""
    n_seed, events = (stats.get("changes") or {}).get(seed), stats.get("events")
    if not n_seed or not events:
        return "event counts unavailable for this window"
    return f"changed in {support} of the {n_seed} eligible events containing {seed}; {events} eligible events in the window"


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


_HISTORY_WORDS = re.compile(r"\b(?:before|previously|earlier|again|regress(?:ion|ed|es)?|used to|last time|we fixed|once more)\b", re.I)
_IMPACT_WORDS = re.compile(r"\b(?:affects?|affected|impact|ripple|depends? on|dependents?|callers?|downstream|consumers?)\b", re.I)
# Identifier-level evidence: a file named, resolved from a dotted name, frame or exact file name, matched by
# symbol, or holding a quoted literal. A directory or partial name match is lexical, not an anchor.
_ANCHOR_SOURCES = {"named", "symbol_definitions", "symbol_references", "phrases"}
_ANCHOR_PATH_REASONS = ("explicit path", "dotted name", "traceback frame", "exact file name")
STATUSES = ("ok", "partial_coverage", "abstained_no_sufficient_local_evidence", "unavailable", "stale_only",
            "budget_exhausted", "provider_failed")


def plan_retrieval(task, query, config, *, extra=(), reranker=None):
    """The deterministic plan for one request: families, reason codes, caps and stop conditions.

    The plan is observational in this release: it names what runs and why, it does not switch a family
    off (every deterministic family costs milliseconds and keeps the baseline coverage path), and the
    optional stages keep their own gates, which it reports. `profile` is a label for reading traces
    and stratifying evaluations, not a probability and not a permission.
    """
    reasons = []
    if query["paths"]:
        reasons.append("explicit_path")
    if query.get("frames"):
        reasons.append("traceback_frames")
    if query["dotted"] or query["qualified"]:
        reasons.append("qualified_name")
    if query["symbols"] or query["identifiers"]:
        reasons.append("identifier")
    if query["phrases"]:
        reasons.append("quoted_literal")
    if not reasons:
        reasons.append("concept_terms_only" if query["concept_terms"] else "no_usable_terms")
    if query["wants"]["test"]:
        reasons.append("asks_for_tests")
    if _HISTORY_WORDS.search(task):
        reasons.append("history_wording")
    if _IMPACT_WORDS.search(task):
        reasons.append("impact_wording")
    anchored = {"explicit_path", "traceback_frames", "qualified_name", "quoted_literal"} & set(reasons)
    profile = ("exact" if anchored else "history" if "history_wording" in reasons else "impact" if "impact_wording" in reasons
               else "tests" if "asks_for_tests" in reasons else "behavior" if {"identifier", "concept_terms_only"} & set(reasons)
               else "vague")
    tuning = config["llm_rerank"]
    return {"profile": profile, "reasons": reasons, "policy": "observe",
            "families": {"deterministic": list(config["retrievers"]), "supplied": sorted(extra),
                         "expansion": {"graph": bool(config["graph"]["enabled"]), "git": bool(config["git"]["enabled"])},
                         "assistance": {"reranker": "configured" if reranker is not None and tuning["enabled"] else "off",
                                        "reranker_policy": tuning["when"],
                                        "explorer": "deterministic" if config["explorer"]["enabled"] else "off"}},
            "caps": {"candidates_per_retriever": config["candidate_limit"], "seeds": config["seed_count"],
                     "graph": {"hops": config["graph"]["max_hops"], "neighbors_per_seed": config["graph"]["max_neighbors_per_seed"],
                               "candidates": config["graph"]["max_candidates"]},
                     "git": {"candidates": config["git"]["max_candidates"], "min_support": config["git"]["min_support"],
                             "statistic": config["git"].get("statistic", "jaccard")},
                     "oversized": {"lexical": (config.get("oversized") or {}).get("lexical", True),
                                   "references": (config.get("oversized") or {}).get("references", False)},
                     "names": dict(config.get("names", DEFAULTS["names"])),
                     "hubs": copy.deepcopy(config.get("hubs", DEFAULTS["hubs"])),
                     "reranker_candidates": tuning["candidate_limit"],
                     "packet": {"files": config["context"]["max_files"], "bytes": config["context"]["max_bytes"]}},
            "stop_conditions": ["each retriever answers once, capped", "expansion: seeds x hops x per-seed cap",
                                "reranker: one bounded call or none", f"explorer: at most {config['explorer']['max_iterations']} iterations"]}


def _displacement(before, after, evidence, window, stage_sources):
    """What one stage changed inside the top `window`: files it introduced, with the sources that brought
    them, files it pushed out, and files it moved. A stage that adds neighbors is not thereby helping."""
    before_top, after_top = [p for p, _ in before[:window]], [p for p, _ in after[:window]]
    introduced = [{"path": p, "sources": sorted({e["source"] for e in evidence[p]} & stage_sources)
                   or sorted({e["source"] for e in evidence[p]})} for p in after_top if p not in before_top]
    return {"window": window, "introduced": introduced, "displaced": [p for p in before_top if p not in after_top],
            "moved": sum(1 for p in after_top if p in before_top and before_top.index(p) != after_top.index(p))}


def _coverage(index):
    """partial_coverage: files the index knows without complete lexical coverage. `unread_files` (no lexical coverage)
    is kept for older readers; `by_state` counts every file's coverage and `paths` names the first affected ones."""
    states = getattr(index, "coverage", None) or {}
    affected = sorted(path for path, state in states.items() if state != "complete")
    if not index.path_only and not affected:
        return None
    return {"condition": "partial_coverage", "unread_files": len(index.path_only),
            "by_state": dict(sorted(Counter(states.values()).items())), "paths": affected[:8]}


def _status(ranked, index, window, llm=None):
    """The result's standing, kept apart from its ranking: what kind of evidence backs the top files and
    which conditions a reader must know about. An empty index is unavailable; an empty ranking over a
    known universe is abstention; a missing summary or history never means no source exists."""
    top = ranked[:window]

    def anchors(rows):
        return any(e["source"] in _ANCHOR_SOURCES or (e["source"] == "path" and e["reason"].startswith(_ANCHOR_PATH_REASONS))
                   for row in rows for e in row["evidence"])
    anchored, leader = anchors(top), anchors(top[:1])
    known = len(index.records) + len(index.path_only)
    status = "unavailable" if not known else "abstained_no_sufficient_local_evidence" if not top else "ok"
    conditions = [condition for condition in (_coverage(index),) if condition]
    if llm and llm.get("error") and not llm.get("order"):
        conditions.append({"condition": "provider_failed", "detail": llm["error"]})
    return {"status": status, "evidence": "anchored" if anchored else "lexical" if top else "none",
            "leader": "anchored" if leader else "lexical" if top else "none", "conditions": conditions}


def retrieve(task, index, config=None, *, named=(), role=None, extra=None, boost_only=(), fallback=None, reranker=None):  # noqa: C901
    """Run the pipeline once.

    `extra` carries candidate lists from outside (worktree, explorer). Sources in `boost_only` may
    strengthen a file another retriever found but never introduce one. `fallback` rows join the
    very end of the ranking when nothing else found them. `reranker` is the optional model-backed
    callable from llm_retrieval.py; without it this function is exactly the deterministic pipeline.
    """
    config = config or STRATEGIES["full"]
    started = time.perf_counter()
    query = analyze_query(task, config, index) if config["query_analysis"] else legacy_query(task)
    lists = damp_hubs({name: RETRIEVERS[name](query, index, config) for name in config["retrievers"]}, index, config)
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
    window = config["context"]["max_files"]
    base_evidence = defaultdict(list)
    for rows in lists.values():
        for row in rows:
            base_evidence[row["file"]].append(row)
    base_scores = fuse(lists, config)
    for path in pinned:
        base_scores.setdefault(path, 0.0)
    unexpanded = _rerank(base_scores, base_evidence, index, query, config, set(pinned), role)  # The same order without graph/git.
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
    displacement = {"expansion": _displacement(unexpanded, order, evidence, window, {"graph", "git"})}
    if asking and tuning["placement"] == "post_graph":
        llm, llm_rows = _llm_opinion(task, [path for path, _ in order], evidence, index, config, reranker)
    if llm_rows and not tuning["shadow"]:
        expanded = order
        order = _integrate(order, llm_rows, lists, evidence, index, query, config, set(pinned), role)
        displacement["rerank"] = _displacement(expanded, order, evidence, window, {"llm_rerank"})
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
             "final": len(ranked), "displacement": displacement,
             "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
    result = {"query": query, "lists": lists, "ranked": ranked, "trace": trace,
              "first": [path for path, _ in first[:50]],  # Fused candidates before expansion: what a reranker can choose from.
              "plan": plan_retrieval(task, query, config, extra=extra or (), reranker=reranker),
              "status": _status(ranked, index, window, llm)}
    if reranker is not None and tuning["enabled"]:
        trace["confidence"] = confidence
        trace["llm"] = {"asked": asking, "placement": tuning["placement"], "integration": tuning["integration"],
                        "shadow": tuning["shadow"], **{key: llm[key] for key in ("error", "ms", "invalid", "usage") if llm and key in llm},
                        "candidates": len(llm["candidates"]) if llm else 0}
        result["llm"] = llm
    represented = getattr(index, "representations", None)
    if represented:
        result["roles"] = {row["path"]: represented[row["path"]]["role"] for row in ranked[:10] if row["path"] in represented}
    if getattr(index, "extended", None):
        trace["extended_files"] = len(index.extended)
    for name in ("experience", "inference"):
        if name in lists:
            trace[name + "_candidates"] = len(lists[name])
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


class LazyTexts(dict):
    """Scanned texts plus files indexed without retained text: ones the deep index knows but this scan did not read
    (beyond its caps), and lexically indexed files over the read limit (excerpts only).

    A loadable path counts as present; its text is read on first use through the caller's loader, which
    applies the same admission, redaction and fingerprint checks as the scan. `items()` covers only what
    is loaded, so a whole-text search (quoted literals) is honest about which files it looked at.
    """

    def __init__(self, texts, loader, loadable):
        super().__init__(texts)
        self.loader, self.loadable, self.failed = loader, set(loadable), set()

    def __contains__(self, path):
        if dict.__contains__(self, path):
            return True
        if path in self.loadable and path not in self.failed:
            # Stale evidence is rejected here: a loadable file whose current content no longer matches its record is absent.
            return self.get(path) is not None
        return False

    def __missing__(self, path):
        if path in self.loadable and path not in self.failed:
            text = self.loader(path)
            if text is not None:
                self[path] = text
                return text
            self.failed.add(path)
        raise KeyError(path)

    def get(self, path, default=None):
        try:
            return self[path]
        except KeyError:
            return default


def build_index(texts, hashes, kind_of, *, cache=None, history=None, config=None, path_only=(), stats=None,
                store=None, extended=None, partners=None, loader=None, structural=None, history_stats=None):
    """Facts for the admitted universe. `history` is raw `git log` text, or None when unavailable.

    `store` (a deep repository index) supplies records whose fingerprint matches the scan, in place of the
    parser-cache shards; `extended` adds records for verified files the scan could not read (their text is
    loaded on demand through `loader`); `partners` are precomputed co-change rows that replace `history`
    (`history_stats`, their event population, lets the evidence name its denominators);
    `structural` adds records ({path: {"record", "sha256", "cap"}}, context._oversized_record) for admitted files over the
    read limit: matched by term, symbol and relationship although their text is never retained, and loadable through
    `loader` for excerpts, their terms adding no term-reference edges unless `oversized.references` is on. With
    `oversized.lexical` off their terms are dropped (definitions only, never loaded). A path
    without a record carries only its coverage state. `index.coverage` maps every known file to complete, partial_lexical,
    structural_only or unreadable (stale is added when a load is rejected).
    """
    config = config or STRATEGIES["full"]
    facts = _sibling("repo_index")
    stats = stats if stats is not None else {}
    started = time.perf_counter()
    if store is not None:
        stored = store.records(hashes)
        stats.update(record_hits=len(stored), record_misses=0, store_records=len(stored))
        records, missing = {}, []
        for path, text in texts.items():
            if path in stored:
                records[path] = stored[path]
            else:
                records[path] = facts["file_record"](path, text)
                stats["record_misses"] += 1
                missing.append(path)
        stats["missing_paths"] = missing
    else:
        records = facts["load_records"](texts, hashes, cache, stats)
    hashes = dict(hashes)
    if extended:
        for path, item in extended.items():
            if path not in records and path not in texts:
                records[path] = item["record"]
                hashes[path] = item["sha256"]
        stats["extended_files"] = len(extended)
    states, loadable = {}, set(extended or ())
    if structural and config.get("structural_records", True):
        lexical = (config.get("oversized") or {}).get("lexical", True)
        references = (config.get("oversized") or {}).get("references", False)
        for path, item in structural.items():
            if path in records or path in texts:
                continue
            record = item.get("record")
            if record is None:
                states[path] = item["coverage"]
                continue
            if lexical and not record.get("structural"):
                records[path] = record if references else dict(record, reference_edges=False)
                loadable.add(path)
            else:
                records[path] = dict(record, terms={}, len=0, structural=True, coverage="structural_only")
            hashes[path] = item["sha256"]
        stats["structural_files"] = sum(1 for r in records.values() if r.get("structural"))
    history_stats = dict(history_stats or {})
    if partners is None and history and config["git"]["enabled"]:
        commits = facts["parse_git_log"](history, set(records) | set(path_only), config["git"]["max_commit_files"])
        partners = facts["cochange"](commits, min_support=config["git"]["min_support"],
                                     half_life_days=config["git"]["half_life_days"],
                                     statistic=config["git"].get("statistic", "jaccard"),
                                     shrinkage=config["git"].get("shrinkage", 0.0), stats=history_stats)
        stats["history_commits"] = len(commits)
    index = facts["RepoIndex"](records, kind_of, partners if config["git"]["enabled"] else None, path_only)
    index.history_stats = history_stats if config["git"]["enabled"] else {}
    index.texts = LazyTexts(texts, loader, loadable) if loader is not None and loadable else texts
    index.coverage = {path: record.get("coverage", "structural_only" if record.get("structural") else "complete")
                      for path, record in records.items()}
    index.coverage.update({path: states.get(path, "structural_only") for path in index.path_only})
    index.hashes = hashes
    index.extended = set(extended or ())
    stats["index_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return index


def run(task, index, config=None, *, anchors=None, explorer=None, findings=None, iteration=1, **options):
    """Retrieve, optionally explore, then budget. Returns ranking, packet and a full trace."""
    config = config or STRATEGIES["full"]
    budget = _sibling("context_budget")

    def packet_of(result):
        return budget["build_packet"](result["ranked"], index, result["query"], config,
                                      anchors={**frame_anchors(result["query"], index, config), **(anchors or {})})

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
    stale = getattr(index.texts, "failed", ())
    if stale and "status" in result:  # Indexed files whose current bytes no longer match were withheld while budgeting.
        index.coverage = {**getattr(index, "coverage", {}), **dict.fromkeys(stale, "stale")}
        result["status"]["conditions"] = [_coverage(index)] + [c for c in result["status"]["conditions"] if c["condition"] != "partial_coverage"]
    starved = [item["path"] for item in result["packet"]["dropped"] if item["reason"] == "byte budget"]
    if starved and "status" in result:
        result["status"]["conditions"].append({"condition": "budget_exhausted", "dropped_for_bytes": len(starved)})
    return result


# ---------------------------------------------------------------- explainability


def render_query(query):
    lines = ["IDENTIFIERS"] + [f"  {v}" for v in query["paths"] + query["dotted"] + query["symbols"] + query["identifiers"]]
    if query.get("frames"):
        lines += ["", "TRACEBACK FRAMES"] + [f"  {f['path']}:{f['line']}" + (f" in {f['function']}" if f["function"] else "") + (" (innermost)" if f["innermost"] else "")
                                             for f in query["frames"]]
    lines += ["", "CONCEPT TERMS"] + [f"  {v}" for v in query["concept_terms"]]
    lines += ["", "IGNORED/LOW-WEIGHT TERMS"] + [f"  {v}" for v in query["generic_terms"]]
    if query["phrases"]:
        lines += ["", "QUOTED LITERALS"] + [f"  {v}" for v in query["phrases"]]
    if query.get("calibration"):
        lines += ["", "NAME CALIBRATION (capitalization-only names, weighed by what they denote)"]
        lines += [f"  {name}: weight {c['weight']:.2f} ({c['reason']}; defines {c['defines']}, family {c['family']}, mentions {c['mentions']})"
                  for name, c in query["calibration"].items()]
    return "\n".join(lines)


def render_explain(result, verbose=False, top=10):
    query, trace, packet = result["query"], result["trace"], result.get("packet")
    kept = {item["path"] for item in packet["files"]} if packet else set()
    dropped = {item["path"]: item["reason"] for item in packet["dropped"]} if packet else {}
    lines = ["QUERY ANALYSIS", render_query(query)]
    plan, status = result.get("plan"), result.get("status")
    if plan:
        assistance = plan["families"]["assistance"]
        lines += ["", f"PLAN               profile {plan['profile']} ({', '.join(plan['reasons'])}); policy {plan['policy']}",
                  f"                   deterministic: {', '.join(plan['families']['deterministic'])}"
                  + (f"; supplied: {', '.join(plan['families']['supplied'])}" if plan["families"]["supplied"] else ""),
                  f"                   expansion: graph {'on' if plan['families']['expansion']['graph'] else 'off'}, "
                  f"git {'on' if plan['families']['expansion']['git'] else 'off'} ({plan['caps']['git']['statistic']}, "
                  f"support >= {plan['caps']['git']['min_support']}); reranker {assistance['reranker']} ({assistance['reranker_policy']}); "
                  f"explorer {assistance['explorer']}",
                  f"                   names: case-only {plan['caps']['names']['case_only']}, slash words {plan['caps']['names']['slash_words']}"]
    if status:
        conditions = "; ".join(", ".join(f"{k} {v}" for k, v in c.items()) for c in status["conditions"]) or "none"
        lines.append(f"STATUS             {status['status']} ({status['evidence']} evidence); conditions: {conditions}")
    lines += ["", "TOP FILES"]
    for row in result["ranked"][:top]:
        state = "in context" if row["path"] in kept else "not in context: " + dropped.get(row["path"], "below file limit")
        lines.append(f"{row['rank']}. {row['path']}  [{row['kind']}; fused {row['score']}; {state}]")
        lines += [f"   + {e['source']} rank #{e['rank']}: {e['reason']} ({e['value']})" + (f" - {e['detail']}" if e.get("detail") else "")
                  for e in row["evidence"]]
        if verbose and row["path"] in result.get("roles", {}):
            lines.append("   ~ role summary (model-written retrieval aid): " + result["roles"][row["path"]])
    request = (result.get("llm") or {}).get("request")
    if request:
        lines += ["", "RERANK REQUEST (host step: order these candidates for the request above, then run "
                      "`retrieval.py rerank` with --ranking '{\"ranking\": [{\"id\": \"C..\", \"label\": \"primary|supporting|weak\", "
                      "\"reason\": \"...\"}, ...]}'; only supplied ids count)", request]
    memory = result.get("memory")
    if memory:
        lines += ["", f"MEMORY ({memory['status']})"]
        lines += [f"   {name}: mode {entry['mode']}, {entry['state']} - {entry['reason']}" for name, entry in memory.get("layers", {}).items()]
        lines += [f"   {'+' if hit.get('applied') else '~'} {hit['kind']} {hit['id'][:12]}: {hit['why']}; {hit['evidence'][:80]} [{hit['label'][:60]}]"
                  for hit in memory.get("hits", [])]
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
        for stage, effect in (trace.get("displacement") or {}).items():
            introduced = ", ".join(f"{i['path']} ({'/'.join(i['sources'])})" for i in effect["introduced"]) or "none"
            lines.append(f"{stage.upper() + ' EFFECT':<19}top {effect['window']}: introduced {introduced}; "
                         f"displaced {', '.join(effect['displaced']) or 'none'}; moved {effect['moved']}")
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
        result = {key: result[key] for key in ("query", "plan", "status", "ranked", "trace", "packet", "exploration", "llm", "roles", "memory")
                  if key in result}
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(render_explain(result, args.verbose))
        print("\n" + _sibling("context_budget")["render_packet"](result["packet"]) if args.verbose else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
