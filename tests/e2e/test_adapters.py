"""Offline tests of native CLI launch isolation and trace interpretation."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from evals.end_to_end import adapters


def lines(*events):
    return "\n".join(json.dumps(event) for event in events)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dispatcher-adapter-tests-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.workspace = self.root / "workspace"
        self.profile = self.root / "profile"
        self.workspace.mkdir()
        self.profile.mkdir()
        self.executable = self.root / "fake-client"
        # Exercise subprocess argv/environment and JSON-RPC, while explicitly
        # refusing every command that could launch an actual model turn.
        source = r'''
import json, os, pathlib, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("fake-native 1.0")
elif "--help" in args:
    print("FLAGS")
elif args[:2] == ["login", "status"]:
    print("Logged in using ChatGPT", file=sys.stderr)
elif args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn":True,"authMethod":"claude.ai","email":"private@example.test"}))
elif args and args[0] == "app-server":
    for line in sys.stdin:
        request=json.loads(line)
        rid=request.get("id")
        if rid is None: continue
        if request["method"] == "initialize": result={}
        elif request["method"] == "configRequirements/read": result={"requirements":None}
        elif request["method"] == "skills/list":
            external={"name":"personal","scope":"user","path":"/outside/personal/SKILL.md","enabled":not any(a.startswith("skills.config=") and "personal" in a for a in args)}
            rows=[external,{"name":"skill-creator","scope":"system","path":"/builtin/skill-creator/SKILL.md","enabled":True}]
            skill=pathlib.Path.cwd()/".agents/skills/agent-dispatcher/SKILL.md"
            if skill.is_file():rows.append({"name":"agent-dispatcher","scope":"repo","path":str(skill),"enabled":True})
            result={"data":[{"skills":rows,"errors":[]}]}
        else: result={}
        print(json.dumps({"id":rid,"result":result}),flush=True)
elif args[:2] == ["debug", "prompt-input"]:
    text="stock skill-creator"
    if not any(a.startswith("skills.config=") and "personal" in a for a in args): text+=" /outside/personal/SKILL.md"
    if (pathlib.Path.cwd()/".agents/skills/agent-dispatcher/SKILL.md").is_file():text+=" agent-dispatcher"
    print(json.dumps([{"role":"developer","content":[{"type":"input_text","text":text}]}]))
elif "--init-only" in args:
    pass
else:
    print("Offline fake refuses model execution",file=sys.stderr)
    sys.exit(77)
'''.replace("FLAGS", " ".join(adapters._CODEX_FLAGS + adapters._CLAUDE_FLAGS))
        self.executable.write_text("#!" + sys.executable + "\n" + source)
        self.executable.chmod(0o700)
        self.spec = {"executable": str(self.executable), "model": "exact-model-id",
                     "effort": "high", "auth": "subscription", "profile_dir": str(self.profile)}

    def skill(self, client):
        path = (self.workspace / ".agents/skills/agent-dispatcher" if client == "codex"
                else self.profile / "skills/agent-dispatcher")
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text("---\nname: agent-dispatcher\n---\n# Agent Dispatcher\n")
        return path

    def test_codex_doctor_checks_inventory_and_prompt_without_model(self):
        result = adapters.doctor("codex", self.spec, self.workspace)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["evidence"]["prompt_checked"])
        self.assertEqual(result["evidence"]["disabled_external_skill_count"], 1)
        self.assertEqual(result["evidence"]["skill_catalog"], [{"name": "skill-creator", "scope": "system"}])
        self.assertNotIn("content", result["evidence"])

    def test_codex_treatment_native_invocation_and_stock_builtins(self):
        skill = self.skill("codex")
        launch = adapters.build_launch("codex", self.spec, self.workspace, skill)
        self.assertEqual(launch["stdin_prefix"], "$agent-dispatcher ")
        self.assertIn("--ignore-user-config", launch["argv"])
        self.assertIn("--ignore-rules", launch["argv"])
        self.assertIn('approval_policy="never"', launch["argv"])
        self.assertEqual(launch["effective"]["input_format"], "text")
        self.assertEqual({s["name"] for s in launch["effective"]["preflight"]["skill_catalog"]},
                         {"skill-creator", "agent-dispatcher"})
        self.assertFalse(any("bypass" in a for a in launch["argv"]))

    def test_environment_scrubs_ambient_customization_and_wrong_auth(self):
        injected = {"CLAUDE_CODE_OAUTH_TOKEN": "do-not-inherit", "CODEX_API_KEY": "do-not-inherit",
                    "OPENAI_BASE_URL": "https://wrong.example", "PYTHONPATH": "/outside",
                    "CLAUDE_CODE_SIMPLE": "1", "AGENT_DISPATCHER_ACTIVE": "1"}
        with patch.dict(os.environ, injected):
            launch = adapters.build_launch("claude", self.spec, self.workspace)
        for key in injected:
            self.assertNotIn(key, launch["env"])
        self.assertEqual(launch["env"]["CLAUDE_CONFIG_DIR"], str(self.profile))
        self.assertEqual(launch["env"]["HOME"], os.environ["HOME"])
        self.assertEqual(launch["effective"]["xdg_config_home"], "inherited")
        isolated = adapters.build_launch("claude", dict(self.spec, config_home=str(self.root)), self.workspace)
        self.assertEqual((isolated["env"]["XDG_CONFIG_HOME"], isolated["effective"]["xdg_config_home"]), (str(self.root), "trial-owned empty directory"))

    def test_api_secret_only_in_process_environment(self):
        self.spec["auth"] = "api"
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "secret-not-for-artifacts"}):
            launch = adapters.build_launch("claude", self.spec, self.workspace)
            result = adapters.doctor("claude", self.spec, self.workspace)
        self.assertTrue(result["ok"], result)
        self.assertEqual(launch["env"]["ANTHROPIC_API_KEY"], "secret-not-for-artifacts")
        self.assertNotIn("secret-not-for-artifacts", json.dumps(launch["effective"]))
        self.assertNotIn("secret-not-for-artifacts", json.dumps(result))
        self.assertNotIn("secret-not-for-artifacts", " ".join(launch["argv"]))

    def test_doctor_auth_output_does_not_capture_account_identifiers(self):
        result = adapters.doctor("claude", self.spec, self.workspace)
        self.assertTrue(result["ok"], result)
        self.assertNotIn("private@example.test", json.dumps(result))

    def test_missing_api_key_is_clear_no_model_failure(self):
        self.spec["auth"] = "api"
        with patch.dict(os.environ, {}, clear=True):
            result = adapters.doctor("claude", self.spec, self.workspace)
        self.assertFalse(result["ok"])
        self.assertIn("ANTHROPIC_API_KEY", " ".join(result["errors"]))

    def test_claude_launch_excludes_project_discovery_and_requires_sandbox(self):
        launch = adapters.build_launch("claude", self.spec, self.workspace, self.skill("claude"))
        argv = launch["argv"]
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "user")
        self.assertEqual(launch["stdin_prefix"], "/agent-dispatcher ")
        self.assertEqual(launch["effective"]["input_format"], "stream-json")
        settings = json.loads(argv[argv.index("--settings") + 1])
        self.assertTrue(settings["disableAllHooks"])
        self.assertTrue(settings["sandbox"]["failIfUnavailable"])
        self.assertFalse(settings["sandbox"]["allowUnsandboxedCommands"])
        self.assertIn("Bash(python3 *)", argv[argv.index("--allowedTools") + 1])
        self.assertNotIn("--bare", argv)
        self.assertNotIn("--dangerously-skip-permissions", argv)

    def test_dirty_profile_and_unexpected_baseline_skill_fail_closed(self):
        self.skill("claude")
        result = adapters.doctor("claude", self.spec, self.workspace)
        self.assertFalse(result["ok"])
        self.assertIn("Unexpected skill", " ".join(result["errors"]))
        (self.profile / "settings.json").write_text('{"hooks":{}}')
        with self.assertRaises(adapters.AdapterError):
            adapters.build_launch("claude", self.spec, self.workspace)

    def test_personal_auth_profile_is_never_accepted(self):
        self.spec["profile_dir"] = str(Path.home() / ".codex")
        result = adapters.doctor("codex", self.spec, self.workspace)
        self.assertFalse(result["ok"])
        self.assertIn("dedicated", " ".join(result["errors"]))

    def test_unsupported_flags_fail_before_launch(self):
        response = subprocess.CompletedProcess([], 0, "native v1", "")
        with patch.object(adapters, "_command", return_value=response):
            result = adapters.doctor("claude", self.spec, self.workspace)
        self.assertFalse(result["ok"])
        self.assertIn("required isolation/capture", " ".join(result["errors"]))

    def test_codex_fails_if_prompt_probe_still_exposes_disabled_skill(self):
        with patch.object(adapters, "_command", return_value=subprocess.CompletedProcess(
            [], 0, json.dumps([{"text": "/outside/personal/SKILL.md"}]), ""
        )):
            with self.assertRaisesRegex(adapters.AdapterError, "disabled Codex skill"):
                adapters.build_launch("codex", self.spec, self.workspace)

    def test_codex_usage_and_successful_role_read(self):
        parsed = adapters.parse_events("codex", lines(
            {"type": "thread.started", "thread_id": "x"},
            {"type": "item.completed", "item": {"type": "command_execution", "exit_code": 0,
                "command": "cat '/tmp/agent-dispatcher/references/roles/implementer.md'",
                "aggregated_output": "# Implementer"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Done"}},
            {"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 7,
                                                    "cached_input_tokens": 3}},
        ))
        self.assertEqual(parsed["status"], "completed")
        self.assertEqual(parsed["usage"]["input_tokens"], 12)
        self.assertIsNone(parsed["usage"]["cost_usd"])
        # Codex token semantics are not assumed: the Claude split stays unknown.
        for key in ("uncached_input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "cost_source", "cost_basis"):
            self.assertIsNone(parsed["usage"][key], key)
        self.assertEqual(parsed["runtime"], {"duration_ms": None, "duration_api_ms": None, "num_turns": None})
        self.assertTrue(parsed["treatment_invoked"])
        self.assertEqual(parsed["final_answer"], "Done")

    def test_final_claim_and_failed_read_do_not_prove_treatment(self):
        parsed = adapters.parse_events("codex", lines(
            {"type": "item.completed", "item": {"type": "command_execution", "exit_code": 1,
                "command": "cat /tmp/agent-dispatcher/SKILL.md", "aggregated_output": "missing"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "I used agent-dispatcher."}},
            {"type": "turn.completed"},
        ))
        self.assertFalse(parsed["treatment_invoked"])

    def test_echoed_read_commands_are_not_invocation_evidence(self):
        for command in ("echo cat /tmp/agent-dispatcher/SKILL.md",
                        "printf 'cat /tmp/agent-dispatcher/SKILL.md'",
                        "git diff /tmp/agent-dispatcher/SKILL.md"):
            self.assertFalse(adapters._read_evidence("Bash", {"command": command}, "output"))
        self.assertTrue(adapters._read_evidence("Bash", {
            "command": "/bin/zsh -lc \"sed -n '1,90p' '/tmp/a b/agent-dispatcher/SKILL.md'\""
        }, "# Agent Dispatcher"))

    def test_claude_successful_skill_tool_is_evidence(self):
        parsed = adapters.parse_events("claude", lines(
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1",
                "name": "Skill", "input": {"skill": "agent-dispatcher"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1",
                "content": "Base directory for this skill: /skills/agent-dispatcher"}]}},
            {"type": "result", "subtype": "success", "result": "Done", "total_cost_usd": .02,
                "duration_ms": 9000, "duration_api_ms": 7000, "num_turns": 3,
                "modelUsage": {"model-a": {"costBasis": "list"}, "model-b": {"costBasis": "list"}},
                "usage": {"input_tokens": 100, "output_tokens": 8, "cache_read_input_tokens": 50, "cache_creation_input_tokens": 30,
                          "cache_creation": {"ephemeral_1h_input_tokens": 30, "ephemeral_5m_input_tokens": 0}}},
        ))
        self.assertTrue(parsed["treatment_invoked"])
        self.assertEqual(parsed["usage"], {
            "input_tokens": 100, "output_tokens": 8, "cached_input_tokens": 50, "cost_usd": .02,  # unchanged meaning
            "uncached_input_tokens": 100, "cache_creation_input_tokens": 30, "cache_read_input_tokens": 50,
            "cache_creation_1h_input_tokens": 30, "cache_creation_5m_input_tokens": 0,
            "cost_source": "runtime_reported_estimate", "cost_basis": "list"})
        self.assertEqual(parsed["runtime"], {"duration_ms": 9000, "duration_api_ms": 7000, "num_turns": 3})
        mixed = adapters.parse_events("claude", lines({"type": "result", "subtype": "success", "result": "Done",
            "modelUsage": {"a": {"costBasis": "list"}, "b": {"costBasis": "negotiated"}}, "usage": {"input_tokens": 1}}))
        self.assertIsNone(mixed["usage"]["cost_basis"])  # never picks one of disagreeing labels
        self.assertIsNone(mixed["usage"]["cost_source"])  # no numeric total_cost_usd
        self.assertIsNone(mixed["usage"]["cache_creation_input_tokens"])  # missing is unknown, never 0

    def test_native_expansion_replay_differs_from_invocation_request(self):
        def trace(text):
            return lines({"type": "user", "message": {"content": text}},
                         {"type": "result", "subtype": "success", "result": "done"})
        parsed = adapters.parse_events("claude", trace("/agent-dispatcher Fix it"))
        self.assertFalse(parsed["treatment_invoked"])
        parsed = adapters.parse_events("claude", trace(
            "Base directory for this skill: /a/agent-dispatcher\n# Agent Dispatcher\nRoute each request"))
        self.assertTrue(parsed["treatment_invoked"])

    def native_dispatcher_replay(self, arguments="Fix the heading.\nDo not edit code."):
        content = ("<command-message>agent-dispatcher</command-message>\n"
                   "<command-name>/agent-dispatcher</command-name>")
        if arguments:
            content += "\n<command-args>" + arguments + "</command-args>"
        return {"type": "user", "message": {"role": "user", "content": content},
                "isReplay": True, "parent_tool_use_id": None,
                "session_id": "native-session", "uuid": "native-message",
                "timestamp": "2026-09-20T03:07:00.175Z"}

    def test_claude_native_replay_proves_expansion_without_role_read(self):
        # Native slash expansion adds an internal skill-body message that Claude
        # omits from replay. Trivial tasks need no subsequent role/skill read.
        for arguments in ("", "Fix the heading.\nDo not edit code."):
            with self.subTest(arguments=arguments):
                parsed = adapters.parse_events("claude", lines(
                    self.native_dispatcher_replay(arguments),
                    {"type": "result", "subtype": "success", "result": "Done",
                     "usage": {"input_tokens": 4, "output_tokens": 20}},
                ))
                self.assertTrue(parsed["treatment_invoked"])
                self.assertEqual(parsed["status"], "completed")
                self.assertEqual(parsed["final_answer"], "Done")
                self.assertEqual(parsed["usage"]["output_tokens"], 20)

    def test_claude_native_replay_rejects_unmarked_or_spoofed_envelopes(self):
        original = self.native_dispatcher_replay()
        variants = []
        unmarked = copy.deepcopy(original)
        del unmarked["isReplay"]
        variants.append(unmarked)
        for marker in (False, "true", 1, None):
            event = copy.deepcopy(original)
            event["isReplay"] = marker
            variants.append(event)
        assistant = copy.deepcopy(original)
        assistant["type"] = "assistant"
        assistant["message"]["role"] = "assistant"
        variants.append(assistant)
        wrong_role = copy.deepcopy(original)
        wrong_role["message"]["role"] = "assistant"
        variants.append(wrong_role)
        content = original["message"]["content"]
        for text in (
            "/agent-dispatcher Fix it",
            content.replace("<command-message>agent-dispatcher", "<command-message>other"),
            content.replace("<command-name>/agent-dispatcher", "<command-name>/other"),
            "Quoted command: " + content,
            content + "\nThis is only an example.",
            content.replace("</command-args>", ""),
        ):
            event = copy.deepcopy(original)
            event["message"]["content"] = text
            variants.append(event)
        tool_result = copy.deepcopy(original)
        tool_result["message"]["content"] = [
            {"type": "tool_result", "tool_use_id": "unrelated", "content": content}]
        variants.append(tool_result)
        for index, event in enumerate(variants):
            with self.subTest(variant=index):
                parsed = adapters.parse_events("claude", lines(
                    event, {"type": "result", "subtype": "success", "result": "Done"}))
                self.assertFalse(parsed["treatment_invoked"])

    def test_missing_terminal_and_malformed_trace_are_not_task_failures(self):
        self.assertEqual(adapters.parse_events("codex", "not-json")["status"], "infrastructure_error")
        parsed = adapters.parse_events("codex", lines({"type": "turn.completed"}) + "\ninvalid")
        self.assertEqual(parsed["status"], "infrastructure_error")

    def test_missing_and_non_numeric_usage_are_unknown(self):
        parsed = adapters.parse_events("claude", lines({"type": "result", "subtype": "success",
            "usage": {"input_tokens": -1, "output_tokens": True, "cache_read_input_tokens": "10"}}))
        self.assertTrue(all(value is None for value in parsed["usage"].values()))
        self.assertTrue(parsed["usage_observed"])
        self.assertFalse(adapters.parse_events("codex", lines({"type": "turn.completed"}))["usage_observed"])

    def test_malformed_nested_events_fail_without_crashing(self):
        cases = [
            ("codex", {"type": "item.completed", "item": None}),
            ("codex", {"type": "turn.completed", "usage": None}),
            ("codex", {"type": "item.completed", "item": {"type": "agent_message", "text": []}}),
            ("claude", {"type": "result", "usage": None}),
            ("claude", {"type": "assistant", "message": {"content": None}}),
            ("claude", {"type": "assistant", "message": None}),
            ("claude", {"type": "user", "message": {"content": [{"type": "text", "text": {}}]}}),
            ("claude", {"type": "result", "errors": None}),
            ("claude", {"type": "result", "permission_denials": [None]}),
        ]
        for client, event in cases:
            with self.subTest(client=client, event=event):
                parsed = adapters.parse_events(client, lines(event))
                self.assertEqual(parsed["status"], "infrastructure_error")
                self.assertTrue(parsed["errors"])

    def test_authentication_error_is_separate(self):
        parsed = adapters.parse_events("claude", lines({"type": "result", "subtype": "error_during_execution",
            "is_error": True, "errors": ["Authentication failed: 401"]}))
        self.assertEqual(parsed["status"], "authentication_failure")
        parsed = adapters.parse_events("claude", lines({"type": "result", "subtype": "error_during_execution",
            "is_error": True, "result": "Invalid API key"}))
        self.assertEqual(parsed["status"], "authentication_failure")

    def startup(self, treatment=False):
        return {"startup": {"init_received": True, "model": self.spec["model"], "tools": ["Bash", "Read"],
            "skills": ["debug"] + (["agent-dispatcher"] if treatment else []),
            "plugins": [], "mcp_servers": [], "permissionMode": "dontAsk"},
            "treatment_invoked": False}

    def test_startup_keeps_stock_builtins_and_treatment_ignore_is_not_infra(self):
        parsed = self.startup(True)
        self.assertEqual(adapters.validate_startup("claude", self.spec, parsed, "dispatcher"), [])
        self.assertFalse(parsed["treatment_invoked"])

    def test_startup_rejects_model_switch_plugin_mcp_memory_and_baseline_dispatcher(self):
        parsed = self.startup(True)
        parsed["startup"].update(model="fallback-model", plugins=[{"name": "personal"}],
                                  mcp_servers=[{"name": "email"}], memory_paths={"auto": "/memory"})
        errors = adapters.validate_startup("claude", self.spec, parsed, "baseline")
        self.assertGreaterEqual(len(errors), 5)

    def test_learned_conditions_are_treatments(self):
        for condition in ("learned_skills", "learned_recipes", "learned_global", "learned_full", "dispatcher_lean", "dispatcher_evidence"):
            self.assertEqual(adapters.validate_startup("claude", self.spec, self.startup(True), condition), [], condition)
            self.assertTrue(adapters.validate_startup("claude", self.spec, self.startup(False), condition), condition)

    def test_startup_missing_catalog_is_unverifiable(self):
        self.assertTrue(adapters.validate_startup("claude", self.spec, {}, "baseline"))

    def test_startup_invalid_catalog_types_fail_without_crashing(self):
        for key in ("tools", "skills", "plugins", "mcp_servers", "slash_commands"):
            for bad in (None, {}, "not-a-list"):
                with self.subTest(key=key, bad=bad):
                    parsed = self.startup()
                    parsed["startup"][key] = bad
                    self.assertTrue(adapters.validate_startup("claude", self.spec, parsed, "baseline"))
        self.assertTrue(adapters.validate_startup("codex", self.spec, {"startup": None}, "baseline"))


if __name__ == "__main__":
    unittest.main()
