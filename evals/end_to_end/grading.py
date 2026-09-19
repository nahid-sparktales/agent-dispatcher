"""Fixture loading and independent, bounded artifact grading (Python 3.10+).

Candidate Python is never imported into the runner. A private evaluator executes
on a disposable artifact copy in a child process with an explicit small environment.
This is process separation, not an adversarial security sandbox.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

DEFAULT_SUITE = Path(__file__).resolve().parent / "fixtures" / "manifest.json"
DIMENSIONS = ("correctness", "completeness", "scope", "unsupported_claims", "unnecessary_intervention")
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TREE_BYTES = 50 * 1024 * 1024


def _inside(root: Path, value: str) -> Path:
    rel = Path(value)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"Path must remain inside fixture: {value}")
    candidate = root / rel
    cursor = candidate
    while cursor != root:
        if cursor.is_symlink():
            raise ValueError(f"Symlink is not an allowed fixture path: {value}")
        cursor = cursor.parent
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes fixture: {value}")
    return resolved


def tree_digest(root: Path) -> str:
    """Hash regular files by relative name and content; reject special files."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Artifact source must be a regular directory")
    digest = hashlib.sha256()
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlink is not permitted: {path.relative_to(root)}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"Special file is not permitted: {path.relative_to(root)}")
        size = path.stat().st_size
        total += size
        if size > MAX_FILE_BYTES or total > MAX_TREE_BYTES:
            raise ValueError("Fixture/artifact exceeds size limit")
        name = path.relative_to(root).as_posix().encode()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def load_suite(path: Path | None = None) -> list[dict]:
    """Read manifest v1. Only source_dir is supplied to the evaluated agent."""
    path = Path(path or DEFAULT_SUITE).resolve()
    if path.is_dir():
        path = path / "manifest.json"
    data = json.loads(path.read_text())
    if data.get("schema_version") != 1 or not isinstance(data.get("fixtures"), list):
        raise ValueError("Expected fixture manifest schema_version=1 and fixtures array")
    result, ids = [], set()
    for raw in data["fixtures"]:
        item = dict(raw)
        task_id = item.get("id", "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", task_id) or task_id in ids:
            raise ValueError(f"Invalid or duplicate fixture id: {task_id}")
        ids.add(task_id)
        for field in ("category", "prompt", "source_dir", "acceptance", "rubric", "checks"):
            if field not in item:
                raise ValueError(f"Fixture {task_id} missing {field}")
        if not isinstance(item["prompt"], str) or not item["prompt"].strip():
            raise ValueError(f"Fixture {task_id} requires a prompt")
        if not isinstance(item["acceptance"], list) or not item["acceptance"] or not all(isinstance(x, str) for x in item["acceptance"]):
            raise ValueError(f"Fixture {task_id} requires acceptance descriptions")
        if not isinstance(item["rubric"], dict) or set(item["rubric"]) != set(DIMENSIONS):
            raise ValueError(f"Fixture {task_id} requires all five rubric dimensions")
        timeout = item.get("timeout_seconds", 600)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 3600:
            raise ValueError(f"Fixture {task_id} invalid timeout_seconds")
        item["timeout_seconds"] = timeout
        for field in ("smoke", "human_required"):
            if not isinstance(item.get(field), bool):
                raise ValueError(f"Fixture {task_id} requires boolean {field}")
        source = _inside(path.parent, item["source_dir"])
        item["source_dir"] = str(source)
        source_digest = tree_digest(source)
        item["source_digest"] = source_digest
        if not isinstance(item["checks"], list) or not item["checks"]:
            raise ValueError(f"Fixture {task_id} requires objective checks")
        checks = []
        for check in item["checks"]:
            check = dict(check)
            if not isinstance(check.get("name"), str):
                raise ValueError("Each check requires a name")
            if check.get("kind") == "python":
                script = _inside(path.parent, check["script"])
                if not script.is_file() or script.is_relative_to(source):
                    raise ValueError("Private evaluator must exist outside source_dir")
                check["script"] = str(script)
            elif check.get("kind") == "unchanged":
                if not isinstance(check.get("paths"), list) or not check["paths"]:
                    raise ValueError("unchanged check requires paths")
                if "no_extra_files" in check and not isinstance(check["no_extra_files"], bool):
                    raise ValueError("no_extra_files must be a boolean")
                for relative in check["paths"]:
                    if not _inside(source, relative).is_file():
                        raise ValueError(f"Missing protected source file: {relative}")
            elif check.get("kind") == "required_files":
                for relative in check["paths"]:
                    _inside(source, relative)
            else:
                raise ValueError(f"Unsupported check kind: {check.get('kind')}")
            checks.append(check)
        item["checks"] = checks
        if "references_dir" in item:
            references = _inside(path.parent, item["references_dir"])
            if references.is_relative_to(source) or not references.is_dir():
                raise ValueError("Reference examples must exist outside source_dir")
            item["references_dir"] = str(references)
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode())
        digest.update(source_digest.encode())
        for check in checks:
            if check["kind"] == "python":
                digest.update(Path(check["script"]).read_bytes())
        item["fixture_digest"] = digest.hexdigest()
        result.append(item)
    return result


