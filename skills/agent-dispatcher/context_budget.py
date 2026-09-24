"""Context engine: fit ranked repository evidence into an explicit byte/token/file budget.

Input is a ranking with provenance (retrieval.py) and the facts index (repo_index.py). Output
is the smallest packet that still says where to look and why: per file its selection reasons,
the symbols that matched, relationships to the other selected files, and bounded excerpts
around definitions, references and rare terms. The budget counts the whole rendered packet.
"""
from __future__ import annotations

import math
import re

HEADER = "REPOSITORY CONTEXT\n==================\n"
MIN_USEFUL_BYTES = 120  # Below this, a file section has no room left for an excerpt.
# Strongest link first: when two files are related several ways, only the first of these is shown.
_RELATION_WORDS = {"tested_by": "tested by", "tests": "tests", "calls": "calls", "called_by": "called by",
                   "inherits": "inherits from", "inherited_by": "inherited by", "references": "references",
                   "referenced_by": "referenced by", "imports": "imports", "imported_by": "imported by"}


def _signals(query, index):
    """What the request named, limited to names that resolve inside the retrieval universe."""
    known = lambda value: any(p == value.lstrip("./") or p.endswith("/" + value.lstrip("./")) for p in index.paths)  # noqa: E731
    resolves = lambda value: any(index.module_path(".".join(value.split(".")[:end])) for end in range(len(value.split(".")), 0, -1))  # noqa: E731
    signals = {"paths": [v for v in query["paths"] if known(v)][:4], "modules": [v for v in query["dotted"] if resolves(v)][:4],
               "symbols": (query["symbols"] + query["identifiers"])[:8], "concepts": query["concept_terms"][:8]}
    return {key: value for key, value in signals.items() if value}


def _lines(index, path):
    """A file's lines. A partially indexed file ends at its last covered line: its text keeps that line's newline, so a
    plain split would add an empty line N+1 where the real file has content that was never read."""
    lines = index.texts[path].split("\n")
    covered = index.records.get(path, {}).get("covered_lines")
    return lines[:covered[1]] if covered else lines


def _spans(row, index, query, config, anchor):
    """Candidate excerpt windows for one file, best first: (priority, start, end, center), 1-based lines."""
    tuning = config["context"]
    path = row["path"]
    lines = _lines(index, path)
    record = index.records[path]
    radius, spans = tuning["radius"], []

    def around(priority, line):
        spans.append((priority, max(1, line - radius), min(len(lines), line + radius), line))

    if anchor and anchor <= len(lines):
        around(0, anchor)
    if not tuning["optimizer"]:
        # Pre-optimizer behavior, kept for ablation: windows around the first lines mentioning any request term.
        terms = [t.lower() for t in query["terms"]]
        hits = [n for n, line in enumerate(lines, 1) if any(t in line.lower() for t in terms)][:3]
        if anchor and anchor <= len(lines):
            hits = [anchor]
        return [(1, max(1, n - 8), min(len(lines), n + 8), n) for n in hits] or [(4, 1, min(len(lines), 17), 1)]
    wanted = query["symbol_names"]
    for name, _, line, end, _ in record["defs"]:
        if name in wanted:
            spans.append((1, max(1, line - 1), min(end, line + tuning["max_definition_lines"] - 1, len(lines)), line))
    for phrase in query["phrases"]:
        hit = next((n for n, line in enumerate(lines, 1) if phrase in line), None)
        if hit:
            around(1, hit)
    floor = config["query_weights"]["identifier"]
    for name, weight in wanted.items():
        if weight >= floor and name in record["terms"]:
            pattern = re.compile(r"(?<![\w])" + re.escape(name) + r"(?![\w])")
            for hit in [n for n, line in enumerate(lines, 1) if pattern.search(line)][:2]:
                around(2, hit)
    rare = sorted((t for t in query["terms"] if t in record["terms"]),
                  key=lambda t: (-index.idf(t) * query["terms"][t], t))[:3]
    for term in rare:
        hit = next((n for n, line in enumerate(lines, 1) if term in line.lower()), None)
        if hit:
            around(3, hit)
    spans.append((4, 1, min(len(lines), 2 * radius), 1))
    merged = []
    for priority, start, end, center in sorted(set(spans), key=lambda s: (s[0], s[1])):
        clash = next((i for i, (_, a, b, _) in enumerate(merged) if start <= b + 1 and end >= a - 1), None)
        if clash is None:
            merged.append((priority, start, end, center))
        elif priority > 1 or merged[clash][0] > 1:  # Never grow a definition span past its cap.
            old = merged[clash]
            merged[clash] = (min(old[0], priority), min(old[1], start), max(old[2], end), old[3])
    merged = [span for span in merged if span[0] < 4] or merged
    return merged[:tuning["max_excerpts_per_file"]]


