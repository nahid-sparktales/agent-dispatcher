"""Validate current facts as well as citation identity; hashes alone are insufficient."""
import hashlib
import json
from pathlib import PurePosixPath


def checked_evidence(root, evidence, paths, anchor):
    assert set(evidence) == {"path", "start_line", "end_line", "quote", "sha256"}
    path = evidence["path"]
    assert isinstance(path, str) and path in paths
    relative = PurePosixPath(path)
    assert not relative.is_absolute() and ".." not in relative.parts
    source = root / path
    assert source.is_file() and not source.is_symlink()
    raw = source.read_bytes()
    lines = raw.decode("utf-8").splitlines()
    first, last = evidence["start_line"], evidence["end_line"]
    assert type(first) is int and type(last) is int
    assert 1 <= first <= last <= len(lines) and last - first < 12
    quote = "\n".join(lines[first - 1:last])
    assert evidence["quote"] == quote and anchor in quote
    assert evidence["sha256"] == hashlib.sha256(raw).hexdigest()


def checks(root, answer):
    report = json.loads((root / "docs/PROJECT_MAP.json").read_text())

    def shape():
        assert set(report) == {"schema_version", "entries"}
        assert type(report["schema_version"]) is int and report["schema_version"] == 1
        assert isinstance(report["entries"], list) and len(report["entries"]) == 4
        assert {row["id"] for row in report["entries"]} == {
            "entrypoint", "max_attempts", "retry_exception", "test_command"}
        assert all(set(row) == {"id", "value", "evidence"} for row in report["entries"])

    def current_facts_and_sources():
        expected = {
            "entrypoint": ("service.worker:run_job", {"service/worker.py"}, "def run_job("),
            "max_attempts": (4, {"service/policy.py"}, "MAX_ATTEMPTS = 4"),
            "retry_exception": ("TemporaryFailure", {"service/worker.py"}, "except TemporaryFailure:"),
            "test_command": ("python3 -m unittest discover -s tests", {"Makefile"},
                             "python3 -m unittest discover -s tests"),
        }
        for row in report["entries"]:
            value, paths, anchor = expected[row["id"]]
            assert type(row["value"]) is type(value) and row["value"] == value
            checked_evidence(root, row["evidence"], paths, anchor)

    return [("complete_unique_map", shape), ("current_facts_and_source_citations", current_facts_and_sources)]
