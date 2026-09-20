"""Score a specified structured report, not the wording of the final response."""
import hashlib
import json
from pathlib import PurePosixPath


def evidence(root, citation, path, anchors):
    assert set(citation) == {"path", "start_line", "end_line", "quote", "sha256"}
    assert citation["path"] == path
    relative = PurePosixPath(path)
    assert not relative.is_absolute() and ".." not in relative.parts
    source = root / path
    assert source.is_file() and not source.is_symlink()
    raw = source.read_bytes()
    lines = raw.decode("utf-8").splitlines()
    first, last = citation["start_line"], citation["end_line"]
    assert type(first) is int and type(last) is int
    assert 1 <= first <= last <= len(lines) and last - first < 12
    quote = "\n".join(lines[first - 1:last])
    assert citation["quote"] == quote and all(anchor in quote for anchor in anchors)
    assert citation["sha256"] == hashlib.sha256(raw).hexdigest()


def checks(root, answer):
    report = json.loads((root / "architecture.json").read_text())

    def shape():
        assert set(report) == {"schema_version", "entrypoint", "features", "edges",
                               "dependencies", "test_command", "decision"}
        assert type(report["schema_version"]) is int and report["schema_version"] == 1
        for key in ("entrypoint", "dependencies", "test_command"):
            assert set(report[key]) == {"value", "evidence"}
        assert len(report["features"]) == 2 and all(
            set(row) == {"id", "value", "evidence"} for row in report["features"])
        assert len(report["edges"]) == 4 and all(
            set(row) == {"from", "to", "evidence"} for row in report["edges"])
        assert set(report["decision"]) == {"id", "value", "status", "evidence"}

    def live_routes():
        assert report["entrypoint"]["value"] == "flowdesk.api:handle_request"
        evidence(root, report["entrypoint"]["evidence"], "flowdesk/api.py", ["def handle_request("])
        expected = {"list_tasks": ("GET /tasks", 'if method == "GET" and path == "/tasks":'),
                    "create_task": ("POST /tasks", 'if method == "POST" and path == "/tasks":')}
        assert {row["id"] for row in report["features"]} == set(expected)
        for row in report["features"]:
            value, branch = expected[row["id"]]
            assert row["value"] == value
            evidence(root, row["evidence"], "flowdesk/api.py", [branch])

    def direct_call_edges():
        expected = {
            ("handle_request", "TaskService.list_tasks"): ("flowdesk/api.py", "return service.list_tasks()"),
            ("handle_request", "TaskService.add_task"): ("flowdesk/api.py", "return service.add_task("),
            ("TaskService.list_tasks", "MemoryTaskStore.list_tasks"): ("flowdesk/service.py", "return self.store.list_tasks()"),
            ("TaskService.add_task", "MemoryTaskStore.add_task"): ("flowdesk/service.py", "return self.store.add_task("),
        }
        assert {(row["from"], row["to"]) for row in report["edges"]} == set(expected)
        for row in report["edges"]:
            path, anchor = expected[row["from"], row["to"]]
            evidence(root, row["evidence"], path, [anchor])

    def declared_metadata_and_accepted_decision():
        assert report["dependencies"]["value"] == ["typing-extensions>=4.8"]
        evidence(root, report["dependencies"]["evidence"], "pyproject.toml",
                 ['dependencies = ["typing-extensions>=4.8"]'])
        assert report["test_command"]["value"] == "python3 -m unittest discover -s tests -v"
        evidence(root, report["test_command"]["evidence"], "Makefile",
                 ["python3 -m unittest discover -s tests -v"])
        decision = report["decision"]
        assert (decision["id"], decision["value"], decision["status"]) == ("storage", "in-memory", "accepted")
        evidence(root, decision["evidence"], "docs/decisions/001-storage.md",
                 ["Status: accepted", "Backend: in-memory"])

    return [("report_structure", shape), ("current_entrypoint_and_features", live_routes),
            ("direct_route_service_store_edges", direct_call_edges),
            ("declared_metadata_and_accepted_design", declared_metadata_and_accepted_decision)]