def _fit(lines, start, end, center, available, cost):
    """Largest whole-line window inside [start, end] around `center` whose cost fits; None if no line fits."""
    if cost(lines, start, end) <= available:
        return start, end
    low = high = min(max(center, start), end)
    if cost(lines, low, high) > available:
        return None
    while True:
        if low > start and cost(lines, low - 1, high) <= available:
            low -= 1
        elif high < end and cost(lines, low, high + 1) <= available:
            high += 1
        else:
            return low, high


def _relationships(path, index, nearby):
    """One line per related file already near the top of the ranking, strongest kind of link first."""
    best = {}
    for other, kind, detail in index.neighbors(path):
        if other in nearby and kind in _RELATION_WORDS:
            order = list(_RELATION_WORDS).index(kind)
            if other not in best or order < best[other][0]:
                suffix = f" ({detail})" if isinstance(detail, str) and detail not in {"test name", "test import"} else ""
                best[other] = (order, f"{_RELATION_WORDS[kind]} {other}{suffix}")
    found = [(nearby[other], text) for other, (_, text) in best.items()]
    for other, score, _ in index.partners.get(path, ()):
        if other in nearby and other not in best:
            found.append((nearby[other], f"co-changes with {other} (jaccard {score})"))
    return [text for _, text in sorted(found)][:4]


def _section(item):
    lines = [f"{item['rank']}. {item['path']}", "Why selected:"] + [f"- {reason}" for reason in item["why"]]
    if item.get("note"):
        lines.append("Note: " + item["note"])
    if item["symbols"]:
        lines += ["Relevant symbols:"] + [f"- {symbol}" for symbol in item["symbols"]]
    if item["relationships"]:
        lines += ["Relationships:"] + [f"- {text}" for text in item["relationships"]]
    for excerpt in item["excerpts"]:
        lines.append(f"Relevant excerpt (lines {excerpt['lines']}):")
        lines += [f"  {number} | {line}" for number, line in enumerate(excerpt["content"].split("\n"), excerpt["start"])]
    return "\n".join(lines) + "\n\n"


def render_packet(packet):
    head = HEADER + "Task signals:\n" + "".join(
        f"- {label}: {', '.join(values)}\n" for label, values in packet["task_signals"].items()) + "\n"
    return head + "".join(_section(item) for item in packet["files"])


