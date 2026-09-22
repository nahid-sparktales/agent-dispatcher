#!/usr/bin/env python3
"""Mine a file-localization dataset from a local clone. Dataset generation only.

This is the one retrieval-benchmark step that may use the network (`--github OWNER/REPO`
reads public PR/issue text through an authenticated `gh` CLI, cached on disk). `run.py`
evaluates the resulting JSONL completely offline. Nothing from the mined repository is
executed: only `git` metadata is read.

A task is one first-parent commit (squash commit or PR merge). Its query is the linked
issue text when one exists, else the PR text, else the commit message. Its targets are the
non-test source files the change *modified*; files it added cannot be located in the parent
tree and are recorded separately, as are modified tests.

Two outputs. The *manifest* (committed) pins every task without any third-party text: ids,
commits, PR/issue numbers, targets and splits. The *dataset* (git-ignored, under dist/) adds the
query text. `--hydrate MANIFEST` rebuilds the dataset from a manifest, so the benchmark is
reproducible without redistributing other people's issue and PR descriptions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".rb",
                   ".c", ".h", ".cpp", ".cs", ".swift", ".kt", ".php"}
SKIP_SUBJECT = re.compile(r"^(?:bump|release|version|chore\(release\)|revert|update changelog|\[pre-commit|v?\d+\.\d+)", re.I)
LINKED_ISSUE = re.compile(r"\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\s*:?\s+(?:[\w.-]+/[\w.-]+)?#(\d+)", re.I)
PR_NUMBER = re.compile(r"(?:\(#(\d+)\)\s*$|^Merge pull request #(\d+)\b)")
MAX_QUERY_CHARS = 6000
MIN_QUERY_CHARS = 30
MAX_TARGETS = 5
SPLITS = ("train",) * 6 + ("validation",) * 2 + ("test",) * 2


def split_of(task_id):
    """Deterministic 60/20/20 split from the task id alone; never from its content or results."""
    return SPLITS[int(hashlib.sha256(task_id.encode("utf-8")).hexdigest(), 16) % len(SPLITS)]


def is_test(path):
    pure = PurePosixPath(path)
    return bool({"tests", "test", "__tests__", "testing"} & set(pure.parts[:-1])
                or re.search(r"(?:^test[_-]|[_-]test\.|\.(?:test|spec)\.|^conftest\.py$)", pure.name))


def _git(repo, *args):
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, errors="replace", check=False)
    return done.stdout if done.returncode == 0 else None


def _github(slug, kind, number, cache):
    """Public PR/issue title and body through `gh`, cached so re-mining needs no network."""
    path = cache / f"{slug.replace('/', '__')}-{kind}-{number}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    done = subprocess.run(["gh", "api", f"repos/{slug}/{kind}/{number}"], capture_output=True, text=True, check=False)
    data = None
    if done.returncode == 0:
        raw = json.loads(done.stdout)
        data = {"title": raw.get("title") or "", "body": raw.get("body") or "", "is_pr": "pull_request" in raw or kind == "pulls"}
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def _clean(text):
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)  # PR-template comments
    text = re.sub(r"^\s*[-*] \[[ xX]\].*$", " ", text, flags=re.M)  # PR-template checklists
    text = re.sub(r"\(#\d+\)", " ", text)
    text = re.sub(r"^(?:Co-authored-by|Signed-off-by):.*$", " ", text, flags=re.M | re.I)
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:MAX_QUERY_CHARS]


def query_text(repo, github, cache, sha, number=None, linked=None, origin=None):
    """(query, source, pr, issue). With `origin` given (hydration) the recorded source is used as is."""
    message = _git(repo, "show", "-s", "--format=%B", sha) or ""
    query, source, issue_number = _clean(message), "commit", None
    if number is None and origin is None:
        number = next((g for m in [PR_NUMBER.search(message.split("\n", 1)[0])] if m for g in m.groups() if g), None)
    if github and number and origin != "commit":
        pull = _github(github, "pulls", number, cache)
        if pull:
            query, source = _clean(pull["title"] + "\n\n" + pull["body"]), "pr"
            candidates = [linked] if linked else LINKED_ISSUE.findall(pull["body"] + "\n" + message)[:1]
            for found in candidates if origin in (None, "issue") else ():
                issue = _github(github, "issues", found, cache)
                if issue and not issue["is_pr"] and len(issue["body"]) >= MIN_QUERY_CHARS:
                    query, source, issue_number = _clean(issue["title"] + "\n\n" + issue["body"]), "issue", found
    return query, source, number, issue_number


def mine(repo, name, url, github=None, scan=800, limit=150, cache=None):
    commits = (_git(repo, "log", "--first-parent", f"-n{scan}", "--format=%H") or "").split()
    tasks = []
    for sha in commits:
        if len(tasks) >= limit:
            break
        parent = (_git(repo, "rev-parse", "--verify", "--quiet", sha + "^1") or "").strip()
        if not parent or _git(repo, "cat-file", "-e", parent + "^{tree}") is None:
            continue  # shallow boundary
        subject = (_git(repo, "show", "-s", "--format=%s", sha) or "").strip()
        if SKIP_SUBJECT.search(subject):
            continue
        status = _git(repo, "diff", "--name-status", "--no-renames", "-z", parent, sha)
        if status is None:
            continue
        fields = status.split("\0")[:-1]
        changed = list(zip(fields[::2], fields[1::2]))
        source = [(s, p) for s, p in changed if PurePosixPath(p).suffix.lower() in SOURCE_SUFFIXES]
        targets = sorted(p for s, p in source if s == "M" and not is_test(p))
        if not 1 <= len(targets) <= MAX_TARGETS:
            continue
        query, origin, number, issue = query_text(repo, github, cache, sha)
        if len(query) < MIN_QUERY_CHARS:
            continue
        task_id = f"{name}-{sha[:10]}"
        tasks.append({"id": task_id, "repo": name, "url": url, "base_commit": parent, "fix_commit": sha,
                      "split": split_of(task_id), "query_source": origin, "pr": number, "issue": issue, "query": query,
                      "target_files": targets,
                      "test_files": sorted(p for s, p in source if s == "M" and is_test(p)),
                      "added_files": sorted(p for s, p in source if s == "A"),
                      "names_target": any(PurePosixPath(t).name in query for t in targets)})
    return tasks


def hydrate(manifest, repo, github, cache):
    """Rebuild query text for pinned tasks: from the clone for commits, from GitHub (or its cache) otherwise."""
    tasks = []
    for line in Path(manifest).read_text(encoding="utf-8").splitlines():
        task = json.loads(line)
        query, origin, _, _ = query_text(repo, github, cache, task["fix_commit"], task.get("pr"), task.get("issue"), task["query_source"])
        if origin != task["query_source"]:
            print(f"{task['id']}: {task['query_source']} text unavailable, skipped", file=sys.stderr)
            continue
        tasks.append(dict(task, query=query))
    return tasks


def write(tasks, out, manifest=None):
    for path, rows in ((out, tasks), (manifest, [{k: v for k, v in task.items() if k != "query"} for task in tasks])):
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, help="Local clone with history")
    parser.add_argument("--name", help="Short repository id used in task ids (mining)")
    parser.add_argument("--url", help="Upstream URL recorded for reproducibility (mining)")
    parser.add_argument("--github", help="OWNER/REPO: read PR/issue text through the gh CLI (network unless cached)")
    parser.add_argument("--scan", type=int, default=800, help="First-parent commits to consider")
    parser.add_argument("--limit", type=int, default=150, help="Tasks to keep")
    parser.add_argument("--cache", default="dist/retrieval-cache/github", help="Where fetched PR/issue text is cached")
    parser.add_argument("--hydrate", metavar="MANIFEST", help="Rebuild a dataset from a committed manifest instead of mining")
    parser.add_argument("--manifest", help="Also write the text-free manifest here (mining)")
    parser.add_argument("--out", required=True, help="Dataset with query text; keep it under the git-ignored dist/")
    args = parser.parse_args(argv)
    if args.hydrate:
        tasks = hydrate(args.hydrate, Path(args.repo), args.github, Path(args.cache))
        write(tasks, args.out)
    else:
        if not args.name or not args.url:
            parser.error("--name and --url are required when mining")
        tasks = mine(Path(args.repo), args.name, args.url, args.github, args.scan, args.limit, Path(args.cache))
        write(tasks, args.out, args.manifest)
    by = {}
    for task in tasks:
        by[(task["split"], task["query_source"])] = by.get((task["split"], task["query_source"]), 0) + 1
    print(f"{len(tasks)} tasks -> {args.out}")
    for key in sorted(by):
        print(f"  {key[0]:<11}{key[1]:<7}{by[key]}")
    return 0 if tasks else 1


if __name__ == "__main__":
    raise SystemExit(main())
