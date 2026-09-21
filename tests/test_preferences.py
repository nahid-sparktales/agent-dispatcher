#!/usr/bin/env python3
"""Offline checks for dispatcher-only preference persistence."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import preferences


ROOT = Path(__file__).resolve().parents[1]


class PreferencesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.state = self.base / "dispatcher"
        self.project = self.base / "project"
        self.project.mkdir()
        self.other = self.base / "other-project"
        self.other.mkdir()

    def get(self, **kwargs):
        return preferences.get_preferences(state_dir=self.state, **kwargs)

    def save(self, **kwargs):
        return preferences.set_preferences(state_dir=self.state, **kwargs)

    def write(self, value):
        self.state.mkdir(exist_ok=True)
        path = self.state / preferences.FILENAME
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
        return path

    def cli(self, *args, cwd=None, env=None):
        return subprocess.run([sys.executable, "-B", str(ROOT / "preferences.py"), *args],
                              cwd=cwd or self.other, env=env, text=True, capture_output=True)

    def test_defaults_are_read_only_and_actual_effort_unknown(self):
        result = self.get(project=self.project)
        self.assertEqual((result["output"], result["effort"]), ("eli5-succinct", "host"))
        self.assertEqual(result["requested_effort"], "host")
        self.assertEqual(result["effective_effort"], "unknown")
        self.assertTrue(result["requires_host_confirmation"])
        self.assertFalse(result["saved"])
        self.assertFalse(self.state.exists())
        self.assertEqual(list(self.project.iterdir()), [])

    def test_global_updates_merge_and_keep_effort_distinct_from_host(self):
        self.save(effort="low")
        result = self.save(output="detailed")
        self.assertEqual((result["output"], result["effort"]), ("detailed", "low"))
        self.assertEqual(result["effective_effort"], "unknown")
        self.assertEqual(result["sources"], {"output": "global", "effort": "global"})
        self.assertEqual(self.get()["effort"], "low")

    def test_project_overrides_merge_and_stay_isolated(self):
        self.save(output="detailed", effort="low")
        self.save(project=self.project, effort="high")
        first = self.get(project=self.project)
        second = self.get(project=self.other)
        self.assertEqual((first["output"], first["effort"]), ("detailed", "high"))
        self.assertEqual(first["sources"], {"output": "global", "effort": "project"})
        self.assertEqual(second["effort"], "low")
        self.save(output="eli5-succinct")
        self.assertEqual(self.get(project=self.project)["effort"], "high")
        self.assertEqual(self.get(project=self.project)["output"], "eli5-succinct")
        content = (self.state / preferences.FILENAME).read_text()
        self.assertNotIn(str(self.project), content)
        self.assertEqual(list(self.project.iterdir()), [])
        self.assertEqual(list(self.other.iterdir()), [])

    def test_explicit_host_effort_overrides_saved_low(self):
        self.save(effort="low")
        self.save(project=self.project, effort="host")
        self.assertEqual(self.get(project=self.project)["requested_effort"], "host")
        self.assertEqual(self.get()["effort"], "low")

    def test_canonical_project_aliases_use_same_override(self):
        alias = self.base / "alias"
        alias.symlink_to(self.project, target_is_directory=True)
        saved = self.save(project=self.project, effort="medium")
        self.assertEqual(self.get(project=alias)["project_key"], saved["project_key"])
        self.assertEqual(self.get(project=alias)["effort"], "medium")

    def test_xdg_and_home_fallback(self):
        environment = {"XDG_CONFIG_HOME": str(self.base / "config"), "HOME": str(self.base / "home")}
        with mock.patch.dict(os.environ, environment):
            self.assertEqual(preferences.get_preferences()["storage_path"],
                             str(self.base / "config/agent-dispatcher/preferences.json"))
            preferences.set_preferences(effort="low")
            self.assertEqual(preferences.get_preferences()["effort"], "low")
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "relative-untrusted", "HOME": str(self.base / "home")}):
            self.assertEqual(preferences.get_preferences()["storage_path"],
                             str(self.base / "home/.config/agent-dispatcher/preferences.json"))
        self.assertFalse((self.base / "home").exists())

    def test_cli_persistence_from_another_working_directory(self):
        saved = self.cli("set", "--state-dir", str(self.state), "--effort", "low", "--json")
        self.assertEqual(saved.returncode, 0, saved.stderr)
        shown = self.cli("show", "--state-dir", str(self.state), "--json", cwd=self.project)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        result = json.loads(shown.stdout)
        self.assertEqual(result["requested_effort"], "low")
        self.assertEqual(result["effective_effort"], "unknown")
        self.assertEqual(list(self.project.iterdir()), [])

    def test_human_output_does_not_claim_host_changed(self):
        result = self.cli("set", "--state-dir", str(self.state), "--effort", "low")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Requested effort: low", result.stdout)
        self.assertIn("Actual host effort: unknown", result.stdout)
        self.assertIn("Host configuration was not changed", result.stdout)

    def test_owner_schema_and_file_mode(self):
        self.save(effort="low")
        path = self.state / preferences.FILENAME
        data = json.loads(path.read_text())
        self.assertEqual(data["owner"], "agent-dispatcher")
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(list(self.state.iterdir()), [path])

    def test_invalid_unknown_and_duplicate_state_is_preserved(self):
        base = preferences._empty()
        invalids = [b"not json", b"{}", b"[]", b'{"owner": 1, "owner": 2}',
                    dict(base, owner="other"), dict(base, schema_version=2),
                    dict(base, schema_version=True), dict(base, future=True),
                    dict(base, **{"global": {"output": "invalid"}}),
                    dict(base, **{"global": {"unexpected": "keep"}}),
                    dict(base, projects={"not-hashed": {"effort": "low"}})]
        for value in invalids:
            with self.subTest(value=value):
                path = self.write(value)
                before = path.read_bytes()
                with self.assertRaises(preferences.PreferencesError):
                    self.get()
                with self.assertRaises(preferences.PreferencesError):
                    self.save(effort="low")
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(list(self.state.iterdir()), [path])

    def test_oversized_state_is_bounded_and_preserved(self):
        path = self.write(b" " * (preferences.MAX_BYTES + 1))
        with self.assertRaisesRegex(preferences.PreferencesError, "size limit"):
            self.save(effort="low")
        self.assertEqual(path.stat().st_size, preferences.MAX_BYTES + 1)

    def test_symlink_file_refused_without_touching_target(self):
        external = self.base / "host-settings.json"
        external.write_text('{"keep": true}')
        self.state.mkdir()
        (self.state / preferences.FILENAME).symlink_to(external)
        for action in (self.get, lambda: self.save(effort="low")):
            with self.assertRaises(preferences.PreferencesError):
                action()
        self.assertEqual(external.read_text(), '{"keep": true}')
        self.assertTrue((self.state / preferences.FILENAME).is_symlink())

    def test_symlink_directory_refused(self):
        self.state.symlink_to(self.project, target_is_directory=True)
        for action in (self.get, lambda: self.save(effort="low")):
            with self.assertRaises(preferences.PreferencesError):
                action()
        self.assertEqual(list(self.project.iterdir()), [])

    def test_unowned_file_refused(self):
        self.save(effort="low")
        path = self.state / preferences.FILENAME
        original = path.read_bytes()
        with mock.patch.object(preferences, "_owned", side_effect=lambda info: stat.S_ISDIR(info.st_mode)):
            with self.assertRaises(preferences.PreferencesError):
                self.save(output="detailed")
        self.assertEqual(path.read_bytes(), original)

    def test_fifo_and_hardlinks_are_refused(self):
        self.state.mkdir()
        path = self.state / preferences.FILENAME
        os.mkfifo(path)
        with self.assertRaises(preferences.PreferencesError):
            self.get()
        path.unlink()
        external = self.base / "original"
        external.write_text(json.dumps(preferences._empty()))
        os.link(external, path)
        with self.assertRaises(preferences.PreferencesError):
            self.save(effort="low")

    def test_atomic_replacement_and_failed_write_preserve_old_bytes(self):
        self.save(effort="low")
        path = self.state / preferences.FILENAME
        before = path.read_bytes()
        real_replace = os.replace

        def checked_replace(source, target, **kwargs):
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(stat.S_IMODE(os.stat(source, dir_fd=kwargs["src_dir_fd"]).st_mode), 0o600)
            return real_replace(source, target, **kwargs)

        with mock.patch.object(preferences.os, "replace", side_effect=checked_replace):
            self.save(output="detailed")
        before = path.read_bytes()
        with mock.patch.object(preferences.os, "replace", side_effect=OSError("no write")):
            with self.assertRaises(preferences.PreferencesError):
                self.save(effort="high")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.state.iterdir()), [path])

    def test_host_configuration_is_not_modified(self):
        home = self.base / "home"
        for relative in (".codex/config.toml", ".claude/settings.json", ".claude.json"):
            path = home / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("unchanged host configuration")
        before = {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()}
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            self.save(project=self.project, output="detailed", effort="low")
        after = {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_invalid_arguments_do_not_create_state(self):
        for arguments in ({}, {"effort": "turbo"}, {"output": "verbose"},
                          {"effort": "low", "project": self.base / "missing"}):
            with self.assertRaises(preferences.PreferencesError):
                self.save(**arguments)
        self.assertFalse(self.state.exists())

    def test_state_inside_selected_project_refused(self):
        inside = self.project / ".settings"
        with self.assertRaises(preferences.PreferencesError):
            preferences.set_preferences(effort="low", project=self.project, state_dir=inside)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_cli_invalid_file_outputs_safe_diagnostic(self):
        secret = "not-a-preference:" + "private-content"
        self.write(secret.encode())
        result = self.cli("show", "--state-dir", str(self.state), "--json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("error", json.loads(result.stdout))
        self.assertNotIn(secret, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
