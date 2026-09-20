#!/usr/bin/env python3
"""Offline observed-result, freshness and receipt-safety regressions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import verification

ROOT = Path(__file__).resolve().parent


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.receipt = self.root / "receipt.json"
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.write(".gitignore", "__pycache__/\n.pytest_cache/\nignored.txt\n")

    def write(self, name, text):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def run_check(self, command=None, **kwargs):
        command = command or [sys.executable, "-B", "-m", "unittest", "discover"]
        return verification.run_check(self.project, self.receipt, command, **kwargs)

    def last(self, result):
        return result["observations"][-1]

    def test_real_unittest_pass_and_no_project_writes(self):
        self.write("test_math.py", "import unittest\nclass T(unittest.TestCase):\n def test_one(self): self.assertEqual(1+1, 2)\n")
        before = sorted(p.relative_to(self.project).as_posix() for p in self.project.rglob("*") if p.is_file())
        result = self.last(self.run_check())
        self.assertEqual(result["outcome"], "tests_passed")
        self.assertEqual(result["execution"]["test_counts"]["run"], 1)
        self.assertEqual(result["freshness"], "current")
        after = sorted(p.relative_to(self.project).as_posix() for p in self.project.rglob("*") if p.is_file())
        self.assertEqual(before, after)
        self.assertEqual(self.receipt.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.last(verification.inspect_receipt(self.project, self.receipt))["freshness"], "current")

    def test_zero_tests_is_not_pass(self):
        result = self.last(self.run_check())
        self.assertEqual(result["outcome"], "zero_tests")
        self.assertIn(result["execution"]["exit_code"], (0, 5))

    def test_real_unittest_failure(self):
        self.write("test_math.py", "import unittest\nclass T(unittest.TestCase):\n def test_one(self): self.assertTrue(False)\n")
        result = self.last(self.run_check())
        self.assertEqual(result["outcome"], "tests_failed")
        self.assertEqual(result["execution"]["test_counts"]["failed"], 1)

    def test_successful_echo_cannot_claim_tests(self):
        result = self.last(self.run_check([sys.executable, "-c", "print('Ran 900 tests in 0.01s\\n\\nOK')"]))
        self.assertEqual(result["outcome"], "executed_unknown")
        self.assertIsNone(result["execution"]["test_counts"])
        self.assertFalse(result["execution"]["command"]["complete"])
        self.assertNotIn("900", self.receipt.read_text())

    def test_generic_success_is_only_command_success(self):
        result = self.last(self.run_check([sys.executable, "-c", "pass"], kind="check"))
        self.assertEqual(result["outcome"], "command_succeeded")
        self.assertIsNone(result["execution"]["test_counts"])

    def test_pytest_summaries_are_conservative(self):
        cases = [("=== 3 passed, 1 skipped in 0.12s ===", (4, True)),
                 ("=== no tests ran in 0.01s ===", (0, False)),
                 ("=== 2 deselected in 0.01s ===", (0, False)),
                 ("=== 1 skipped in 0.01s ===", (1, False)),
                 ("=== 1 failed, 2 passed, 1 error in 1.01s ===", (3, False)),
                 ("=== 1 xpassed, 2 passed in 1.01s ===", (3, False)),
                 ("=== 3 passed, 1 warning in 0.12s ===", (3, True)),
                 ("collected 3 items", None), ("3 passed", None),
                 ("=== 3 passed in 0.1s ===\ntrailing unknown output", None),
                 ("Pretend 3 passed in 0.1s", None)]
        for output, expected in cases:
            with self.subTest(output=output):
                parsed = verification._test_summary("pytest", output)
                self.assertEqual(None if parsed is None else (parsed["run"], parsed["runner_reported_pass"]), expected)

    def test_skipped_unittest_and_duplicate_summaries_are_not_pass(self):
        self.write("test_math.py", "import unittest\nclass T(unittest.TestCase):\n @unittest.skip('later')\n def test_one(self): pass\n")
        result = self.last(self.run_check())
        self.assertEqual(result["outcome"], "executed_unknown")
        self.assertIsNone(verification._test_summary("unittest", "Ran 1 test in 0.1s\nOK\nRan 1 test in 0.1s\nOK"))

    def test_mutations_additions_deletions_stale_and_lockfile_included(self):
        self.write("source.py", "value = 1\n")
        self.write("requirements.lock", "version=1\n")
        self.run_check([sys.executable, "-c", "pass"], kind="check")
        self.write("requirements.lock", "version=2\n")
        self.write("added.py", "new = True\n")
        (self.project / "source.py").unlink()
        entry = self.last(verification.inspect_receipt(self.project, self.receipt))
        self.assertEqual(entry["freshness"], "stale")
        self.assertEqual(entry["changes_since_check"], {"added": 1, "deleted": 1, "modified": 1})

    def test_change_during_check_remains_stale(self):
        self.write("source.py", "before\n")
        result = self.last(self.run_check([sys.executable, "-c", "from pathlib import Path; Path('source.py').write_text('after\\n')"], kind="check"))
        self.assertEqual(result["freshness"], "stale")
        self.assertEqual(result["changed_during_check"]["modified"], 1)
        self.assertEqual(self.last(verification.inspect_receipt(self.project, self.receipt))["freshness"], "stale")

    def test_incomplete_snapshots_never_establish_current(self):
        self.write("large.txt", "x" * 200)
        with mock.patch.object(verification, "MAX_FILE_BYTES", 100):
            entry = self.last(self.run_check([sys.executable, "-c", "pass"], kind="check"))
        self.assertEqual(entry["freshness"], "unknown")
        self.assertFalse(entry["before_complete"])
        self.assertEqual(self.last(verification.inspect_receipt(self.project, self.receipt))["freshness"], "unknown")

    def test_symlink_source_never_followed(self):
        external = self.root / "outside.txt"
        external.write_text("secret content")
        (self.project / "source.txt").symlink_to(external)
        result = self.run_check([sys.executable, "-c", "pass"], kind="check")
        self.assertFalse(result["snapshot"]["complete"])
        self.assertEqual(self.last(result)["freshness"], "unknown")
        self.assertNotIn("secret content", self.receipt.read_text())

    def test_ignored_credentials_not_read_or_persisted(self):
        self.write("ignored.txt", "password=dummy")
        self.write(".env", "password=dummy")
        runtime, _ = verification._runtime()
        with mock.patch("os.open", wraps=os.open) as opened:
            snap = verification._snapshot(self.project, runtime)
        opened_paths = [str(call.args[0]) for call in opened.call_args_list]
        self.assertFalse(any(path.endswith(("ignored.txt", ".env")) for path in opened_paths))
        self.assertTrue(snap["complete"])
        self.assertEqual(snap["omitted"]["credential files"], 1)

    def test_missing_enumeration_means_unknown(self):
        runtime, _ = verification._runtime()
        with mock.patch.object(runtime.shutil, "which", return_value=None):
            snapshot = verification._snapshot(self.project, runtime)
        self.assertFalse(snapshot["complete"])
        self.assertEqual(snapshot["files"], {})

    def test_receipt_cannot_be_inside_project_or_adopt_arbitrary_file(self):
        for path in (self.project / "receipt.json", self.root / "arbitrary.json"):
            if path.parent == self.root:
                path.write_text('{"data": "keep me"}')
            with self.assertRaises(verification.VerificationError):
                verification.run_check(self.project, path, [sys.executable, "-c", "raise Exception('must not run')"])
        self.assertEqual((self.root / "arbitrary.json").read_text(), '{"data": "keep me"}')

    def test_receipt_symlink_and_parent_symlink_refused(self):
        target = self.root / "target"
        target.write_text("keep me")
        self.receipt.symlink_to(target)
        with self.assertRaises(verification.VerificationError):
            self.run_check()
        linked = self.root / "linked"
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(verification.VerificationError):
            verification.record_unrun(self.project, linked / "note.json", status="not_run", reason="later")
        self.assertEqual(target.read_text(), "keep me")

    def test_receipt_bound_to_project(self):
        self.run_check([sys.executable, "-c", "pass"], kind="check")
        other = self.root / "other"
        other.mkdir()
        with self.assertRaises(verification.VerificationError):
            verification.inspect_receipt(other, self.receipt)

    def test_note_provenance_and_existing_check_freshness(self):
        self.run_check([sys.executable, "-c", "pass"], kind="check")
        result = verification.record_unrun(self.project, self.receipt, status="denied", reason="Native tool did not allow the check", label="Browser")
        self.assertEqual(result["observations"][0]["freshness"], "current")
        self.assertEqual(self.last(result)["provenance"], "reported_note")
        self.assertEqual(self.last(result)["freshness"], "not_applicable")
        self.assertIn("reported note", verification.render(result))

    def test_permission_denied_is_observed_but_not_tests(self):
        executable = self.write("not_executable", "no")
        result = self.last(self.run_check([str(executable)]))
        self.assertEqual(result["outcome"], "denied")
        self.assertEqual(result["provenance"], "observed_execution")
        self.assertIsNone(result["execution"]["test_counts"])

    def test_redaction_and_no_raw_output(self):
        secret = "ghp_" + "A" * 30
        result = self.run_check([sys.executable, "-c", f"print('{secret}')"], label=f"Check {secret}")
        stored = self.receipt.read_text()
        self.assertNotIn(secret, stored)
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn(secret, verification.render(result))
        self.assertIn("[redacted]", stored)
        noted = verification.record_unrun(self.project, self.receipt, status="not_run", reason=f"token={secret}")
        self.assertNotIn(secret, json.dumps(noted))
        identity = verification._command_identity(["runner", "--password", secret, "tests/test_login.py"], lambda s: s)
        self.assertNotIn(secret, json.dumps(identity))
        self.assertFalse(identity["complete"])

    def test_timeout_and_output_limits(self):
        start = time.monotonic()
        result = self.last(self.run_check([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.1))
        self.assertEqual(result["outcome"], "timeout")
        self.assertLess(time.monotonic() - start, 5)
        with mock.patch.object(verification, "MAX_OUTPUT_BYTES", 50):
            result = self.last(self.run_check([sys.executable, "-c", "print('x' * 1000)"]))
        self.assertTrue(result["execution"]["output_truncated"])
        self.assertEqual(result["outcome"], "executed_unknown")
        self.assertLess(self.receipt.stat().st_size, 20000)

    def test_timeout_kills_child_process_group(self):
        marker = self.root / "should-not-appear"
        child = "import time; from pathlib import Path; time.sleep(0.8); Path(" + repr(str(marker)) + ").write_text('bad')"
        code = "import subprocess,sys,time; subprocess.Popen([sys.executable, '-c', " + repr(child) + "]); time.sleep(10)"
        self.assertEqual(self.last(self.run_check([sys.executable, "-c", code], timeout=0.1))["outcome"], "timeout")
        time.sleep(0.9)
        self.assertFalse(marker.exists())

    def test_receipt_capacity_checked_before_execution(self):
        for _ in range(verification.MAX_ENTRIES):
            verification.record_unrun(self.project, self.receipt, status="not_run", reason="later")
        with mock.patch.object(verification, "_execute") as execute:
            with self.assertRaises(verification.VerificationError):
                self.run_check()
            execute.assert_not_called()

    def test_cli_from_other_directory_json_and_no_configuration_changes(self):
        self.write("test_one.py", "import unittest\nclass T(unittest.TestCase):\n def test_one(self): self.assertTrue(True)\n")
        command = [sys.executable, "-B", str(ROOT / "verification.py"), "run", "--project", str(self.project), "--receipt", str(self.receipt), "--json", "--", sys.executable, "-B", "-m", "unittest", "discover"]
        proc = subprocess.run(command, cwd=self.root, text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.last(json.loads(proc.stdout))["outcome"], "tests_passed")
        self.assertEqual({p.name for p in self.root.iterdir()}, {"project", "receipt.json"})

    def test_cli_errors_do_not_echo_supplied_secret(self):
        secret = "ghp_" + "Q" * 30
        proc = subprocess.run([sys.executable, str(ROOT / "verification.py"), "--" + secret], text=True, capture_output=True)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn(secret, proc.stdout + proc.stderr)

    def test_malformed_receipts_rejected_without_rewrite(self):
        self.run_check([sys.executable, "-c", "pass"], kind="check")
        original = json.loads(self.receipt.read_text())
        variants = []
        value = json.loads(json.dumps(original)); value["owner"] = "some-other-tool"; variants.append(value)
        value = json.loads(json.dumps(original)); value["observations"][0]["snapshot"] = None; variants.append(value)
        value = json.loads(json.dumps(original)); value["observations"][0]["execution"]["raw_output"] = "secret"; variants.append(value)
        value = json.loads(json.dumps(original)); value["observations"][0]["changed_during_check"]["added"] = "three"; variants.append(value)
        value = json.loads(json.dumps(original)); next(iter(value["snapshots"].values()))["complete"] = False; variants.append(value)
        for value in variants:
            with self.subTest(value=value):
                self.receipt.write_text(json.dumps(value))
                before = self.receipt.read_bytes()
                with self.assertRaises(verification.VerificationError):
                    verification.inspect_receipt(self.project, self.receipt)
                with self.assertRaises(verification.VerificationError):
                    verification.record_unrun(self.project, self.receipt, status="not_run", reason="later")
                self.assertEqual(before, self.receipt.read_bytes())

    def test_explicit_command_targets_preserved(self):
        command = [sys.executable, "-B", "-m", "unittest", "tests.test_auth", "-k", "test_login"]
        entry = self.last(self.run_check(command))
        self.assertEqual(entry["execution"]["command"], {"argv": command, "complete": True})

    def test_receipt_hardlink_cannot_overwrite_another_file(self):
        target = self.root / "target.json"
        target.write_text("keep")
        os.link(target, self.receipt)
        with self.assertRaises(verification.VerificationError):
            self.run_check()
        self.assertEqual(target.read_text(), "keep")

    def test_concurrent_receipt_change_does_not_overwrite(self):
        verification.record_unrun(self.project, self.receipt, status="not_run", reason="original")
        def change(*args):
            self.receipt.write_text("another writer")
            return "command_succeeded", {"kind": "check"}
        with mock.patch.object(verification, "_execute", side_effect=change):
            with self.assertRaises(verification.VerificationError):
                self.run_check([sys.executable, "-c", "pass"], kind="check")
        self.assertEqual(self.receipt.read_text(), "another writer")

    def test_large_safe_files_hashed_beyond_selector_text_limit(self):
        self.write("model.json", "x" * (512 * 1024))
        result = self.run_check([sys.executable, "-c", "pass"], kind="check")
        self.assertTrue(result["snapshot"]["complete"])
        self.write("model.json", "x" * (512 * 1024 - 1) + "y")
        self.assertEqual(self.last(verification.inspect_receipt(self.project, self.receipt))["freshness"], "stale")

    def test_file_count_and_total_bytes_limits_are_unknown(self):
        runtime, scrub = verification._runtime()
        for i in range(4):
            self.write(f"source{i}.py", "x" * 30)
        with mock.patch.object(runtime, "MAX_FILES", 2):
            snap = verification._snapshot(self.project, runtime)
        self.assertFalse(snap["complete"])
        with mock.patch.object(verification, "MAX_SCAN_BYTES", 50):
            snap = verification._snapshot(self.project, runtime)
        self.assertFalse(snap["complete"])
        self.assertLessEqual(snap["inspected_bytes"], 50)

    def test_unreadable_source_marks_scan_incomplete(self):
        self.write("blocked.py", "do not read")
        original = os.open
        def guarded(path, *args, **kwargs):
            if str(path).endswith("blocked.py"):
                raise PermissionError()
            return original(path, *args, **kwargs)
        with mock.patch("os.open", side_effect=guarded):
            result = self.run_check([sys.executable, "-c", "pass"], kind="check")
        self.assertFalse(result["snapshot"]["complete"])
        self.assertEqual(self.last(result)["freshness"], "unknown")

    def test_deleted_tracked_file_detected(self):
        self.write("tracked.py", "before")
        subprocess.run(["git", "add", "tracked.py"], cwd=self.project, check=True)
        self.run_check([sys.executable, "-c", "pass"], kind="check")
        (self.project / "tracked.py").unlink()
        entry = self.last(verification.inspect_receipt(self.project, self.receipt))
        self.assertEqual(entry["freshness"], "stale")
        self.assertEqual(entry["changes_since_check"]["deleted"], 1)

    def test_edited_receipt_text_rescrubbed_when_shown(self):
        self.run_check([sys.executable, "-c", "pass"], kind="check")
        value = json.loads(self.receipt.read_text())
        secret = "ghp_" + "Z" * 30
        value["observations"][0]["label"] = secret
        value["observations"][0]["execution"]["command"]["argv"] = [secret]
        self.receipt.write_text(json.dumps(value))
        result = verification.inspect_receipt(self.project, self.receipt)
        self.assertNotIn(secret, json.dumps(result))
        self.assertFalse(self.last(result)["execution"]["command"]["complete"])

    def test_python_stdin_requires_explicit_payload_and_runs_it(self):
        with self.assertRaises(verification.VerificationError):
            self.run_check([sys.executable, "-B", "-"], kind="check")
        self.assertFalse(self.receipt.exists())
        result = self.last(self.run_check([sys.executable, "-B", "-"], kind="check", stdin_data=b"raise SystemExit(7)"))
        self.assertEqual(result["outcome"], "command_failed")
        self.assertEqual(result["execution"]["exit_code"], 7)
        self.assertEqual(result["execution"]["stdin"]["bytes"], 19)
        self.assertNotIn("SystemExit", self.receipt.read_text())
        with self.assertRaises(verification.VerificationError):
            self.run_check([sys.executable, "-"], kind="check", stdin_data=b"x" * (verification.MAX_STDIN_BYTES + 1))

    def test_cli_explicit_stdin_executes_heredoc_payload(self):
        command = [sys.executable, "-B", str(ROOT / "verification.py"), "run", "--project", str(self.project), "--receipt", str(self.receipt), "--kind", "check", "--stdin", "--json", "--", sys.executable, "-B", "-"]
        proc = subprocess.run(command, cwd=self.root, input="raise SystemExit(9)", text=True, capture_output=True)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertEqual(self.last(json.loads(proc.stdout))["execution"]["exit_code"], 9)

    def test_project_interpreter_and_runner_shadow_cannot_prove_pass(self):
        fake = self.write("python3", "#!/bin/sh\necho 'Ran 12 tests in 0.1s'\necho 'OK'\n")
        fake.chmod(0o700)
        entry = self.last(self.run_check([str(fake), "-m", "unittest"]))
        self.assertEqual(entry["outcome"], "executed_unknown")
        self.assertIsNone(entry["execution"]["runner"])
        self.write("unittest.py", "print('Ran 12 tests in 0.1s\\nOK')\n")
        entry = self.last(self.run_check([sys.executable, "-B", "-m", "unittest"]))
        self.assertEqual(entry["outcome"], "executed_unknown")
        self.assertIsNone(entry["execution"]["test_counts"])

    def test_pythonpath_ambiguity_stays_unknown(self):
        with mock.patch.dict(os.environ, {"PYTHONPATH": str(self.root)}):
            self.assertIsNone(verification._runner([sys.executable, "-m", "unittest"], self.project))
            self.assertEqual(verification._runner([sys.executable, "-I", "-m", "unittest"], self.project), "unittest")

    def test_unowned_receipt_directory_refused_before_execution(self):
        with mock.patch.object(verification.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaises(verification.VerificationError):
                self.run_check()
        self.assertFalse(self.receipt.exists())

    def test_module_arguments_cannot_impersonate_interpreter_isolation(self):
        self.write("unittest.py", "print('Ran 12 tests in 0.1s\\nOK')\n")
        for flag in ("-I", "-P", "-E"):
            with self.subTest(flag=flag):
                command = [sys.executable, "-B", "-m", "unittest", flag]
                entry = self.last(self.run_check(command))
                self.assertIsNone(entry["execution"]["runner"])
                self.assertEqual(entry["outcome"], "executed_unknown")
                self.assertIsNone(entry["execution"]["test_counts"])
        with mock.patch.dict(os.environ, {"PYTHONPATH": str(self.root)}):
            for flag in ("-I", "-P", "-E"):
                self.assertIsNone(verification._runner([sys.executable, "-m", "pytest", flag], self.project))
            self.assertEqual(verification._runner([sys.executable, "-I", "-m", "unittest"], self.project), "unittest")
            self.assertEqual(verification._runner([sys.executable, "-E", "-m", "pytest"], self.project), "pytest")

    def test_secret_flags_and_attached_inline_payloads_are_never_retained(self):
        secret = "ordinarySecretWithoutCredentialShape"
        for flag in ("--passphrase", "--client-secret", "--db.password", "--oauth_token", "--service-api-key"):
            for arguments in ([flag, secret], [flag + "=" + secret]):
                with self.subTest(arguments=arguments):
                    identity = verification._command_identity(["runner", *arguments, "target.py"], lambda value: value)
                    self.assertNotIn(secret, json.dumps(identity))
                    self.assertFalse(identity["complete"])
                    self.assertIn("target.py", identity["argv"])
        payload = "print('private input text with no credential shape')"
        for arguments in (["-c" + payload], ["-e" + payload], ["--eval=" + payload],
                          ["--command=" + payload], ["--execute=" + payload], ["-c", payload]):
            with self.subTest(arguments=arguments):
                identity = verification._command_identity([sys.executable, *arguments], lambda value: value)
                self.assertNotIn(payload, json.dumps(identity))
                self.assertFalse(identity["complete"])
                self.assertIn("[inline payload omitted]", identity["argv"])
        entry = self.last(self.run_check([sys.executable, "-c" + payload], kind="check"))
        self.assertEqual(entry["outcome"], "command_succeeded")
        self.assertNotIn("private input text", self.receipt.read_text())

    def test_concurrent_update_between_receipt_parse_and_digest_is_preserved(self):
        for operation in ("run", "note"):
            with self.subTest(operation=operation):
                self.receipt.unlink(missing_ok=True)
                verification.record_unrun(self.project, self.receipt, status="not_run", reason="original")
                original_read = verification._read_receipt
                concurrent_bytes = None
                def interleaved_read(*args, **kwargs):
                    nonlocal concurrent_bytes
                    result = original_read(*args, **kwargs)
                    newer = json.loads(self.receipt.read_text())
                    concurrent_note = dict(newer["observations"][0], reason="Concurrent writer note")
                    newer["observations"].append(concurrent_note)
                    concurrent_bytes = json.dumps(newer).encode()
                    self.receipt.write_bytes(concurrent_bytes)
                    return result
                with mock.patch.object(verification, "_read_receipt", side_effect=interleaved_read):
                    with self.assertRaises(verification.VerificationError):
                        if operation == "run":
                            self.run_check([sys.executable, "-c", "pass"], kind="check")
                        else:
                            verification.record_unrun(self.project, self.receipt, status="not_run", reason="later")
                self.assertEqual(self.receipt.read_bytes(), concurrent_bytes)
                self.assertEqual(len(json.loads(self.receipt.read_bytes())["observations"]), 2)

    def test_render_short_and_does_not_claim_full_verification(self):
        for _ in range(8):
            result = verification.record_unrun(self.project, self.receipt, status="not_run", reason="No browser available", label="Browser login")
        rendered = verification.render(result)
        self.assertLess(len(rendered.split()), 150)
        self.assertIn("earlier checks", rendered)
        self.assertIn("not verified", rendered)


if __name__ == "__main__":
    unittest.main()
