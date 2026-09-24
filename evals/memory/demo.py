#!/usr/bin/env python3
"""Offline repository-intelligence lifecycle on a tiny synthetic repository. No model, no network, no real state.

    python3 -B evals/memory/demo.py [--json]

One linear walkthrough with the shipped modules in a throwaway cache/config home: build a small repository and its
memory store, retrieve a behavior query and read the plan, status and co-change evidence, record a receipt-backed
observation and a second task, derive a scoped consolidation candidate, change the source, correct one episode,
forget the other, and check at each step that stale or withdrawn evidence stops influencing retrieval. The digest
operations are exercised last. Every outcome here is supplied or checked locally; the demo proves the machinery
and its refusals, never a benefit, and its synthetic records never leave the temporary home.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SESSIONS = '''from app.tokens import issue_token, rotate_token


class Session:
    def __init__(self, user):
        self.user = user
        self.token = issue_token(user)
        self.revoked = False


def create_session(user):
    return Session(user)


def revoke_session(session):
    session.revoked = True
    return session


def refresh_session(session):
    """Refresh keeps the session alive by rotating its token."""
    session.token = rotate_token(session.token)
    return session
'''
TOKENS = '''import hashlib


def issue_token(user):
    return hashlib.sha256(user.encode("utf-8")).hexdigest()[:16]


def rotate_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
'''
TESTS = '''import unittest

from app.sessions import create_session, refresh_session, revoke_session


class SessionTests(unittest.TestCase):
    def test_refresh_rotates_the_token(self):
        session = create_session("ada")
        before = session.token
        self.assertNotEqual(refresh_session(session).token, before)

    def test_revoke(self):
        self.assertTrue(revoke_session(create_session("ada")).revoked)
'''
TASK_A = "refresh_session drops the token when it expires; keep the session alive on refresh"
TASK_B = "token rotation in refresh must keep the session valid after rotate_token"


def git(project, *args):
    base = ["git", "-C", str(project), "-c", "user.email=demo@example.com", "-c", "user.name=demo", "-c", "commit.gpgsign=false"]
    return subprocess.run([*base, *args], check=True, capture_output=True, text=True).stdout.strip()


def make_repo(root):
    project = root / "sessions-demo"
    for path, text in {"app/__init__.py": "", "app/sessions.py": SESSIONS.replace("    session.token = rotate_token(session.token)\n", "    return session\n"),
                       "app/tokens.py": TOKENS, "tests/__init__.py": "", "tests/test_sessions.py": TESTS, "README.md": "# sessions demo\n"}.items():
        (project / path).parent.mkdir(parents=True, exist_ok=True)
        (project / path).write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(project)], check=True)
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "Initial sessions and tokens")
    (project / "app/sessions.py").write_text(SESSIONS, encoding="utf-8")
    (project / "app/tokens.py").write_text(TOKENS + "\n\ndef token_age(token):\n    return 0\n", encoding="utf-8")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "Rotate the token on refresh (#3)")
    (project / "app/sessions.py").write_text(SESSIONS + "\n\ndef session_age(session):\n    return 0\n", encoding="utf-8")
    (project / "app/tokens.py").write_text(TOKENS + "\n\ndef token_age(token):\n    return 1\n", encoding="utf-8")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "Age helpers for sessions and tokens")
    return project


def step(report, name, detail):
    report["steps"].append({"step": name, **detail})
    if not report["json"]:
        print(f"\n== {name}")
        for key, value in detail.items():
            print(f"  {key}: {value if isinstance(value, str) else json.dumps(value, default=str)}")


def run(home, report):  # noqa: C901 - one linear walkthrough
    import context, repository_memory as memory, retrieval, verification  # noqa: E401
    pack = context.find_pack(str(ROOT))
    config = home / "config" / "agent-dispatcher"
    config.mkdir(parents=True)
    (config / "repository-memory.json").write_text(json.dumps({"enabled": True, "git": {"retrieval": "on", "symbols": {"enabled": False}},
                                                              "experience": {"recording": True, "retrieval": "on"}}))
    project = make_repo(home / "repos")
    # 1. Build the memory store from eligible history: private state only, nothing in the working tree.
    built = memory.build(project, memory.load_settings(project=project), pack=pack)
    assert not (project / ".agent-dispatcher").exists() and git(project, "status", "--porcelain") == ""
    step(report, "build memory", {"action": built["action"], "events": built["events"], "workspace_clean": True})
    # 2. A behavior query: plan, status and co-change evidence with denominators, before anything was recorded.
    explained = context.explain_retrieval(project, TASK_A, pack=str(ROOT))
    text = retrieval.render_explain(explained, verbose=True)
    git_rows = [e for row in explained["ranked"] for e in row["evidence"] if e["source"] == "git"]
    assert explained["ranked"][0]["path"] == "app/sessions.py", explained["ranked"][:2]
    assert explained["plan"]["profile"] == "behavior" and explained["status"]["status"] == "ok"
    assert git_rows and "eligible events containing" in git_rows[0]["detail"], git_rows
    assert "EXPANSION EFFECT" in text
    step(report, "retrieve behavior query", {"top": [row["path"] for row in explained["ranked"][:3]], "plan": explained["plan"]["profile"],
                                             "reasons": explained["plan"]["reasons"], "status": explained["status"],
                                             "co_change_evidence": git_rows[0]["detail"], "memory_git": explained["memory"]["layers"]["git"]["state"]})
    # 3. A receipt-backed observation: verified success only from a passing, current run.
    receipt = home / "receipt.json"
    verification.run_check(project, receipt, [sys.executable, "-B", "-m", "unittest", "-q", "tests.test_sessions"], kind="tests", pack=str(ROOT))
    first = memory.record_experience(project, {"task": TASK_A, "modified": ["app/sessions.py"], "read": ["app/sessions.py", "app/tokens.py"]},
                                     pack=str(ROOT), receipt=str(receipt))
    assert first["outcome"] == "checked_success" and first["eligible"], first
    try:
        memory.record_experience(project, {"task": TASK_A, "modified": ["app/sessions.py"], "outcome": "checked_success"}, pack=str(ROOT))
        raise AssertionError("an asserted verified success must be refused")
    except memory.RepositoryMemoryError as exc:
        refused = str(exc)
    second = memory.record_experience(project, {"task": TASK_B, "modified": ["app/sessions.py", "app/tokens.py"], "outcome": "accepted",
                                                "assertions": [{"by": "user", "claim": "looks right"}]}, pack=str(ROOT))
    step(report, "record experience", {"first": {"outcome": first["outcome"], "verification": first["verification"]},
                                       "asserted_success_refused": refused, "second": second["outcome"]})
    # 4. A scoped consolidation candidate: two independent families, current evidence, no authority.
    candidates = memory.consolidate(project, task=TASK_A, pack=str(ROOT))
    assert candidates["status"] == "ok", candidates
    claim = candidates["candidates"][0]
    assert claim["scope"]["paths"] == ["app/sessions.py"] and claim["support"]["families"] == 2 and claim["scope_match"] == "exact"
    assert claim["freshness"]["state"] == "current" and claim["status"] == "candidate"
    used = context.select_context(project, TASK_A, pack=str(ROOT))
    assert used["memory"]["layers"]["experience"]["state"] == "use" and used["memory"]["layers"]["experience"]["applied"]
    step(report, "consolidate", {"claim": claim["claim"], "scope": claim["scope"]["module"], "support": claim["support"],
                                 "contradictions": claim["contradictions"]["events"], "freshness": claim["freshness"]["state"],
                                 "review": claim["review"]["promotion"], "experience_layer": used["memory"]["layers"]["experience"]["state"]})
    # 5. The source changes: the claim's evidence is no longer current and experience may only strengthen, not introduce.
    (project / "app/sessions.py").write_text(SESSIONS.replace("rotate_token(session.token)", "rotate_token(session.token)  # changed"), encoding="utf-8")
    stale = memory.consolidate(project, task=TASK_A, pack=str(ROOT))["candidates"][0]["freshness"]
    changed = context.select_context(project, TASK_A, pack=str(ROOT))["memory"]["layers"]["experience"]
    assert stale["state"] == "changed" and stale["changed"] == ["app/sessions.py"], stale
    assert changed["state"] == "use_limited", changed
    step(report, "source changed", {"claim_freshness": stale, "experience_layer": changed["state"], "reason": changed["reason"]})
    git(project, "checkout", "-q", "--", "app/sessions.py")
    # 6. Correct one episode: its support is withdrawn everywhere, the original keeps its text, nothing is resurrected.
    corrected = memory.correct_experience(project, second["record_id"], outcome="reverted_or_invalidated", note="rolled back in review", pack=str(ROOT))
    after_correction = memory.consolidate(project, task=TASK_A, pack=str(ROOT))
    assert after_correction["status"] == "no_candidates" and after_correction["supporting"] == 1, after_correction
    step(report, "correct episode", {"superseding": corrected["id"][:12], "candidates": after_correction["status"], "supporting": after_correction["supporting"]})
    # 7. Forget the other: no experience influence remains, the packet is the baseline packet again.
    forgotten = memory.forget_experience(project, first["record_id"])
    gone = memory.consolidate(project, pack=str(ROOT))
    plain = context.select_context(project, TASK_A, pack=str(ROOT))
    assert gone["status"] in ("no_candidates", "unavailable") and gone["supporting"] == 0
    assert plain["memory"]["layers"]["experience"]["candidates"] == 0, plain["memory"]["layers"]["experience"]
    assert [row["path"] for row in plain["context"]] == [row["path"] for row in context.select_context(project, TASK_A, pack=str(ROOT))["context"]]
    step(report, "forget episode", {"removed": forgotten["removed"], "candidates": gone["status"], "experience_candidates": 0})
    # 8. Working memory: explicit, task-local, verbatim, never read by retrieval.
    observations = [{"kind": "finding", "status": "confirmed", "text": "refresh_session lives in app/sessions.py", "evidence": ["app/sessions.py:19"]},
                    {"kind": "hypothesis", "status": "contradicted", "text": "the token is NOT rotated in app/tokens.py; rotation happens in refresh_session"},
                    {"kind": "question", "status": "pending", "text": "expiry handling not found in this bounded search; it may not exist"},
                    {"kind": "check", "status": "failed", "text": "tests.test_sessions failed before the fix", "evidence": ["tests/test_sessions.py"]}]
    digest = memory.working_memory(project, "demo-task", "record", observations=observations, objective="keep sessions alive on refresh",
                                   acceptance=["tests.test_sessions passes"], window=1, pack=str(ROOT))
    assert digest["digest"]["contradicted"][0]["text"].startswith("the token is NOT") and digest["digest"]["unresolved"]
    assert "refresh_session lives in" not in json.dumps(context.select_context(project, TASK_A, pack=str(ROOT)))  # never in a packet
    memory.working_memory(project, "demo-task", "forget", pack=str(ROOT))
    step(report, "working memory", {"recent": len(digest["recent"]), "digest": {k: len(v) for k, v in digest["digest"].items()}, "loss": digest["loss"]})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    home = Path(tempfile.mkdtemp(prefix="memory-demo-")).resolve()
    saved = {key: os.environ.get(key) for key in ("XDG_CACHE_HOME", "XDG_CONFIG_HOME", "AGENT_DISPATCHER_MEMORY_CONFIG")}
    os.environ["XDG_CACHE_HOME"], os.environ["XDG_CONFIG_HOME"] = str(home / "cache"), str(home / "config")
    os.environ.pop("AGENT_DISPATCHER_MEMORY_CONFIG", None)
    report = {"json": args.json, "steps": [], "isolated_home": str(home)}
    try:
        run(home, report)
        report["result"] = "complete"
    finally:
        shutil.rmtree(home, ignore_errors=True)
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    del report["json"]
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("\nDemo complete. Nothing outside the removed temporary home was touched; no benefit was measured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