def _run_check(script: Path, final_dir: Path, answer: str, timeout: float = 10.0) -> list[dict]:
    # Run the trusted evaluator outside the candidate working directory. The
    # subprocess is the only process that imports generated candidate modules.
    with tempfile.TemporaryDirectory(prefix="dispatcher-grade-") as tmp:
        root = Path(tmp)
        candidate = root / "candidate"
        shutil.copytree(final_dir, candidate)
        answer_path = root / "answer.txt"
        answer_path.write_text(answer)
        env = {"PATH": os.defpath, "TMPDIR": str(root), "PYTHONHASHSEED": "0"}
        from .runtime import execute
        run = execute([sys.executable, "-I", str(Path(__file__).resolve()), "_worker", str(script), str(candidate), str(answer_path)],
                      cwd=candidate, env=env, prompt="", timeout=timeout, output_limit=100_000)
        if run["timed_out"]:
            return [{"name": "evaluator_timeout", "passed": False, "detail": f"Independent grader exceeded {timeout:g}s"}]
        if run["output_overflow"]:
            return [{"name": "evaluator_output", "passed": False, "detail": "Independent grader exceeded output limit"}]
        if run["returncode"]:
            return [{"name": "evaluator_process", "passed": False, "detail": f"Independent grader exited with status {run['returncode']}"}]
        output = run["stdout"]
        try:
            checks = json.loads(output)
            if not isinstance(checks, list) or not checks:
                raise ValueError("empty checks")
            for check in checks:
                if not isinstance(check, dict) or not isinstance(check.get("name"), str) or not isinstance(check.get("passed"), bool) or not isinstance(check.get("detail"), str):
                    raise ValueError("invalid check result")
            return checks
        except (ValueError, UnicodeDecodeError):
            return [{"name": "evaluator_output", "passed": False, "detail": "Independent grader returned invalid structured results"}]


def grade(fixture: dict, final_dir: Path, final_answer: str) -> dict:
    """Grade a frozen final artifact, keeping human judgments explicitly separate."""
    final_dir = Path(final_dir)
    results = []
    try:
        tree_digest(final_dir)
        for check in fixture["checks"]:
            kind = check["kind"]
            if kind == "python":
                results.extend(_run_check(Path(check["script"]), final_dir, final_answer))
            elif kind == "unchanged":
                bad = []
                for relative in check["paths"]:
                    actual = _inside(final_dir, relative)
                    expected = _inside(Path(fixture["source_dir"]), relative)
                    if not actual.is_file() or actual.read_bytes() != expected.read_bytes():
                        bad.append(relative)
                if check.get("no_extra_files", False):
                    source_files = {p.relative_to(Path(fixture["source_dir"])).as_posix() for p in Path(fixture["source_dir"]).rglob("*") if p.is_file()}
                    bad.extend("added:" + p.relative_to(final_dir).as_posix() for p in final_dir.rglob("*") if p.is_file() and p.relative_to(final_dir).as_posix() not in source_files)
                results.append({"name": check["name"], "passed": not bad, "detail": "Protected files preserved" if not bad else "Changed or missing protected files: " + ", ".join(bad)})
            elif kind == "required_files":
                missing = [relative for relative in check["paths"] if not _inside(final_dir, relative).is_file()]
                results.append({"name": check["name"], "passed": not missing, "detail": "Required files present" if not missing else "Missing files: " + ", ".join(missing)})
            else:
                raise ValueError(f"Unknown check kind: {kind}")
    except (OSError, ValueError, KeyError) as error:
        results.append({"name": "artifact_validation", "passed": False, "detail": str(error)})
    return {"passed": bool(results) and all(check["passed"] for check in results), "checks": results, "human_required": fixture["human_required"]}


def _worker(script: str, candidate: str, answer_path: str) -> None:
    # Limits cover common accidental hangs/output explosions; this is not a sandbox.
    if os.name == "posix":
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
        resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
    import contextlib
    import runpy
    class DiscardWriter:
        def write(self, value):
            return len(value)
        def flush(self):
            pass
    with contextlib.redirect_stdout(DiscardWriter()), contextlib.redirect_stderr(DiscardWriter()):
        scope = runpy.run_path(script)
        checks = scope["checks"](Path(candidate), Path(answer_path).read_text())
        results = []
        for name, callback in checks:
            try:
                callback()
                results.append({"name": name, "passed": True, "detail": "Acceptance check passed"})
            except Exception as error:
                results.append({"name": name, "passed": False, "detail": type(error).__name__ + ": " + str(error)[:1000]})
    print(json.dumps(results))


if __name__ == "__main__" and len(sys.argv) == 5 and sys.argv[1] == "_worker":
    _worker(*sys.argv[2:])