def build_packet(ranked, index, query, config, anchors=None):
    """Choose files (tests may not crowd out implementation), then spend the budget one excerpt per file first."""
    tuning, anchors = config["context"], anchors or {}
    limit = tuning["max_bytes"] if not tuning["max_tokens"] else min(tuning["max_bytes"], tuning["max_tokens"] * 4)
    max_files = tuning["max_files"]
    test_cap = max_files if query["wants"]["test"] or not tuning["optimizer"] else max(1, math.ceil(max_files * tuning["max_test_share"]))
    chosen, held, dropped, tests, contents = [], [], [], 0, {}
    for row in ranked:
        named = any(e["source"] == "named" for e in row["evidence"])
        content = index.hashes.get(row["path"]) if tuning["optimizer"] else None
        if len(chosen) >= max_files:
            reason = "file limit"
        elif not named and content is not None and content in contents:
            reason = "diversity: same content as " + contents[content]  # vendored or generated copies wait their turn
        elif not named and row["kind"] == "test" and tests >= test_cap:
            reason = "diversity: test share reached"
        else:
            chosen.append(row)
            tests += row["kind"] == "test"
            if content is not None:
                contents.setdefault(content, row["path"])
            continue
        (held if reason.startswith("diversity") else dropped).append({"path": row["path"], "reason": reason, "row": row})
    # Diversity only reorders: when nothing more varied wants the room, the held files take it back.
    while held and len(chosen) < max_files:
        chosen.append(held.pop(0)["row"])
    last = max((row["rank"] for row in chosen), default=0)
    for item in held:  # Diversity cost it the place only if a lower-ranked file was kept instead.
        if item["row"]["rank"] > last:
            item["reason"] = "file limit"
    chosen.sort(key=lambda row: row["rank"])
    dropped = [{"path": d["path"], "reason": d["reason"]} for d in sorted(held + dropped, key=lambda d: d["row"]["rank"])][:3 * max_files]
    nearby = {row["path"]: row["rank"] for row in ranked[:2 * max_files]}
    packet = {"task_signals": _signals(query, index), "files": [], "dropped": dropped,
              "budget": {"max_bytes": limit, "max_files": max_files, "counts": tuning["count"]}}
    whole = tuning["count"] == "packet"  # "excerpts" keeps the context helper's documented excerpt-only budget.
    used = len(render_packet(packet).encode("utf-8")) if whole else 0
    pending = []
    for row in chosen:
        path = row["path"]
        matched = [e["value"].rsplit(":", 1)[0].rsplit(".", 1)[-1] for e in row["evidence"] if e["source"] == "symbol_definitions"]
        in_file = index.symbols_in(path)
        symbols = list(dict.fromkeys(matched + [s for s in in_file if s in query["symbol_names"]]))[:5]
        item = {"path": path, "rank": row["rank"], "kind": row["kind"],
                "why": [f"{e['reason']}: {e['value']} ({e['source']} #{e['rank']})" for e in row["evidence"][:4]],
                "symbols": symbols, "relationships": _relationships(path, index, nearby), "excerpts": []}
        covered = index.records.get(path, {}).get("covered_lines")
        if path in index.path_only:
            item["note"] = "over the file read limit: ranked by name, imports and history only; open it directly"
        elif covered and path in index.texts:
            item["note"] = f"over the file read limit: only lines {covered[0]}-{covered[1]} were indexed and can be excerpted"
        elif covered:  # Its loader refused the bytes: stale, so nothing from the record's span is shown.
            item["note"] = "changed since it was indexed; excerpts withheld"
        spans = _spans(row, index, query, config, anchors.get(path)) if path in index.texts else []
        cost = len(_section(item).encode("utf-8")) if whole else 0
        if whole and used + cost + MIN_USEFUL_BYTES > limit:
            # A tight budget is spent on evidence first: keep one reason, drop the rest of the description.
            item.update(why=item["why"][:1], symbols=item["symbols"][:2], relationships=[])
            cost = len(_section(item).encode("utf-8"))
        if used + cost > limit or (whole and limit - used - cost < MIN_USEFUL_BYTES):
            packet["dropped"].append({"path": path, "reason": "byte budget"})
            continue
        packet["files"].append(item)
        used += cost
        pending.append((item, spans))
    lines_of = {item["path"]: _lines(index, item["path"]) for item, spans in pending if spans}

    def line_cost(lines, start, end):
        content = "\n".join(lines[start - 1:end])
        if not whole:
            return 4 * math.ceil(len(content) / 4)  # The helper budgets whole estimated tokens.
        width = sum(len(f"  {n} | ") for n in range(start, end + 1))
        return len(content.encode("utf-8")) + width + len(f"Relevant excerpt (lines {start}-{end}):\n") + 1

    for round_number in range(tuning["max_excerpts_per_file"]):
        waiting = sum(1 for _, spans in pending if round_number < len(spans))
        for item, spans in pending:
            if round_number >= len(spans):
                continue
            _, start, end, center = spans[round_number]
            lines = lines_of[item["path"]]
            # Breadth first: a file's first excerpt gets an equal share of what is left, so a tight budget
            # shrinks every window instead of starving the lower-ranked files. Later rounds spend the rest in rank order.
            available = max((limit - used) // waiting, MIN_USEFUL_BYTES) if round_number == 0 and tuning["optimizer"] else limit - used
            waiting -= 1
            window = _fit(lines, start, end, center, min(available, limit - used), line_cost)
            if window is None:
                continue
            start, end = window
            content = "\n".join(lines[start - 1:end])
            if not content.strip():
                continue
            if (start, end) != spans[round_number][1:3]:
                packet["trimmed"] = True
            # `order` is the admission round, so it follows the span's (priority, line); excerpts are shown by line below.
            item["excerpts"].append({"lines": f"{start}-{end}", "start": start, "end": end, "content": content, "order": round_number})
            used += line_cost(lines, start, end)
    for item in list(packet["files"]):
        if not item["excerpts"] and item["path"] in index.texts:
            packet["files"].remove(item)
            packet["dropped"].append({"path": item["path"], "reason": "byte budget"})
    for item in packet["files"]:
        item["excerpts"].sort(key=lambda excerpt: excerpt["start"])
    packet["bytes"] = len(render_packet(packet).encode("utf-8"))
    packet["tokens"] = math.ceil(packet["bytes"] / 4)
    return packet
