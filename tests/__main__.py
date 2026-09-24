#!/usr/bin/env python3
"""Run every repository test group with one command."""
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "tests.test_build",
    "tests.test_decision",
    "tests.test_release",
    "tests.test_codex",
    "tests.test_doctor",
    "tests.test_context",
    "tests.test_context_packet",
    "tests.test_context_reuse",
    "tests.test_parser_cache",
    "tests.test_incremental_context",
    "tests.test_cache_scope",
    "tests.test_project_map",
    "tests.test_project_graph",
    "tests.test_retrieval",
    "tests.test_retrieval_security",
    "tests.test_llm_retrieval",
    "tests.test_repository_index",
    "tests.test_experience",
    "tests.test_exploration",
    "tests.test_retrieval_sequence",
    "tests.test_repository_memory",
    "tests.test_memory_lifecycle",
    "tests.test_learning",
    "tests.test_learning_security",
    "tests.test_e2e",
    "tests.test_verification",
    "tests.test_change_audit",
    "tests.test_preferences",
    "tests.test_reporting_package",
)


def main():
    discovered = {f"tests.{path.stem}" for path in Path(__file__).parent.glob("test_*.py")}
    declared = set(MODULES)
    if discovered != declared:
        missing = sorted(discovered - declared)
        stale = sorted(declared - discovered)
        print(f"Test runner manifest mismatch; missing={missing}, stale={stale}", file=sys.stderr)
        return 2
    for module in MODULES:
        print(f"\n== {module} ==", flush=True)
        completed = subprocess.run(
            [sys.executable, "-B", "-m", module],
            cwd=ROOT,
            check=False,
        )
        if completed.returncode:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
