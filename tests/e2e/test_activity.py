"""Offline measurement and owned-directory boundary regressions."""
import json
import shlex
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evals.end_to_end import activity, runtime


def trace(*events):
    return "\n".join(json.dumps(event) for event in events)


def call(ident, name, inputs):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": ident, "name": name, "input": inputs}]}}


def result(ident, content, error=False):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": ident, "content": content, "is_error": error}]}}


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.skill = self.root / "private-profile/skills/agent-dispatcher"
        for relative in ("SKILL.md", "roles/explorer.md", "roles/implementer.md", "lib/guide/SKILL.md", "context.py", "project_map.py"):
            path = self.skill / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Instructions\n")
        self.binding = activity.bind(self.project, self.skill)

    def analyze(self, *events, **kwargs):
        return activity.analyze("claude", trace(*events, {"type": "result", "subtype": "success", "result": "done"}), self.binding, **kwargs)

    def context_events(self, ident="context", payload="{}"):
        return [call(ident, "Bash", {"command": f"python3 '{self.skill}/context.py' --json"}), result(ident, payload)]

    def test_preparation_first_vs_late_literal_shell_exploration(self):
        for command, operation in (("ls -la", "explore"), ("cat CONTRACT.md", "read"),
                                   ("find . -type f -name '*.py'", "search"),
                                   ("rg -n profile src", "search")):
            events = [call("inspect", "Bash", {"command": f"cd '{self.project}' && {command}"}), result("inspect", "data")]
            with self.subTest(command=command):
                late = self.analyze(*events, *self.context_events())["preparation"]
                self.assertEqual(late["status"], "after_investigation")
                self.assertEqual(late["preceding_project_events_by_operation"][operation], 1)
                first = self.analyze(*self.context_events(), *events)["preparation"]
                self.assertEqual(first["status"], "before_investigation")
                self.assertEqual(first["preceding_project_events"], 0)
                self.assertEqual(first["first_context_result_event_line"], 2)

    def test_preparation_exempts_only_instruction_and_package_discovery(self):
        commands = ["cat AGENTS.md CLAUDE.md", "find . -name AGENTS.md -o -name CLAUDE.md",
                    "rg --files -g AGENTS.md", f"ls '{self.skill}'", f"cat '{self.skill}/SKILL.md'"]
        events = []
        for index, command in enumerate(commands):
            events.extend([call(str(index), "Bash", {"command": command}), result(str(index), "instructions")])
        events.extend([call("glob", "Glob", {"pattern": "**/CLAUDE.md"}), result("glob", "CLAUDE.md")])
        measured = self.analyze(*events, *self.context_events())["preparation"]
        self.assertEqual(measured["status"], "before_investigation")
        self.assertEqual(measured["exempt_instruction_events"], 4)
        self.assertEqual(measured["exempt_package_events"], 2)
        for command in ("cat AGENTS.md CONTRACT.md", "cat MAP_CONTRACT.md", "ls", "find . -name AGENTS.md -o -type f",
                        "find . -print -name AGENTS.md", "find . -name AGENTS.md -o -print0 -name CLAUDE.md"):
            report = self.analyze(call("mixed", "Bash", {"command": command}), result("mixed", "data"), *self.context_events())
            self.assertEqual(report["preparation"]["status"], "after_investigation", command)

    def test_preparation_native_search_reads_and_result_overlap(self):
        for name, inputs in (("Read", {"file_path": str(self.project / "app.py")}),
                             ("Grep", {"pattern": "profile", "path": str(self.project)}),
                             ("Glob", {"pattern": "**/*.py"})):
            context_call, context_result = self.context_events()
            inspect_call = call("inspect", name, inputs)
            combined = {"type": "assistant", "message": {"content": context_call["message"]["content"] + inspect_call["message"]["content"]}}
            report = self.analyze(combined, context_result, result("inspect", "data"))
            self.assertEqual(report["preparation"]["status"], "after_investigation")
            self.assertEqual(report["preparation"]["preceding_project_events"], 0)
            self.assertEqual(report["preparation"]["project_events_before_context_result"], 1)

    def test_preparation_failed_context_retry_and_other_helpers(self):
        failed, _ = self.context_events("failed")
        events = [failed, result("failed", "denied", True),
                  call("read", "Read", {"file_path": str(self.project / "app.py")}), result("read", "data")]
        prep = self.analyze(*events, *self.context_events())["preparation"]
        self.assertEqual(prep["status"], "after_investigation")
        self.assertEqual(prep["attempt_timing"], "early")
        self.assertEqual(prep["first_context_attempt_outcome"], "failed")
        report = self.analyze(call("map", "Bash", {"command": f"python3 '{self.skill}/project_map.py' show --json"}), result("map", "{}"))
        self.assertEqual(report["preparation"]["status"], "not_observed")
        self.assertEqual(self.analyze(failed)["preparation"]["status"], "unknown")

    def test_preparation_reports_project_writes_and_detailed_guides_separately(self):
        for name in ("Write", "Edit"):
            prep = self.analyze(call("write", name, {"file_path": str(self.project / ".agent-dispatcher/task.txt")}),
                                result("write", "saved"), *self.context_events())["preparation"]
            self.assertEqual(prep["preceding_project_writes"], 1)
            self.assertEqual(prep["project_writes_before_first_attempt"], 1)
            self.assertEqual(prep["preceding_project_events"], 0)
            self.assertEqual(prep["status"], "after_investigation")
        events = []
        for index, relative in enumerate(("roles/implementer.md", "lib/guide/SKILL.md")):
            events.extend([call(str(index), "Read", {"file_path": str(self.skill / relative)}), result(str(index), "instructions")])
        prep = self.analyze(*events, *self.context_events())["preparation"]
        self.assertEqual(prep["preceding_role_guide_reads"], 2)
        self.assertEqual(prep["role_guide_reads_before_first_attempt"], 2)
        self.assertEqual(prep["status"], "after_investigation")
        self.assertEqual(prep["preceding_project_events"], 0)

    def test_preparation_unknown_prefix_not_unknown_suffix(self):
        for command in ("python3 -c 'print(open(\"app.py\").read())'", "cat app.py && echo done", "ls $PROJECT"):
            events = [call("unknown", "Bash", {"command": command}), result("unknown", "data")]
            self.assertEqual(self.analyze(*events, *self.context_events())["preparation"]["status"], "unknown")
            self.assertEqual(self.analyze(*self.context_events(), *events)["preparation"]["status"], "before_investigation")
        malformed = {"type": "assistant", "message": {"content": None}}
        self.assertEqual(self.analyze(malformed, *self.context_events())["preparation"]["status"], "unknown")
        self.assertEqual(self.analyze(*self.context_events(), malformed)["preparation"]["status"], "before_investigation")

    def test_preparation_codex_started_and_completed_order(self):
        def item(ident, kind, command):
            return {"type": kind, "item": {"id": ident, "type": "command_execution", "command": command,
                    "exit_code": 0 if kind == "item.completed" else None, "aggregated_output": "{}"}}
        command = f"python3 '{self.skill}/context.py' --json"
        events = [item("context", "item.started", command), item("read", "item.started", "cat app.py"),
                  item("context", "item.completed", command), item("read", "item.completed", "cat app.py"), {"type": "turn.completed"}]
        report = activity.analyze("codex", trace(*events), self.binding)
        self.assertEqual(report["preparation"]["status"], "after_investigation")
        self.assertEqual(report["preparation"]["first_context_result_event_line"], 3)

    def test_context_exclusion_metadata_is_measured_without_rule_contents(self):
        policy = {"automatic_enabled": True, "automatic": ["archive"], "manual": ["private"],
                  "applied": ["archive", "private"], "unresolved": [{"phrase": "secret wording", "reason": "ambiguous"}], "unresolved_total": 1}
        report = self.analyze(*self.context_events(payload=json.dumps({"exclusion_policy": policy})))
        counts = report["actions"][0]["context_exclusions"]
        self.assertEqual(counts, {"availability": "complete", "automatic_enabled": True,
                         "automatic_count": 1, "manual_count": 1, "applied_count": 2, "unresolved_count": 1, "unresolved_total": 1})
        self.assertNotIn("archive", json.dumps(report))
        self.assertNotIn("secret wording", json.dumps(report))
        for bad in ({"automatic_enabled": "yes"}, {**policy, "applied": [False]}, {**policy, "unresolved_total": True}):
            report = self.analyze(*self.context_events(payload=json.dumps({"exclusion_policy": bad})))
            self.assertEqual(report["actions"][0]["context_exclusions"]["availability"], "partial")
        self.assertEqual(self.analyze(*self.context_events())["actions"][0]["context_exclusions"], {"availability": "unavailable"})

    def test_literal_cleanup_matches_only_prior_owned_trial_writes(self):
        report = self.analyze(call("write", "Write", {"file_path": "../check.py", "content": "private"}), result("write", "written"),
                              call("clean", "Bash", {"command": f"cd '{self.project}' && rm -f ../check.py"}), result("clean", ""),
                              call("unmatched", "Bash", {"command": "unlink ../other.py"}), result("unmatched", ""))
        cleanups = [row for row in report["actions"] if row["kind"] == "cleanup_attempt"]
        self.assertEqual([row["matched_prior_write"] for row in cleanups], [True, False])
        self.assertTrue(all(row["remaining_state"] == "unknown" for row in cleanups))
        self.assertFalse((self.root / "check.py").exists())  # Trace parsing never executes writes or cleanup.
        unknown = self.analyze(call("clean", "Bash", {"command": "rm -rf ../check.py && echo removed"}), result("clean", "removed"))
        self.assertFalse(unknown["actions"])
        self.assertEqual(unknown["availability"], "partial")

    def test_cleanup_of_project_or_mixed_targets_cannot_establish_early_preparation(self):
        for command in ("rm -f app.py", "unlink app.py", "rm -f ../check.py app.py"):
            report = self.analyze(call("cleanup", "Bash", {"command": command}), result("cleanup", ""), *self.context_events())
            self.assertEqual(report["preparation"]["status"], "unknown", command)
            self.assertEqual(report["availability"], "partial")
            if "../check.py" in command:
                self.assertEqual(report["actions"][0]["kind"], "cleanup_attempt")

    def test_helpers_bind_to_staged_paths_and_observed_results(self):
        rows = [call("h1", "Bash", {"command": f"python3 -B '{self.skill}/context.py' --task-file - --json <<'END'\ntask\nEND"}),
                result("h1", json.dumps({"schema_version": 1, "project_map": {"status": "missing"}})),
                call("h2", "Bash", {"command": f"python3 '{self.skill}/project_map.py' show --json"}),
                result("h2", "failed", True),
                call("h3", "Bash", {"command": "python3 context.py --json"}), result("h3", "{}"),
                call("h4", "Bash", {"command": f"echo python3 {self.skill}/context.py"}), result("h4", "echo"),
                call("h5", "Bash", {"command": "python3 /other/agent-dispatcher/context.py"}), result("h5", "{}")]
        report = self.analyze(*rows)
        self.assertEqual(report["summary"]["helper_attempts"], 2)
        self.assertEqual(report["summary"]["helper_successes"], 1)
        self.assertEqual(report["actions"][0]["map_status"], "missing")
        self.assertNotIn(str(self.root), json.dumps(report))
        self.assertNotIn("private-profile", json.dumps(report))

    def test_quoted_heredoc_task_data_is_not_shell_syntax(self):
        command = f"python3 -B '{self.skill}/context.py' --task-file - --json <<'TASK'\nFix the user's \"missing quote and request.\nTASK"
        report = self.analyze(call("h", "Bash", {"command": command}), result("h", '{"project_map":{"status":"missing","evidence_origin":"preview","cache_status":"missing","entries":[{}]}}'))
        self.assertEqual(report["summary"]["helper_successes"], 1)
        self.assertEqual(report["actions"][0]["map_evidence_origin"], "preview")
        for unsafe in (command + "\necho done", command.rsplit("\n", 1)[0]):
            report = self.analyze(call("h", "Bash", {"command": unsafe}), result("h", "{}"))
            self.assertEqual(report["summary"]["helper_successes"], 0)
            self.assertEqual(report["availability"], "partial")

    def test_malformed_events_and_unknown_codex_exit_remain_unknown(self):
        for event in ({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": []}]}},
                      {"type": "assistant", "message": {"content": None}},
                      {"type": "result", "permission_denials": [None]}):
            report = self.analyze(event)
            self.assertEqual(report["availability"], "partial")
        report = activity.analyze("codex", trace({"type": "item.completed", "item": {"type": "command_execution", "command": f"python3 {self.skill}/context.py", "aggregated_output": "{}"}}, {"type": "turn.completed"}), self.binding)
        self.assertEqual(report["summary"]["helper_successes"], 0)
        self.assertEqual(report["availability"], "partial")

    def test_guidance_reads_repeats_characters_roles_and_failed_paths(self):
        path = str(self.skill / "roles/explorer.md")
        report = self.analyze(call("a", "Read", {"file_path": path}), result("a", "12345"),
                              call("b", "Read", {"file_path": path, "offset": 2}), result("b", "abcdef"),
                              call("c", "Read", {"file_path": str(self.skill / "missing/SKILL.md")}), result("c", "No such file", True),
                              {"type": "assistant", "message": {"content": [{"type": "text", "text": "→ explorer · Skills loaded: guide"}]}})
        summary = report["summary"]
        self.assertEqual((summary["guidance_reads"], summary["guidance_unique_paths"], summary["guidance_repeated_reads"], summary["guidance_returned_chars"]), (2, 1, 1, 11))
        self.assertEqual(summary["failed_paths"], 1)
        self.assertEqual(report["route"], {"role": "explorer", "basis": "declaration", "consistent": True, "availability": "complete"})
        report = self.analyze(call("a", "Read", {"file_path": path}), result("a", "role"),
                              {"type": "assistant", "message": {"content": [{"type": "text", "text": "Role: implementer"}]}})
        self.assertFalse(report["route"]["consistent"])

    def test_denied_missing_and_unknown_calls_are_not_success(self):
        report = self.analyze(call("a", "Read", {"file_path": str(self.skill / "SKILL.md")}),
                              result("a", "Permission to use Read denied", True),
                              call("b", "Bash", {"command": f"python3 {self.skill}/context.py"}))
        self.assertEqual(report["availability"], "partial")
        self.assertEqual(report["summary"]["permission_denials"], 1)
        self.assertEqual(report["summary"]["helper_successes"], 0)
        self.assertEqual(report["summary"]["guidance_reads"], 0)

    def test_codex_updates_deduplicated_and_read_output_attributed(self):
        command = f"/bin/zsh -lc \"cat '{self.skill}/roles/explorer.md'\""
        events = [{"type": kind, "item": {"id": "a", "type": "command_execution", "command": command,
                   "exit_code": 0 if kind == "item.completed" else None, "aggregated_output": "role text"}}
                  for kind in ("item.started", "item.updated", "item.completed")]
        report = activity.analyze("codex", trace(*events, {"type": "turn.completed"}), self.binding)
        self.assertEqual(report["summary"]["guidance_reads"], 1)
        self.assertEqual(report["summary"]["guidance_returned_chars"], 9)
        self.assertEqual(report["route"]["role"], "explorer")

    def test_literal_cd_printf_pipeline_matches_observed_native_context_call(self):
        # Shape and task from the saved auth_config_boundary treatment call.
        task = ("Unauthenticated /profile still succeeds when APP_ALLOW_GUEST=false. "
                "Fix the live behavior to meet CONTRACT.md, including its false/true aliases, "
                "missing default, and invalid-value behavior. Preserve router and identity behavior. "
                "The archive and generated snapshot are distractors, not runtime entrypoints.")
        command = (f'cd "{self.project}" && printf \'%s\' ' + shlex.quote(task)
                   + f' | python3 -B "{self.skill}/context.py" --project "{self.project}"'
                   + ' --task-file - --role implementer --map-preview --json')
        payload = {"schema_version": 1, "read_only": True, "project_map": {
            "status": "missing", "cache_status": "missing", "evidence_origin": "preview", "entries": [{}]}}
        report = self.analyze(call("a", "Bash", {"command": command}), result("a", json.dumps(payload)))
        self.assertEqual(report["summary"]["helper_successes"], 1)
        self.assertEqual(report["availability"], "complete")
        self.assertEqual(report["actions"][0]["map_evidence_origin"], "preview")
        self.assertEqual(report["actions"][0]["map_entries"], 1)
        plain = command.split(" && ", 1)[1]
        plain_result = self.analyze(call("a", "Bash", {"command": plain}), result("a", json.dumps(payload)))
        self.assertEqual(plain_result["summary"]["helper_successes"], 1)
        direct = (f'cd "{self.project}" && python3 -B "{self.skill}/context.py" --project "{self.project}" '
                  "--task-file '.agent-dispatcher/task.txt' --role documentation-writer --map-preview --json")
        direct_result = self.analyze(call("a", "Bash", {"command": direct}), result("a", json.dumps(payload)))
        self.assertEqual(direct_result["summary"]["helper_successes"], 1)
        failed = self.analyze(call("a", "Bash", {"command": command}), result("a", "failed", True))
        self.assertEqual(failed["summary"]["helper_successes"], 0)

    def test_literal_pipeline_preserves_quoted_data_and_uses_cd_directory(self):
        relative = str(self.skill.relative_to(self.root) / "context.py")
        task = "Fix the user's \"quote\"; literal $(echo data), pipes | and && stay task data."
        command = (f'cd "{self.root}" && printf \'%s\' ' + shlex.quote(task)
                   + ' | python3 -B ' + shlex.quote(relative) + ' --task-file - --json')
        report = self.analyze(call("a", "Bash", {"command": command}), result("a", "{}"))
        self.assertEqual(report["summary"]["helper_successes"], 1)
        wrong = command.replace(f'cd "{self.root}"', 'cd "/another/workspace"')
        report = self.analyze(call("a", "Bash", {"command": wrong}), result("a", "{}"))
        self.assertEqual(report["summary"]["helper_successes"], 0)
        direct = f'cd "{self.root}" && python3 -B ' + shlex.quote(relative) + ' --task query --json'
        report = self.analyze(call("a", "Bash", {"command": direct}), result("a", "{}"))
        self.assertEqual(report["summary"]["helper_successes"], 1)

    def test_helper_pipeline_rejects_spoofs_expansions_and_extra_commands(self):
        helper = f'python3 -B "{self.skill}/context.py" --task-file - --json'
        good = "printf '%s' 'literal task' | " + helper
        invalid = [good + '; echo success', good + ' && echo success', good + '\necho success',
                   good + ' | cat', good + ' > result.json',
                   "printf '%s' 'literal task' | cat | " + helper,
                   "echo " + shlex.quote(good), "printf '%s' " + shlex.quote(good),
                   "printf '%s' \"$TASK\" | " + helper,
                   "printf '%s' \"$(echo task)\" | " + helper,
                   "printf '%s' `echo task` | " + helper,
                   'cd "$DIR" && ' + good, "false && " + good,
                   "printf '%s' 'literal task' | echo " + shlex.quote(helper),
                   good.replace('--task-file -', '--task query'),
                   'bash -lc "printf \'%s\' \'$TASK\' | ' + helper.replace('"', '') + '"',
                   'bash -lc "printf \'%s\' \'$(echo task)\' | ' + helper.replace('"', '') + '"',
                   f'python3 "{self.skill}/context.py" --task "$TASK"']
        for command in invalid:
            with self.subTest(command=command):
                report = self.analyze(call("a", "Bash", {"command": command}), result("a", "{}"))
                self.assertEqual(report["summary"]["helper_successes"], 0)

    def test_recorded_binding_never_resolves_removed_workspace_or_live_profile(self):
        recorded_root = "/recorded/trial/project"
        recorded_pack = "/recorded/profile/skills/agent-dispatcher"
        binding = activity.Bindings(recorded_root, recorded_pack,
            {recorded_pack + "/context.py": "context.py"}, {}, {}, recorded=True)
        command = f'cd "{recorded_root}" && printf \'%s\' \'request\' | python3 -B "{recorded_pack}/context.py" --task-file - --json'
        events = trace(call("a", "Bash", {"command": command}), result("a", "{}"), {"type": "result", "subtype": "success", "result": "done"})
        with patch.object(activity.os.path, "realpath", side_effect=AssertionError("live path resolution")):
            report = activity.analyze("claude", events, binding)
        self.assertEqual(report["summary"]["helper_successes"], 1)

    def test_explicit_command_workdir_is_used_for_relative_helper_paths(self):
        relative = str(self.skill.relative_to(self.root) / "context.py")
        report = self.analyze(call("a", "exec_command", {"cmd": "python3 " + relative, "workdir": "/different/workspace"}), result("a", "{}"))
        self.assertEqual(report["summary"]["helper_successes"], 0)
        report = self.analyze(call("a", "exec_command", {"cmd": "python3 " + relative, "workdir": str(self.root)}), result("a", "{}"))
        self.assertEqual(report["summary"]["helper_successes"], 1)
        report = self.analyze(call("a", "Bash", {"command": f"python3 {self.skill}/context.py", "cwd": "/different/workspace"}), result("a", "{}"))
        self.assertEqual(report["summary"]["helper_successes"], 1)

    def test_codex_file_changes_observe_successful_writes_only(self):
        def changed(ident, status, kind="item.completed"):
            return {"type": kind, "item": {"id": ident, "type": "file_change", "status": status,
                    "changes": [{"path": str(self.project / "app.py"), "kind": "update"}]}}
        report = activity.analyze("codex", trace(changed("a", "in_progress", "item.started"),
                    changed("a", "completed"), changed("b", "failed"), changed("c", None),
                    {"type": "turn.completed"}), self.binding)
        self.assertEqual(report["summary"]["observed_writes"], 1)
        self.assertEqual([row["outcome"] for row in report["actions"]], ["succeeded", "failed", "unknown"])
        self.assertEqual(report["actions"][0]["target"], "project/app.py")
        self.assertEqual(report["availability"], "partial")

    def test_compound_shell_output_is_not_guessed(self):
        report = self.analyze(call("a", "Bash", {"command": f"cat '{self.skill}/SKILL.md'; echo success"}), result("a", "No such file\nsuccess"))
        self.assertEqual(report["availability"], "partial")
        self.assertEqual(report["summary"]["guidance_reads"], 0)

    def test_multiple_direct_read_paths_do_not_double_count_output_characters(self):
        report = self.analyze(call("a", "Bash", {"command": f"cat '{self.skill}/SKILL.md' '{self.skill}/lib/guide/SKILL.md'"}), result("a", "combined"))
        self.assertEqual(report["summary"]["guidance_reads"], 2)
        self.assertEqual(report["summary"]["guidance_returned_chars"], len("combined"))
        self.assertTrue(all(row["returned_chars"] is None for row in report["actions"]))

    def test_writes_classified_without_contents_or_absolute_host_paths(self):
        report = self.analyze(call("a", "Write", {"file_path": str(self.root / "check_map.py"), "content": "secret text"}), result("a", "created"),
                              call("b", "Edit", {"file_path": "/outside/personal.txt", "old_string": "secret"}), result("b", "edited"))
        self.assertEqual(report["summary"]["observed_writes"], 2)
        self.assertEqual([r["target"] for r in report["actions"]], ["trial/check_map.py", "outside-owned-trial"])
        self.assertNotIn("secret", json.dumps(report))
        self.assertNotIn("personal", json.dumps(report))

    def test_empty_partial_and_action_caps_remain_explicit(self):
        self.assertEqual(activity.analyze("claude", "", self.binding)["availability"], "unavailable")
        self.assertEqual(activity.analyze("claude", "not json", self.binding)["availability"], "unavailable")
        with patch.object(activity, "MAX_ACTIONS", 1):
            report = self.analyze(call("a", "Read", {"file_path": str(self.skill / "SKILL.md")}), result("a", "abc"),
                                  call("b", "Read", {"file_path": str(self.skill / "SKILL.md")}), result("b", "abc"))
        self.assertEqual(report["omitted_actions"], 1)
        self.assertEqual(report["availability"], "partial")
        self.assertEqual(self.analyze(interrupted=True)["availability"], "partial")

    def test_codex_pack_helper_and_role_paths(self):
        pack = self.root / "codex"
        for relative in ("scripts/context.py", "references/roles/explorer.md", "references/skills/foo/GUIDE.md"):
            path = pack / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("guide")
        binding = activity.bind(self.project, pack)
        report = activity.analyze("codex", trace(
            {"type": "item.completed", "item": {"type": "command_execution", "command": f"python3 {pack}/scripts/context.py --json", "exit_code": 0, "aggregated_output": '{"project_map":{"status":"stale"}}'}},
            {"type": "turn.completed"}), binding)
        self.assertEqual(report["summary"]["helper_successes"], 1)
        self.assertEqual(report["actions"][0]["map_status"], "stale")


class ScopeAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "source.py").write_text("untouched")

    def test_records_sibling_metadata_without_contents_and_ignores_project(self):
        (self.root / "check_map.py").write_text("not collected")
        audit = runtime.audit_trial_parent(self.project)
        self.assertFalse(audit["clean"])
        self.assertEqual(audit["entries"], [{"path": "check_map.py", "kind": "file", "size": 13}])
        self.assertNotIn("not collected", json.dumps(audit))
        (self.root / "check_map.py").unlink()
        self.assertTrue(runtime.audit_trial_parent(self.project)["clean"])

    def test_symlink_metadata_is_recorded_without_following_it(self):
        (self.root / "link").symlink_to(self.project, target_is_directory=True)
        audit = runtime.audit_trial_parent(self.project)
        self.assertEqual(audit["entries"], [{"path": "link", "kind": "symlink", "size": None}])

    def test_scope_audit_write_failure_cannot_preserve_success(self):
        from evals.end_to_end.run import capture_scope
        for residue in (False, True):
            with self.subTest(residue=residue):
                if residue:
                    (self.root / "check_map.py").write_text("validator")
                trial = {"status": "completed", "task_success": True, "diagnostics": []}
                with patch.object(runtime, "write_json", side_effect=OSError("disk unavailable")):
                    with self.assertRaises(OSError):
                        with capture_scope(self.project, trial, self.root / "artifacts", {}):
                            pass
                self.assertNotEqual(trial["status"], "completed")
                self.assertIsNot(trial["task_success"], True)
                self.assertEqual(trial["scope_check"]["passed"], not residue)

    def test_limits_cannot_claim_clean(self):
        (self.root / "extra").mkdir()
        (self.root / "extra/file").write_text("x")
        for kwargs in ({"max_entries": 1}, {"max_seconds": 0}):
            audit = runtime.audit_trial_parent(self.project, **kwargs)
            self.assertEqual(audit["availability"], "partial")
            self.assertIsNot(audit["clean"], True)
        audit = runtime.audit_trial_parent(self.root / "missing/project")
        self.assertEqual(audit["availability"], "unavailable")
        self.assertIsNone(audit["clean"])


if __name__ == "__main__":
    unittest.main()
