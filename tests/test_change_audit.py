#!/usr/bin/env python3
"""Before/after change evidence, scope, bounded scanning and owned cleanup."""
import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import change_audit
import context

ROOT = Path(__file__).resolve().parents[1]


class ChangeAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.states = []
        self.addCleanup(self.cleanup_states)

    def cleanup_states(self):
        for path in self.states:
            if path.exists():
                # Test-owned remnants include deliberate malformed/replaced state.
                if path.is_file() or path.is_symlink():
                    path.unlink()
            try:
                path.parent.rmdir()
            except OSError:
                pass

    def write(self, name, text):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def start(self, **kwargs):
        result = change_audit.start_audit(self.project, pack=ROOT, **kwargs)
        self.states.append(Path(result["state"]))
        return result

    def finish(self, start, **kwargs):
        return change_audit.finish_audit(self.project, start["state"], pack=ROOT, **kwargs)

    def test_tracks_new_modified_deleted_and_preserves_existing_edits_baseline(self):
        self.write("already-edited.py", "user's uncommitted work\n")
        self.write("change.py", "before\n")
        self.write("delete.py", "remove\n")
        start = self.start()
        self.write("change.py", "after\n")
        self.write("new.py", "new\n")
        (self.project / "delete.py").unlink()
        result = self.finish(start, writable_paths=["change.py", "new.py", "delete.py"])
        self.assertEqual(result["changes"], {"added": ["new.py"], "deleted": ["delete.py"], "modified": ["change.py"]})
        self.assertEqual(result["scope_status"], "within_scope")
        self.assertTrue(result["complete"])
        self.assertFalse(result["preserved"])
        self.assertFalse(Path(start["state"]).parent.exists())

    def test_includes_ignored_untracked_helper_caches_and_checks_exact_scope(self):
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.write(".gitignore", ".agent-dispatcher/\nuntracked.txt\n")
        self.write("result.md", "before\n")
        start = self.start()
        self.write("result.md", "after\n")
        self.write(".agent-dispatcher/project-map.json", "{}\n")
        self.write(".agent-dispatcher/project-graph.json", "{}\n")
        self.write("untracked.txt", "new\n")
        result = self.finish(start, writable_paths=["result.md"])
        self.assertEqual(result["out_of_scope"], [".agent-dispatcher/project-graph.json", ".agent-dispatcher/project-map.json", "untracked.txt"])
        self.assertEqual(result["scope_status"], "out_of_scope")
        self.assertTrue(result["complete"])

    def test_private_no_content_state_and_no_project_writes(self):
        secret = "never persist this source text\n"
        self.write("data.txt", secret)
        before = sorted(p.relative_to(self.project).as_posix() for p in self.project.rglob("*"))
        start = self.start()
        path = Path(start["state"])
        self.assertFalse(path.is_relative_to(self.project))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertNotIn(secret.strip(), path.read_text())
        self.assertEqual(before, sorted(p.relative_to(self.project).as_posix() for p in self.project.rglob("*")))
        result = self.finish(start)
        self.assertTrue(result["preserved"])
        self.assertEqual(result["scope_status"], "not_provided")
        self.assertTrue(start["project_read_only"])
        self.assertFalse(start["read_only"])

    def test_subtree_allowlist_does_not_match_similarly_named_directory(self):
        start = self.start()
        self.write("src/a.py", "yes")
        self.write("src-other/a.py", "no")
        result = self.finish(start, writable_paths=["src/"])
        self.assertEqual(result["out_of_scope"], ["src-other/a.py"])

    def test_empty_allowlist_forbids_all_changes(self):
        start = self.start()
        self.write("new.py", "new")
        result = self.finish(start, writable_paths=[])
        self.assertEqual(result["out_of_scope"], ["new.py"])

    def test_context_human_output_exposes_state_for_finish_and_cleanup(self):
        self.write("example.py", "def example():\n    return True\n")
        completed = subprocess.run([sys.executable, "-B", str(ROOT / "context.py"),
                                    "--project", str(self.project), "--task", "Inspect example",
                                    "--audit", "--map-preview"], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        prefix = "Change audit state: "
        paths = [line[len(prefix):] for line in completed.stdout.splitlines() if line.startswith(prefix)]
        self.assertEqual(len(paths), 1)
        state = Path(paths[0])
        self.states.append(state)
        self.assertTrue(state.is_file())
        finished = change_audit.finish_audit(self.project, state, pack=ROOT)
        self.assertEqual(finished["cleanup"]["status"], "removed")

    def test_cli_preserves_authored_setup_cleanup_diagnostics(self):
        helper = change_audit._verification()
        message = "Temporary setup failed; cleanup refused; retained state: [owned temporary location]"
        error = helper.VerificationError(message)
        output = io.StringIO()
        with mock.patch.object(change_audit, "start_audit", side_effect=error), \
                mock.patch("sys.stderr", output):
            status = change_audit.main(["start", "--project", str(self.project), "--json"])
        self.assertNotEqual(status, 0)
        self.assertIn(message, output.getvalue())

    def test_excluded_paths_are_not_opened_and_block_blanket_preservation(self):
        hidden = self.write("private/secret.txt", "private")
        original = os.open
        calls = []
        def tracked(path, *args, **kwargs):
            calls.append(str(path))
            return original(path, *args, **kwargs)
        with mock.patch.object(change_audit.os, "open", side_effect=tracked):
            start = self.start(exclude_paths=["private/"])
            result = self.finish(start, writable_paths=[])
        self.assertNotIn(hidden.name, calls)
        self.assertNotIn("private", calls)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["preserved"])
        self.assertEqual(result["scope_status"], "incomplete")

    def test_symlink_outside_project_is_never_followed(self):
        external = self.root / "external.txt"
        external.write_text("outside")
        (self.project / "linked.txt").symlink_to(external)
        (self.project / "linked-dir").symlink_to(self.root, target_is_directory=True)
        start = self.start()
        external.write_text("outside changed")
        result = self.finish(start, writable_paths=[])
        self.assertFalse(result["complete"])
        self.assertIsNone(result["preserved"])
        self.assertEqual(result["coverage"]["before"]["omitted"]["symlink"], 2)
        self.assertEqual(result["changes"], {"added": [], "deleted": [], "modified": []})

    def test_size_file_and_time_limits_never_claim_preserved(self):
        self.write("large.txt", "x" * 200)
        cases = [{"MAX_FILE_BYTES": 10}, {"MAX_FILES": 0}, {"MAX_SCAN_BYTES": 10}, {"MAX_SCAN_SECONDS": -1}]
        for limits in cases:
            with self.subTest(limits=limits), mock.patch.multiple(change_audit, **limits):
                start = self.start()
                result = self.finish(start, writable_paths=[])
                self.assertFalse(result["complete"])
                self.assertIsNone(result["preserved"])
                self.assertEqual(result["scope_status"], "incomplete")

    def test_unreadable_after_does_not_claim_deleted(self):
        self.write("large.txt", "x" * 200)
        start = self.start()
        with mock.patch.object(change_audit, "MAX_FILE_BYTES", 10):
            result = self.finish(start)
        self.assertEqual(result["changes"]["deleted"], [])
        self.assertFalse(result["complete"])

    def test_permission_mode_change_is_reported(self):
        path = self.write("run.sh", "true\n")
        path.chmod(0o600)
        start = self.start()
        path.chmod(0o700)
        self.assertEqual(self.finish(start)["changes"]["modified"], ["run.sh"])

    def test_invalid_literal_paths_rejected_without_cleanup(self):
        start = self.start()
        for path in ("../outside", "/tmp", "src/*", "src//a", "src/./a", "src\\a", "a\nb"):
            with self.subTest(path=path), self.assertRaises(change_audit.AuditError):
                self.finish(start, writable_paths=[path])
        self.assertTrue(Path(start["state"]).exists())
        self.finish(start)

    def test_wrong_project_foreign_and_malformed_states_left_untouched(self):
        start = self.start()
        state = Path(start["state"])
        another = self.root / "another"
        another.mkdir()
        with self.assertRaises(change_audit.AuditError):
            change_audit.finish_audit(another, state, pack=ROOT)
        self.assertTrue(state.exists())
        original = state.read_text()
        for replacement in ("{}", "malformed", original.replace(change_audit.OWNER, "foreign-owner")):
            state.write_text(replacement)
            with self.assertRaises(change_audit.AuditError):
                self.finish(start)
            self.assertEqual(state.read_text(), replacement)
        state.write_text(original)
        self.finish(start)

    def test_cleanup_only_owned_file_and_original_empty_directory(self):
        start = self.start()
        state = Path(start["state"])
        extra = state.parent / "unrelated.txt"
        extra.write_text("keep")
        result = self.finish(start)
        self.assertTrue(state.exists())
        self.assertTrue(state.parent.exists())
        self.assertEqual(extra.read_text(), "keep")
        self.assertEqual(result["cleanup"]["status"], "refused")
        self.assertIn("cleanup refused", change_audit.render(result))
        self.assertIn("leftover_path", result["cleanup"])
        extra.unlink()
        self.finish(start)
        self.assertFalse(state.parent.exists())

    def test_explicit_cleanup_without_finishing(self):
        start = self.start()
        change_audit.cleanup_audit(self.project, start["state"], pack=ROOT)
        self.assertFalse(Path(start["state"]).parent.exists())

    def test_exclusive_create_collision_never_adopts_or_deletes_competing_state(self):
        helper = change_audit._verification()
        original = helper._temporary_directory
        paths = []
        def collide(project):
            directory, identity = original(project)
            state = directory / "audit.json"
            state.write_text("competing file; do not delete")
            paths.append(state)
            self.states.append(state)
            return directory, identity
        with mock.patch.object(helper, "_temporary_directory", side_effect=collide), \
                mock.patch.object(change_audit, "_verification", return_value=helper):
            with self.assertRaisesRegex(change_audit.AuditError, "Cleanup refused; retained state"):
                self.start()
        self.assertEqual(paths[0].read_text(), "competing file; do not delete")
        self.assertTrue(paths[0].parent.exists())

    def test_fsync_failure_does_not_delete_replacement_state(self):
        helper = change_audit._verification()
        original = helper._temporary_directory
        paths = []
        def capture(project):
            directory, identity = original(project)
            paths.append(directory / "audit.json")
            self.states.append(paths[-1])
            return directory, identity
        def replace_and_fail(fd):
            path = paths[0]
            path.unlink()
            path.write_text("replacement; retain")
            raise OSError("injected fsync failure")
        with mock.patch.object(helper, "_temporary_directory", side_effect=capture), \
                mock.patch.object(change_audit, "_verification", return_value=helper), \
                mock.patch.object(change_audit.os, "fsync", side_effect=replace_and_fail):
            with self.assertRaisesRegex(change_audit.AuditError, "Cleanup refused"):
                self.start()
        self.assertEqual(paths[0].read_text(), "replacement; retain")

    def test_fsync_failure_cleans_our_unchanged_complete_state(self):
        helper = change_audit._verification()
        original = helper._temporary_directory
        paths = []
        def capture(project):
            directory, identity = original(project)
            paths.append(directory / "audit.json")
            self.states.append(paths[-1])
            return directory, identity
        with mock.patch.object(helper, "_temporary_directory", side_effect=capture), \
                mock.patch.object(change_audit, "_verification", return_value=helper), \
                mock.patch.object(change_audit.os, "fsync", side_effect=OSError("injected failure")):
            with self.assertRaises(change_audit.AuditError):
                self.start()
        self.assertFalse(paths[0].parent.exists())

    def test_preserve_state_option_can_be_finished_later(self):
        start = self.start()
        result = self.finish(start, cleanup=False)
        self.assertTrue(Path(start["state"]).exists())
        self.assertFalse(result["cleanup"]["requested"])
        self.write("later.txt", "later")
        self.assertEqual(self.finish(start)["changes"]["added"], ["later.txt"])

    def test_cli_round_trip(self):
        command = [sys.executable, "-B", str(ROOT / "change_audit.py")]
        started = subprocess.run(command + ["start", "--project", str(self.project), "--pack", str(ROOT), "--json"],
                                 capture_output=True, text=True, check=True)
        start = json.loads(started.stdout)
        self.states.append(Path(start["state"]))
        self.write("report.md", "report")
        finished = subprocess.run(command + ["finish", "--project", str(self.project), "--pack", str(ROOT),
                                             "--state", start["state"], "--writable-path", "report.md", "--json"],
                                  capture_output=True, text=True, check=True)
        result = json.loads(finished.stdout)
        self.assertEqual(result["scope_status"], "within_scope")
        self.assertEqual(result["changes"]["added"], ["report.md"])
        self.assertFalse(Path(start["state"]).exists())

    def test_context_audit_baseline_includes_first_helper_writes(self):
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.write("core.py", "def value():\n    return 1\n")
        result = context.select_context(self.project, "Inspect value and dependencies", pack=ROOT,
                                        compact=True, packet_tokens=12000, map_maintain=True, audit=True)
        audit = result["change_audit"]
        self.states.append(Path(audit["state"]))
        final = self.finish(audit, writable_paths=[])
        self.assertEqual(final["changes"]["added"], [".agent-dispatcher/project-graph.json", ".agent-dispatcher/project-map.json"])
        self.assertFalse(result["read_only"])

    def test_context_audit_propagates_read_exclusions(self):
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.write("core.py", "def value():\n    return 1\n")
        self.write("private/secret.txt", "private source")
        result = context.select_context(self.project, "Inspect value", pack=ROOT, audit=True, exclude_paths=["private/"])
        audit = result["change_audit"]
        self.states.append(Path(audit["state"]))
        data = json.loads(Path(audit["state"]).read_text())
        self.assertEqual(data["exclude_paths"], ["private"])
        self.assertNotIn("private/secret.txt", data["before"]["files"])
        self.assertFalse(self.finish(audit)["complete"])

    def test_context_too_small_packet_cleans_new_audit_state(self):
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.write("core.py", "def value():\n    return 1\n")
        original = context._sibling
        states = []
        def sibling(name):
            functions = original(name)
            if name == "change_audit":
                real_start = functions["start_audit"]
                def capture(*args, **kwargs):
                    result = real_start(*args, **kwargs)
                    states.append(Path(result["state"]))
                    self.states.append(Path(result["state"]))
                    return result
                functions["start_audit"] = capture
            return functions
        with mock.patch.object(context, "_sibling", side_effect=sibling), self.assertRaises(context.ContextError):
            context.select_context(self.project, "Inspect value", role="reviewer", pack=ROOT,
                                   compact=True, packet_tokens=256, audit=True)
        self.assertEqual(len(states), 1)
        self.assertFalse(states[0].parent.exists())

    def test_cli_out_of_scope_and_incomplete_are_nonzero(self):
        start = self.start()
        self.write("new.py", "new")
        with mock.patch.object(change_audit.sys, "stdout", io.StringIO()) as output:
            code = change_audit.main(["finish", "--project", str(self.project), "--state", start["state"],
                                      "--writable-path", "allowed.py", "--pack", str(ROOT), "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["out_of_scope"], ["new.py"])
        (self.project / "link").symlink_to(self.root)
        start = self.start()
        with mock.patch.object(change_audit.sys, "stdout", io.StringIO()):
            self.assertEqual(change_audit.main(["finish", "--project", str(self.project), "--state", start["state"], "--pack", str(ROOT)]), 1)

    def test_start_output_failure_cleans_created_state(self):
        original = change_audit.start_audit
        states = []
        def capture(*args, **kwargs):
            result = original(*args, **kwargs)
            states.append(Path(result["state"]))
            self.states.append(Path(result["state"]))
            return result
        class BrokenOutput(io.StringIO):
            def write(self, value):
                raise BrokenPipeError()
        with mock.patch.object(change_audit, "start_audit", side_effect=capture), \
                mock.patch.object(change_audit.sys, "stdout", BrokenOutput()), \
                mock.patch.object(change_audit.sys, "stderr", io.StringIO()):
            self.assertEqual(change_audit.main(["start", "--project", str(self.project), "--pack", str(ROOT)]), 1)
        self.assertEqual(len(states), 1)
        self.assertFalse(states[0].parent.exists())


if __name__ == "__main__":
    unittest.main()
