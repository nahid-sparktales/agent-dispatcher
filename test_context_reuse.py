"""Offline delivery-ledger checks; retained conversation context is caller-owned."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import context_reuse as reuse
import context


class ContextReuseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.state = self.root / "delivered.json"

    def excerpt(self, content="def greet(): return 'hello'", path="src/greet.py", lines="1-1", source=None):
        item = {"path": path, "lines": lines, "content": content,
                "source_sha256": hashlib.sha256((source or content).encode()).hexdigest()}
        item["id"] = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
        return item

    def packet(self, *excerpts):
        return {"project": str(self.project), "exclusion_policy": {"exclude_paths": ["private"]},
                "excerpts": list(excerpts or [self.excerpt()]), "context": [], "read_only": True}

    def deliver(self, packet=None, scope="retained-turns-1"):
        prepared, pending = reuse.prepare_reuse(packet or self.packet(), self.state, scope)
        return reuse.commit_reuse(prepared, pending)

    def test_second_delivery_references_exact_unchanged_evidence(self):
        original = self.packet()
        first = self.deliver(original)
        self.assertEqual(first["excerpts"], original["excerpts"])
        second = self.deliver(original)
        self.assertEqual(second["excerpts"], [])
        self.assertEqual(second["reuse"]["reused_count"], 1)
        self.assertEqual(second["reuse"]["references"][0]["id"], original["excerpts"][0]["id"])
        self.assertNotIn("reuse", original)

    def test_changed_source_range_content_or_path_emits_full_evidence(self):
        self.deliver()
        cases = [self.excerpt(source="changed elsewhere in the file"), self.excerpt(lines="2-2"),
                 self.excerpt(content="def greet(): return 'goodbye'"), self.excerpt(path="src/other.py")]
        for item in cases:
            with self.subTest(item=item):
                result, _ = reuse.prepare_reuse(self.packet(item), self.state, "retained-turns-1")
                self.assertEqual(result["excerpts"], [item])
                self.assertEqual(result["reuse"]["reused_count"], 0)

    def test_changed_binding_cannot_reuse_a_stale_identifier(self):
        original = self.packet()
        self.deliver(original)
        changed = copy.deepcopy(original)
        changed["excerpts"][0]["content"] = "new content retaining the old id"
        result, _ = reuse.prepare_reuse(changed, self.state, "retained-turns-1")
        self.assertEqual(result["excerpts"], changed["excerpts"])

    def test_new_scope_policy_project_or_deleted_ledger_emits_full_evidence(self):
        self.deliver()
        result, _ = reuse.prepare_reuse(self.packet(), self.state, "new-worker")
        self.assertEqual(len(result["excerpts"]), 1)
        changed = self.packet()
        changed["exclusion_policy"]["exclude_paths"] = ["other"]
        result, _ = reuse.prepare_reuse(changed, self.state, "retained-turns-1")
        self.assertEqual(len(result["excerpts"]), 1)
        other = self.root / "other-project"
        other.mkdir()
        changed = self.packet()
        changed["project"] = str(other)
        result, _ = reuse.prepare_reuse(changed, self.state, "retained-turns-1")
        self.assertEqual(len(result["excerpts"]), 1)
        self.state.unlink()
        self.assertEqual(len(self.deliver()["excerpts"]), 1)

    def test_only_full_excerpts_actually_delivered_are_recorded(self):
        first, second = self.excerpt(), self.excerpt(path="src/second.py")
        prepared, pending = reuse.prepare_reuse(self.packet(first, second), self.state, "scope")
        prepared["excerpts"] = [first]
        reuse.commit_reuse(prepared, pending)
        after, _ = reuse.prepare_reuse(self.packet(first, second), self.state, "scope")
        self.assertEqual(after["excerpts"], [second])
        self.assertEqual(after["reuse"]["reused_count"], 1)

    def test_truncated_excerpt_is_not_marked_as_full_delivery(self):
        prepared, pending = reuse.prepare_reuse(self.packet(), self.state, "scope")
        prepared["excerpts"][0]["content"] = "def greet"
        reuse.commit_reuse(prepared, pending)
        after, _ = reuse.prepare_reuse(self.packet(), self.state, "scope")
        self.assertEqual(len(after["excerpts"]), 1)

    def test_bad_or_missing_excerpt_metadata_disables_reuse(self):
        self.deliver()
        for key, value in [("id", None), ("id", "z" * 64), ("source_sha256", "bad"),
                           ("lines", "unbounded"), ("path", "../escape"), ("content", None)]:
            packet = self.packet()
            packet["excerpts"][0][key] = value
            result, pending = reuse.prepare_reuse(packet, self.state, "retained-turns-1")
            self.assertEqual(result["excerpts"], packet["excerpts"])
            self.assertEqual(result["reuse"]["status"], "unavailable")
            self.assertIsNone(pending)

    def test_absent_scope_disables_reuse_without_creating_state(self):
        for scope in (None, "", " ", 42):
            result, pending = reuse.prepare_reuse(self.packet(), self.state, scope)
            self.assertEqual(len(result["excerpts"]), 1)
            self.assertEqual(result["reuse"]["status"], "unavailable")
            self.assertIsNone(pending)
        self.assertFalse(self.state.exists())

    def test_unselected_or_deleted_sources_are_not_reintroduced(self):
        self.deliver()
        packet = self.packet()
        packet["excerpts"] = []
        self.assertEqual(self.deliver(packet)["excerpts"], [])
        self.assertEqual(self.deliver(packet)["reuse"]["references"], [])

    def test_ledger_contains_no_source_task_scope_or_project_text(self):
        packet = self.packet(self.excerpt(content="sensitive source example"))
        packet["task"] = "private user request"
        self.deliver(packet, "sensitive retained scope")
        raw = self.state.read_text()
        for text in ("sensitive source example", "private user request", "sensitive retained scope",
                     str(self.project), "src/greet.py", "private"):
            self.assertNotIn(text, raw)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)

    def test_malformed_oversized_or_changed_ledger_is_not_trusted(self):
        self.deliver()
        valid = self.state.read_text()
        changed = json.loads(valid)
        changed["entries"] = {}
        for raw in ("not json", " " * (reuse.MAX_STATE_BYTES + 1), json.dumps(changed)):
            self.state.write_text(raw)
            result, pending = reuse.prepare_reuse(self.packet(), self.state, "retained-turns-1")
            self.assertEqual(len(result["excerpts"]), 1)
            self.assertEqual(result["reuse"]["status"], "unavailable")
            self.assertIsNone(pending)
            self.assertEqual(self.state.read_text(), raw)

    def test_unsafe_locations_do_not_write_or_withhold_evidence(self):
        inside = self.project / "state.json"
        target = self.root / "target.json"
        target.write_text("keep me")
        link = self.root / "link.json"
        link.symlink_to(target)
        linked_parent = self.root / "alias"
        linked_parent.symlink_to(self.root, target_is_directory=True)
        for state in (inside, link, linked_parent / "state.json", self.root / "missing" / "state.json"):
            result, pending = reuse.prepare_reuse(self.packet(), state, "scope")
            self.assertEqual(len(result["excerpts"]), 1)
            self.assertEqual(result["reuse"]["status"], "unavailable")
            self.assertIsNone(pending)
        self.assertFalse(inside.exists())
        self.assertEqual(target.read_text(), "keep me")

    def test_relative_state_path_is_rejected_without_writing(self):
        with mock.patch.object(reuse.os, "getcwd", return_value=str(self.root)):
            result, pending = reuse.prepare_reuse(self.packet(), "relative-state.json", "scope")
        self.assertEqual(result["excerpts"], self.packet()["excerpts"])
        self.assertEqual(result["reuse"]["status"], "unavailable")
        self.assertIsNone(pending)
        self.assertFalse((self.root / "relative-state.json").exists())

    def test_public_or_hardlinked_ledger_is_rejected(self):
        self.deliver()
        self.state.chmod(0o644)
        result, pending = reuse.prepare_reuse(self.packet(), self.state, "retained-turns-1")
        self.assertEqual(result["reuse"]["status"], "unavailable")
        self.assertIsNone(pending)
        self.state.chmod(0o600)
        os.link(self.state, self.root / "hardlink.json")
        result, pending = reuse.prepare_reuse(self.packet(), self.state, "retained-turns-1")
        self.assertEqual(result["reuse"]["status"], "unavailable")
        self.assertIsNone(pending)

    def test_fifo_ledger_is_rejected_before_reading(self):
        os.mkfifo(self.state, 0o600)
        result, pending = reuse.prepare_reuse(self.packet(), self.state, "scope")
        self.assertEqual(len(result["excerpts"]), 1)
        self.assertEqual(result["reuse"]["status"], "unavailable")
        self.assertIsNone(pending)

    def test_write_failure_restores_retained_references_as_full_evidence(self):
        self.deliver()
        before = self.state.read_bytes()
        prepared, pending = reuse.prepare_reuse(self.packet(), self.state, "retained-turns-1")
        self.assertEqual(prepared["excerpts"], [])
        with mock.patch.object(reuse.os, "replace", side_effect=OSError("sensitive failure detail")):
            result = reuse.commit_reuse(prepared, pending)
        self.assertEqual(result["excerpts"], self.packet()["excerpts"])
        self.assertEqual(result["reuse"]["status"], "commit_failed")
        self.assertEqual(result["reuse"]["reused_count"], 0)
        self.assertNotIn("sensitive failure detail", json.dumps(result))
        self.assertEqual(self.state.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["delivered.json", "project"])

    def test_write_failure_does_not_restore_references_trimmed_from_packet(self):
        self.deliver()
        prepared, pending = reuse.prepare_reuse(self.packet(), self.state, "retained-turns-1")
        prepared["reuse"]["references"] = []
        with mock.patch.object(reuse.os, "replace", side_effect=OSError()):
            result = reuse.commit_reuse(prepared, pending)
        self.assertEqual(result["excerpts"], [])
        self.assertEqual(result["reuse"]["status"], "commit_failed")

    def test_write_failure_restores_original_retrieval_priority(self):
        important = self.excerpt(path="important.py")
        secondary = self.excerpt(path="secondary.py")
        self.deliver(self.packet(important))
        prepared, pending = reuse.prepare_reuse(self.packet(important, secondary), self.state, "retained-turns-1")
        self.assertEqual(prepared["excerpts"], [secondary])
        with mock.patch.object(reuse.os, "replace", side_effect=OSError()):
            result = reuse.commit_reuse(prepared, pending)
        self.assertEqual(result["excerpts"], [important, secondary])

    def test_state_change_between_prepare_and_commit_restores_full_evidence(self):
        self.deliver()
        prepared, pending = reuse.prepare_reuse(self.packet(), self.state, "retained-turns-1")
        self.state.unlink()
        result = reuse.commit_reuse(prepared, pending)
        self.assertEqual(result["excerpts"], self.packet()["excerpts"])
        self.assertEqual(result["reuse"]["status"], "commit_failed")

    def test_fresh_write_failure_leaves_no_delivery_claim_for_next_call(self):
        prepared, pending = reuse.prepare_reuse(self.packet(), self.state, "scope")
        with mock.patch.object(reuse.os, "replace", side_effect=OSError()):
            result = reuse.commit_reuse(prepared, pending)
        self.assertEqual(result["excerpts"], self.packet()["excerpts"])
        self.assertEqual(result["reuse"]["status"], "commit_failed")
        self.assertFalse(self.state.exists())
        self.assertEqual(len(self.deliver(scope="scope")["excerpts"]), 1)

    def test_entry_limit_evicts_old_entries_without_losing_evidence(self):
        with mock.patch.object(reuse, "MAX_ENTRIES", 2):
            for path in ("one.py", "two.py", "three.py"):
                self.deliver(self.packet(self.excerpt(path=path)))
            self.assertEqual(len(json.loads(self.state.read_text())["entries"]), 2)
            result, _ = reuse.prepare_reuse(self.packet(self.excerpt(path="one.py")), self.state,
                                           "retained-turns-1")
            self.assertEqual(len(result["excerpts"]), 1)

    def cli_args(self):
        # Git supplies ignore-aware enumeration even when ripgrep is unavailable.
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        (self.project / "main.py").write_text("def important_function():\n    return 42\n")
        return ["--project", str(self.project), "--task", "Inspect important_function", "--compact",
                "--pack", str(Path(__file__).resolve().parent),
                "--reuse-state", str(self.state), "--reuse-scope", "retained-cli-scope"]

    def test_cli_emits_source_when_ripgrep_is_unavailable(self):
        stdout = io.StringIO()
        args = self.cli_args()
        original_which = context.shutil.which

        def without_ripgrep(command, *args, **kwargs):
            return None if command == "rg" else original_which(command, *args, **kwargs)

        with mock.patch.object(context.shutil, "which", side_effect=without_ripgrep), \
                mock.patch("sys.stdout", stdout):
            self.assertEqual(context.main(args), 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual([item["path"] for item in result["excerpts"]], ["main.py"])
        self.assertTrue(self.state.exists())

    def test_cli_write_failure_does_not_record_undelivered_source(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr), \
                mock.patch.object(stdout, "write", side_effect=BrokenPipeError):
            code = context.main(self.cli_args())
        self.assertEqual(code, 1)
        self.assertFalse(self.state.exists())
        self.assertIn("reuse ledger was not updated", stderr.getvalue())

    def test_cli_flush_failure_does_not_record_undelivered_source(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr), \
                mock.patch.object(stdout, "flush", side_effect=BrokenPipeError):
            code = context.main(self.cli_args())
        self.assertEqual(code, 1)
        self.assertFalse(self.state.exists())
        self.assertEqual(json.loads(stdout.getvalue())["reuse"]["status"], "delivery_pending")

    def test_cli_success_flushes_source_then_records_delivery_once(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        state_existed_at_flush = []
        original_flush = stdout.flush

        def flush():
            state_existed_at_flush.append(self.state.exists())
            original_flush()

        args = self.cli_args()
        with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr), \
                mock.patch.object(stdout, "flush", side_effect=flush):
            code = context.main(args)
        self.assertEqual(code, 0)
        self.assertEqual(state_existed_at_flush, [False])
        first = json.loads(stdout.getvalue())
        self.assertEqual(first["reuse"]["status"], "delivery_pending")
        self.assertEqual(first["reuse"]["commit_policy"], "after_stdout_flush")
        self.assertTrue(first["excerpts"])
        self.assertTrue(self.state.exists())
        self.assertEqual(stderr.getvalue(), "")
        second_stdout = io.StringIO()
        with mock.patch("sys.stdout", second_stdout):
            self.assertEqual(context.main(args), 0)
        second = json.loads(second_stdout.getvalue())
        self.assertEqual(second["excerpts"], [])
        self.assertEqual(second["reuse"]["reused_count"], 1)

    def test_cli_ledger_failure_warns_without_reprinting_source(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr), \
                mock.patch.object(reuse.os, "replace", side_effect=OSError("private failure detail")):
            code = context.main(self.cli_args())
        self.assertEqual(code, 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["reuse"]["status"], "delivery_pending")
        self.assertTrue(result["excerpts"])
        self.assertFalse(self.state.exists())
        self.assertIn("later preparation may resend full evidence", stderr.getvalue())
        self.assertNotIn("private failure detail", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
