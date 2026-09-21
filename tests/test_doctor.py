#!/usr/bin/env python3
"""Offline behavioural checks for the read-only doctor runtime."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import doctor

ROOT = Path(__file__).resolve().parents[1]


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) if isinstance(data, (dict, list)) else data, encoding="utf-8")


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.pack = self.root / "pack"
        self.project = self.root / "project"
        self.config = self.root / "host"
        for path in (self.pack, self.project, self.config):
            path.mkdir()
        self.inventory = {
            "local_skills": [{"id": "review-guide", "purpose": "Review code", "paths": ["lib/review-guide/SKILL.md"]}],
            "external_skills": [
                {"id": "vendor-review", "name": "Review", "purpose": "Vendor review", "repository": "https://example.org/skills", "path": "skills/review/SKILL.md", "fallback": "review-guide"},
                {"id": "community-old", "activation": "Not recommended — official alternative available."}],
            "tools_and_mcps": [
                {"id": "workspace", "transport": "native", "purpose": "Read files"},
                {"id": "github", "source": "https://github.com/github/github-mcp-server", "fallback": "local git"},
                {"id": "supabase", "source": "https://supabase.com/docs", "fallback": "migrations"},
                {"id": "context7", "source": "https://example.org/docs"},
                {"id": "postgres-reference", "activation": "never", "risk": "unmaintained", "fallback": "migrations"}]}
        self.roles = {"roles": [{"id": "reviewer", "slug": "review", "name": "Code Reviewer",
                                 "skills": {"core": ["review-guide"], "preferred": ["vendor-review"], "conditional": {}},
                                 "mcps": {"recommended": ["github", "workspace"], "conditional": ["supabase"]},
                                 "verification": []}]}
        write(self.pack / "INVENTORY.json", self.inventory)
        write(self.pack / "catalog/loadouts.json", self.roles)
        write(self.pack / "catalog/resource-paths.json", {"schema_version": 1})
        write(self.pack / "decision/redact.py", "# fixture")
        write(self.pack / "lib/review-guide/SKILL.md", "# Review")
        write(self.pack / "SKILL.md", "# Dispatcher")
        write(self.pack / "roles/reviewer.md", "# Reviewer")
        for file in ("INDEX.md", "CONTEXT.md", "CONTEXT-REFERENCE.md", "ROLES.md", "CONTROLS.md",
                     "DELEGATION.md", "PROJECT-MAP.md", "VERIFICATION.md", "jev.md", "DOCTOR.md", "doctor.py", "context.py", "project_map.py", "resources.py", "verification.py", "preferences.py",
                     "context_packet.py", "context_reuse.py", "parser_cache.py", "project_graph.py", "change_audit.py"):
            write(self.pack / file, "fixture")

    def inspect(self, **kwargs):
        return doctor.inspect(pack=self.pack, project=self.project, host="codex", config_dir=self.config, **kwargs)

    def evidence(self, **kwargs):
        file = self.root / "evidence.json"
        write(file, {"schema_version": 1, **kwargs})
        return doctor.read_evidence(str(file))

    def row(self, report, name, category=None):
        matches = [r for r in report["entries"] if r["id"] == name and (category is None or r["category"] == category)]
        self.assertEqual(len(matches), 1, matches)
        return matches[0]

    def snapshot(self):
        return {str(p.relative_to(self.root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()}

    def test_without_session_evidence_connections_are_unknown_and_default_activation_is_healthy(self):
        report = self.inspect()
        self.assertEqual(self.row(report, "github")["status"], "unknown")
        self.assertEqual(self.row(report, "activation")["status"], "usable")
        self.assertIn("explicit", self.row(report, "activation")["detail"].lower())
        self.assertEqual(self.row(report, "hook")["status"], "usable")
        self.assertEqual(self.row(report, "review-guide")["status"], "usable")
        self.assertTrue(report["read_only"])
        self.assertTrue(any("No current-session" in v for v in report["limits"]))

    def test_configured_server_is_not_connected_and_configuration_secrets_never_escape(self):
        secret = "sk-" + "privatevalue" * 5
        write(self.config / "config.toml", '[mcp_servers.github]\nurl = "https://example.org"\nenv = { API_KEY = "' + secret + '" }\n')
        report = self.inspect(role="review")
        row = self.row(report, "configured:github")
        self.assertEqual(row["status"], "unknown")
        self.assertEqual(row["source"], "")
        self.assertTrue(row["configured"])
        self.assertIn("configured", row["detail"])
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn("API_KEY", json.dumps(report))

    def test_verified_server_and_exposed_individual_tool_keep_distinct_evidence(self):
        evidence = self.evidence(mcps=[{"id": "github-host", "catalog_id": "github", "status": "verified"}], tools=[{"id": "mcp__github__list_issues", "server": "github-host", "status": "exposed"}])
        report = self.inspect(role="reviewer", evidence=evidence)
        self.assertEqual(self.row(report, "github")["evidence"], "verified")
        self.assertEqual(self.row(report, "github")["tools"], ["mcp__github__list_issues"])
        self.assertIn("not tested", self.row(report, "mcp__github__list_issues")["detail"])
        self.assertNotIn("github", [r["id"] for r in report["recommendations"]])

    def test_extra_skills_native_tools_and_partial_mcp_servers_are_all_reported(self):
        evidence = self.evidence(skills=[{"id": "personal-writing", "status": "exposed"}], tools=[
            {"id": "exec_command", "status": "exposed"}, {"id": "mcp__extra__read", "server": "extra-service", "status": "exposed"}])
        report = self.inspect(evidence=evidence)
        self.assertEqual(self.row(report, "personal-writing")["category"], "host_skill")
        self.assertEqual(self.row(report, "exec_command")["category"], "native_tool")
        self.assertEqual(self.row(report, "mcp__extra__read")["category"], "mcp_tool")
        extra = self.row(report, "extra-service")
        self.assertEqual(extra["status"], "usable")
        self.assertIn("only listed", extra["detail"])
        self.assertEqual(self.row(report, "workspace")["category"], "native_tool")

    def test_same_name_external_skill_requires_explicit_provenance_mapping(self):
        write(self.config / "skills/vendor-review/SKILL.md", "# local fallback using same name")
        report = self.inspect(evidence=self.evidence(skills=[{"id": "Review", "status": "exposed"}]))
        self.assertEqual(self.row(report, "vendor-review", "external_skill")["status"], "unknown")
        self.assertEqual(self.row(report, "Review", "host_skill")["status"], "usable")
        mapped = self.inspect(evidence=self.evidence(skills=[{"id": "real-vendor-review", "catalog_id": "vendor-review", "status": "exposed"}]))
        self.assertEqual(self.row(mapped, "vendor-review", "external_skill")["status"], "usable")

    def test_explicit_disabled_preferences_override_even_verified_evidence(self):
        evidence = self.evidence(disabled=["github", "task-observer"], skills=[{"id": "task-observer", "status": "exposed"}],
                                 mcps=[{"id": "github-host", "catalog_id": "github", "status": "verified"}])
        report = self.inspect(role="reviewer", evidence=evidence)
        self.assertEqual(self.row(report, "github")["status"], "blocked")
        self.assertEqual(self.row(report, "task-observer")["status"], "blocked")
        self.assertFalse({"github", "task-observer"} & {r["id"] for r in report["recommendations"]})

    def test_disabled_config_server_cannot_be_unblocked_by_session_exposure(self):
        write(self.config / "config.toml", "[mcp_servers.github]\nenabled = false\n")
        report = self.inspect(evidence=self.evidence(mcps=[{"id": "github", "catalog_id": "github", "status": "verified"}]))
        self.assertEqual(self.row(report, "github")["status"], "blocked")

    def test_blocked_catalog_server_blocks_tools_under_host_alias(self):
        evidence = self.evidence(disabled=["github"], mcps=[{"id": "host-github", "catalog_id": "github", "status": "exposed"}],
                                 tools=[{"id": "list_issues", "server": "host-github", "status": "exposed"}])
        report = self.inspect(evidence=evidence)
        self.assertEqual(self.row(report, "github")["status"], "blocked")
        self.assertEqual(self.row(report, "list_issues")["status"], "blocked")

    def test_disabled_config_alias_blocks_explicitly_mapped_catalog_and_tools(self):
        write(self.config / "config.toml", "[mcp_servers.host-github]\nenabled = false\n")
        evidence = self.evidence(mcps=[{"id": "host-github", "catalog_id": "github", "status": "verified"}],
                                 tools=[{"id": "list_issues", "server": "host-github", "status": "verified"}])
        report = self.inspect(evidence=evidence)
        self.assertEqual(self.row(report, "github")["status"], "blocked")
        self.assertEqual(self.row(report, "list_issues")["status"], "blocked")

    def test_native_aggregate_keeps_every_individual_tool(self):
        evidence = self.evidence(tools=[{"id": "exec_command", "catalog_id": "workspace", "status": "exposed"},
                                 {"id": "apply_patch", "catalog_id": "workspace", "status": "exposed"}])
        report = self.inspect(evidence=evidence, scope="tools")
        self.assertEqual(self.row(report, "workspace")["status"], "usable")
        self.assertEqual(self.row(report, "workspace")["tools"], ["exec_command", "apply_patch"])
        self.assertEqual(self.row(report, "exec_command")["status"], "usable")
        self.assertEqual(self.row(report, "apply_patch")["status"], "usable")
        with self.assertRaises(doctor.DoctorError):
            self.inspect(evidence=self.evidence(tools=[{"id": "list_issues", "catalog_id": "github", "status": "exposed"}]))

    def test_native_partial_permissions_preserve_read_tools_and_explicit_aggregate_block(self):
        tools = [{"id": "read_file", "catalog_id": "workspace", "status": "exposed"},
                 {"id": "write_file", "catalog_id": "workspace", "status": "blocked"}]
        report = self.inspect(evidence=self.evidence(tools=tools))
        self.assertEqual(self.row(report, "workspace")["status"], "usable")
        self.assertEqual(self.row(report, "read_file")["status"], "usable")
        self.assertEqual(self.row(report, "write_file")["status"], "blocked")
        report = self.inspect(evidence=self.evidence(tools=tools, disabled=["workspace"]))
        self.assertEqual(self.row(report, "workspace")["status"], "blocked")
        self.assertEqual(self.row(report, "read_file")["status"], "blocked")

    def test_config_names_do_not_assert_catalog_provenance(self):
        write(self.config / "config.toml", "[mcp_servers.github]\ncommand = 'unrelated-service'\nenabled = false\n")
        report = self.inspect()
        self.assertEqual(self.row(report, "configured:github")["status"], "blocked")
        self.assertEqual(self.row(report, "configured:github")["source"], "")
        self.assertEqual(self.row(report, "github")["status"], "unknown")

    def test_package_health_reports_missing_entrypoint_role_and_required_reference(self):
        for file in ("SKILL.md", "roles/reviewer.md", "DOCTOR.md"):
            (self.pack / file).unlink()
        report = self.inspect()
        health = self.row(report, "package-files")
        self.assertEqual(health["status"], "needs_setup")
        self.assertEqual(set(health["missing_files"]), {"SKILL.md", "roles/reviewer.md", "DOCTOR.md"})
        self.assertEqual(report["recommendations"][0]["id"], "package-files")

    def test_bad_explicit_pack_does_not_fall_back_to_parent(self):
        missing = self.pack / "not-a-pack"
        missing.mkdir()
        with self.assertRaises(doctor.DoctorError):
            doctor.find_pack(missing)

    def test_context_helper_dependencies_are_required_for_package_health(self):
        self.assertEqual(self.row(self.inspect(), "package-files")["status"], "usable")
        (self.pack / "decision/redact.py").unlink()
        health = self.row(self.inspect(), "package-files")
        self.assertEqual(health["status"], "needs_setup")
        self.assertIn("decision/redact.py", health["missing_files"])

    def test_project_map_helper_is_required_for_package_health(self):
        (self.pack / "project_map.py").unlink()
        health = self.row(self.inspect(), "package-files")
        self.assertEqual(health["status"], "needs_setup")
        self.assertIn("project_map.py", health["missing_files"])

    def test_reporting_helpers_and_guide_are_required_for_package_health(self):
        missing = {"verification.py", "preferences.py", "change_audit.py", "VERIFICATION.md"}
        for name in missing:
            (self.pack / name).unlink()
        health = self.row(self.inspect(), "package-files")
        self.assertEqual(health["status"], "needs_setup")
        self.assertEqual(set(health["missing_files"]), missing)

    def test_plugin_runtime_dependencies_are_resolved_from_catalog(self):
        plugin = self.root / "plugin"
        plugin.mkdir()
        (plugin / "skills").mkdir()
        self.pack.rename(plugin / "skills/agent-dispatcher")
        self.pack = plugin / "skills/agent-dispatcher"
        for name in ("catalog", "decision"):
            (self.pack / name).rename(plugin / name)
        self.assertEqual(self.row(self.inspect(), "package-files")["status"], "usable")
        (plugin / "decision/redact.py").unlink()
        health = self.row(self.inspect(), "package-files")
        self.assertEqual(health["status"], "needs_setup")
        self.assertIn("../../decision/redact.py", health["missing_files"])

    def test_parent_connection_failure_blocks_exposed_tools_but_preserves_successful_operation_evidence(self):
        for parent in ("auth_required", "missing"):
            with self.subTest(parent=parent):
                evidence = self.evidence(mcps=[{"id": "host-github", "catalog_id": "github", "status": parent}],
                                         tools=[{"id": "list_issues", "server": "host-github", "status": "exposed"},
                                                {"id": "get_repo", "server": "host-github", "status": "verified"}])
                report = self.inspect(evidence=evidence)
                self.assertEqual(self.row(report, "list_issues")["status"], "needs_setup")
                self.assertEqual(self.row(report, "get_repo")["status"], "usable")
                self.assertIn("conflict", self.row(report, "get_repo")["detail"])
                self.assertEqual(self.row(report, "github")["status"], "needs_setup")

    def test_auth_failure_gets_setup_step_retired_capabilities_never_get_recommended(self):
        evidence = self.evidence(mcps=[{"id": "github", "catalog_id": "github", "status": "auth_required"}, {"id": "postgres-reference", "catalog_id": "postgres-reference", "status": "exposed"}])
        report = self.inspect(role="reviewer", evidence=evidence)
        self.assertEqual(self.row(report, "github")["status"], "needs_setup")
        self.assertEqual(self.row(report, "postgres-reference")["status"], "not_recommended")
        self.assertEqual(self.row(report, "community-old")["status"], "not_recommended")
        self.assertIn("Reconnect", next(r for r in report["recommendations"] if r["id"] == "github")["action"])

    def test_all_role_aliases_keep_full_inventory_and_only_focus_recommendations(self):
        for role in ("reviewer", "review", "Code Reviewer", "code reviewer"):
            report = self.inspect(role=role)
            self.assertEqual(report["role"], "reviewer")
            self.assertEqual(len(report["entries"]), len(self.inspect()["entries"]))
            self.assertNotIn("supabase", [r["id"] for r in report["recommendations"]])
            github = next(r for r in report["recommendations"] if r["id"] == "github")
            self.assertIn("Check current-session", github["action"])
        with self.assertRaises(doctor.DoctorError):
            self.inspect(role="not-a-role")

    def test_project_signals_make_recommendations_specific(self):
        write(self.project / "supabase/config.toml", "")
        report = self.inspect()
        self.assertEqual(report["project_signals"], ["supabase"])
        self.assertEqual([r["id"] for r in report["recommendations"]], ["supabase"])
        self.assertEqual(report["recommendations"][0]["fallback"], "migrations")

    def test_filters_and_totals_cover_all_requested_entries(self):
        evidence = self.evidence(tools=[{"id": "mcp__extra__read", "server": "extra-service", "status": "exposed"}])
        for scope, allowed in (("skills", {"bundled_skill", "external_skill", "host_skill"}), ("mcps", {"mcp_server"}), ("tools", {"mcp_tool", "native_tool"})):
            report = self.inspect(scope=scope, evidence=evidence)
            self.assertTrue(all(r["category"] in allowed for r in report["entries"]))
            self.assertEqual(sum(report["counts"].values()), len(report["entries"]))
        report = self.inspect(scope="setup")
        self.assertTrue(all(r["status"] != "usable" for r in report["entries"]))
        self.assertTrue(any("displayed subset" in v for v in report["limits"]))

    def test_missing_local_file_is_repairable_and_broken_catalog_reference_is_reported(self):
        (self.pack / "lib/review-guide/SKILL.md").unlink()
        self.roles["roles"][0]["skills"]["core"].append("missing-reference")
        write(self.pack / "catalog/loadouts.json", self.roles)
        write(self.pack / "catalog/resource-paths.json", {"schema_version": 1})
        report = self.inspect(role="reviewer")
        self.assertEqual(self.row(report, "review-guide")["status"], "needs_setup")
        self.assertIn("review-guide", [r["id"] for r in report["recommendations"]])
        self.assertEqual(self.row(report, "catalog-references")["status"], "needs_setup")

    def test_codex_reference_layout_and_default_helper_path_work_from_external_directory(self):
        installed = self.root / "codex-pack"
        installed.mkdir()
        write(installed / "references/INVENTORY.json", {**self.inventory, "local_skills": [{"id": "review-guide", "paths": ["references/skills/review-guide/GUIDE.md"]}]})
        write(installed / "references/skills/review-guide/GUIDE.md", "guide")
        write(installed / "references/roles/reviewer.md", "role")
        write(installed / "SKILL.md", "entrypoint")
        for file in ("INDEX.md", "CONTEXT.md", "DOCTOR.md"):
            write(installed / "references" / file, "fixture")
        write(installed / "scripts/runtime/catalog/loadouts.json", self.roles)
        shutil.copyfile(ROOT / "doctor.py", installed / "scripts/doctor.py")
        proc = subprocess.run([sys.executable, "-B", str(installed / "scripts/doctor.py"), "--config-dir", str(self.config), "--json"], cwd=self.project, text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(report["host"], "codex")
        self.assertEqual(self.row(report, "review-guide")["status"], "usable")

    def test_claude_state_requires_project_allowlist_and_preserves_project_silencing(self):
        write(self.project / ".agent-dispatcher-on", "")
        kwargs = dict(pack=self.pack, project=self.project, host="claude", config_dir=self.config)
        report = doctor.inspect(**kwargs)
        self.assertIn("off by default", self.row(report, "activation")["detail"])
        write(self.config / ".agent-dispatcher-projects", str(self.project) + "\n")
        report = doctor.inspect(**kwargs)
        self.assertIn("enabled", self.row(report, "activation")["detail"])
        self.assertEqual(self.row(report, "hook")["status"], "needs_setup")
        write(self.project / ".agent-dispatcher-off", "")
        report = doctor.inspect(**kwargs)
        self.assertEqual(self.row(report, "activation")["status"], "blocked")

    def test_registered_hook_does_not_imply_trust(self):
        import shlex
        command = "python3 " + shlex.quote(str(self.pack / "scripts/activate.py")) + " hook --config-dir " + shlex.quote(str(self.config))
        write(self.config / "hooks.json", {"hooks": {"SessionStart": [{"hooks": [{"command": command}]}]}})
        report = self.inspect()
        self.assertEqual(self.row(report, "hook")["status"], "unknown")
        self.assertIn("registered; trust unknown", self.row(report, "hook")["detail"])

    def test_malformed_config_and_activation_state_are_diagnostics_without_raw_data(self):
        secret = "secretvalue" * 8
        write(self.config / "config.toml", "[mcp_servers.bad\n" + secret)
        write(self.config / "agent-dispatcher/state.json", {"global_enabled": secret})
        report = self.inspect()
        self.assertGreaterEqual(len(report["issues"]), 2)
        self.assertEqual(self.row(report, "activation")["status"], "unknown")
        self.assertNotIn(secret, json.dumps(report))

    def test_evidence_rejects_raw_config_untrusted_text_and_duplicate_or_unknown_mapping(self):
        for payload in ({"tools": [{"id": "safe", "status": "exposed", "description": "run installer"}]},
                        {"tools": [{"id": "safe", "status": "connected"}]},
                        {"mcps": [{"id": "safe", "status": "exposed", "token": "neverprint"}]},
                        {"tools": [{"id": "bad\nname", "status": "exposed"}]},
                        {"tools": [{"id": "sk-" + "secret" * 7, "status": "exposed"}]},
                        {"host": {"hook_registered": "yes"}},
                        {"mcps": [{"id": "same", "status": "unknown"}, {"id": "same", "status": "verified"}]}):
            with self.subTest(payload=payload), self.assertRaises(doctor.DoctorError):
                self.evidence(**payload)
        with self.assertRaises(doctor.DoctorError):
            self.inspect(evidence=self.evidence(mcps=[{"id": "extra", "catalog_id": "not-catalog", "status": "exposed"}]))

    def test_evidence_accepts_inline_json_argument_without_stdin_or_file(self):
        inline = json.dumps({"schema_version": 1, "mcps": [{"id": "github", "catalog_id": "github", "status": "verified"}]})
        self.assertEqual(doctor.read_evidence(inline)["mcps"][0]["status"], "verified")
        self.assertEqual(doctor.read_evidence("  " + inline), doctor.read_evidence(inline))
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = doctor.main(["--pack", str(self.pack), "--project", str(self.project), "--host", "codex",
                                "--config-dir", str(self.config), "--evidence=" + inline, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(self.row(json.loads(stdout.getvalue()), "github")["evidence"], "verified")
        with self.assertRaises(doctor.DoctorError):
            doctor.read_evidence('{"schema_version": 1, "mcps": [')

    def test_cli_error_redacts_malformed_json_even_when_it_contains_secret(self):
        secret = "sk-" + "neverprint" * 5
        file = self.root / "bad.json"
        write(file, '{"schema_version": "' + secret)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = doctor.main(["--pack", str(self.pack), "--evidence", str(file), "--json"])
        self.assertEqual(code, 2)
        self.assertNotIn(secret, stderr.getvalue())
        self.assertTrue(json.loads(stderr.getvalue())["read_only"])

    def test_inspection_never_mutates_files_or_runs_tools_or_network(self):
        write(self.config / "config.toml", "[mcp_servers.github]\ncommand = 'do-not-run'\n")
        evidence = self.evidence(tools=[{"id": "exec_command", "status": "verified"}])
        before = self.snapshot()
        with mock.patch("subprocess.run", side_effect=AssertionError("doctor must not run commands")), mock.patch("socket.socket", side_effect=AssertionError("doctor must not make network calls")):
            report = self.inspect(evidence=evidence)
            rendered = doctor.render(report)
        self.assertIn("No setup changes were made", rendered)
        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main(verbosity=2)
