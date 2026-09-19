"""Offline tests for blinded review and paired report denominators."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from evals.end_to_end.reporting import DIMENSIONS, create_review, import_review, report


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.trials = []

    def add_trial(self, fixture="edit", condition="baseline", client="codex", repetition=1, **changes):
        ident = f"{client}-{fixture}-{repetition}-{condition}"
        artifact_dir = f"trials/{ident}"
        final = self.root / artifact_dir / "final"
        final.mkdir(parents=True, exist_ok=True)
        (final / "app.py").write_text("print('finished')\n")
        trial = {
            "id": ident, "client": client, "condition": condition,
            "fixture_id": fixture, "category": "edit", "repetition": repetition,
            "status": "completed", "task_success": True,
            "auto_grade": {"passed": True, "checks": [], "human_required": False},
            "treatment_invoked": condition == "dispatcher", "elapsed_seconds": 20,
            "usage": {"input_tokens": None, "output_tokens": None, "cached_input_tokens": None, "cost_usd": None},
            "final_answer": "Fixed the requirement.", "artifact_dir": artifact_dir,
            "prompt": "Fix the requirement.", "acceptance": ["The behavior is correct."],
            "rubric": {"correctness": "The requirement works."}, "diagnostics": [],
        }
        trial.update(changes)
        self.trials.append(trial)
        self.save()
        return trial

    def save(self, extra_schedule=None):
        schedule = [{k: trial[k] for k in ("client", "condition", "fixture_id", "repetition")} for trial in self.trials]
        schedule.extend(extra_schedule or [])
        (self.root / "results.json").write_text(json.dumps({"schema_version": 1, "trials": self.trials}))
        (self.root / "batch.json").write_text(json.dumps({"schema_version": 1, "suite": "smoke", "seed": 7, "provenance": {"digest": "fixture"}, "schedule": schedule}))

    def packets(self):
        return json.loads((self.root / "review" / "packets.json").read_text())["packets"]

    def trace(self, trial, events):
        (self.root / trial["artifact_dir"] / "events.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n")

    def rating(self, packet_id, **changes):
        row = {"packet_id": packet_id, "correctness": True, "completeness": True, "scope": True, "unsupported_claims": False, "unnecessary_intervention": False, "notes": "Checked."}
        row.update(changes)
        return row

    def submit(self, rows):
        path = self.root / "ratings.json"
        path.write_text(json.dumps({"schema_version": 1, "ratings": rows}))
        return import_review(self.root, path)

    def group(self, result, condition="baseline", client="codex"):
        return result["clients"][client]["conditions"][condition]

    def test_packet_omits_identity_routing_config_and_runtime(self):
        trial = self.add_trial(condition="dispatcher", final_answer="Role: data-analyst\nSkills: secret role\nI am using agent-dispatcher for this task.\nCodex wrote the fix at /Users/a/dispatcher/trial/app.py.")
        final = self.root / trial["artifact_dir"] / "final"
        (final / ".codex").mkdir()
        (final / ".codex" / "auth.json").write_text('{"secret": "DO NOT INCLUDE"}')
        (final / "AGENTS.md").write_text("Hidden configuration")
        (final / "blob.bin").write_bytes(b"\x00\xff")
        create_review(self.root, seed=9)
        text = (self.root / "review" / "packets.json").read_text()
        for disallowed in (trial["id"], "agent-dispatcher", "Codex", "DO NOT INCLUDE", "secret role", "data-analyst", "/Users/a", "Hidden configuration"):
            self.assertNotIn(disallowed, text)
        self.assertIn("print('finished')", text)
        self.assertIn("non_text_or_unreadable", text)
        self.assertNotIn("client", self.packets()[0])
        self.assertNotIn("condition", self.packets()[0])

    def test_randomization_stable_mapping_and_opaque_ids(self):
        for n in range(5):
            self.add_trial(fixture=f"task{n}")
        create_review(self.root, seed=3)
        first = self.packets()
        self.assertTrue(all(packet["packet_id"].startswith("R-") for packet in first))
        create_review(self.root, seed=3)
        self.assertEqual(first, self.packets())
        self.assertEqual({p["packet_id"] for p in first}, {p["packet_id"] for p in self.packets()})
        self.assertEqual(5, len(set(p["packet_id"] for p in first)))

    def test_prompt_invocation_removed_without_altering_artifact_role_fields(self):
        trial = self.add_trial(condition="dispatcher", prompt="$agent-dispatcher\n\nFix this configuration.")
        (self.root / trial["artifact_dir"] / "final" / "app.yaml").write_text("role: author\nskills: editing\n")
        create_review(self.root)
        packet = self.packets()[0]
        self.assertEqual("Fix this configuration.", packet["prompt"])
        source = next(file["text"] for file in packet["artifacts"] if file["path"] == "app.yaml")
        self.assertIn("role: author", source)
        self.assertIn("skills: editing", source)

    def test_snapshot_symlinks_not_followed(self):
        trial = self.add_trial()
        outside = self.root / "private.txt"
        outside.write_text("secret material")
        (self.root / trial["artifact_dir"] / "final" / "link.txt").symlink_to(outside)
        create_review(self.root)
        self.assertNotIn("secret material", json.dumps(self.packets()))
        self.assertEqual(1, self.packets()[0]["omissions"]["symlinks"])

    def test_snapshot_path_escape_rejected(self):
        self.add_trial(artifact_dir="../escape")
        with self.assertRaisesRegex(ValueError, "relative"):
            create_review(self.root)

    def test_large_text_omitted_with_explicit_evidence_gap(self):
        trial = self.add_trial()
        (self.root / trial["artifact_dir"] / "final" / "large.txt").write_text("x" * 70000)
        create_review(self.root)
        self.assertEqual(1, self.packets()[0]["omissions"]["size_limit"])

    def test_codex_verification_trace_supports_test_claim_audit(self):
        trial = self.add_trial(condition="dispatcher", final_answer="All tests passed.")
        self.trace(trial, [
            {"type": "item.completed", "item": {"id": "skill-read", "type": "command_execution", "command": "cat /Users/me/.agents/skills/agent-dispatcher/SKILL.md", "exit_code": 0, "aggregated_output": "Role: software-engineer"}},
            {"type": "item.completed", "item": {"id": "tests", "type": "command_execution", "command": "/bin/zsh -lc 'python3 -m unittest test_app'", "exit_code": 1, "aggregated_output": "Ran 2 tests\nFAILED (failures=1)\n/Users/me/codex-private/app.py"}},
        ])
        create_review(self.root)
        evidence = self.packets()[0]["verification_evidence"]
        self.assertEqual("available", evidence["availability"])
        self.assertEqual(1, len(evidence["commands"]))
        command = evidence["commands"][0]
        self.assertEqual("python3 -m unittest test_app", command["command"])
        self.assertEqual("failed", command["outcome"])
        self.assertEqual(1, command["exit_code"])
        self.assertIn("FAILED", command["output_excerpt"])
        serialized = json.dumps(evidence)
        for disallowed in ("skill-read", "Role:", "agent-dispatcher", "codex-private", "command_execution", "zsh"):
            self.assertNotIn(disallowed, serialized)

    def test_claude_verification_joins_tool_ids_without_exposing_them(self):
        trial = self.add_trial(client="claude")
        self.trace(trial, [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "internal-secret-id", "name": "Bash", "input": {"command": "python3 -m unittest discover"}}, {"type": "tool_use", "id": "role-read", "name": "Read", "input": {"file_path": "/skills/agent-dispatcher/SKILL.md"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "role-read", "content": "Agent Dispatcher role output"}, {"type": "tool_result", "tool_use_id": "internal-secret-id", "content": [{"type": "text", "text": "Ran 3 tests\nOK"}], "is_error": False}]}},
        ])
        create_review(self.root)
        evidence = self.packets()[0]["verification_evidence"]
        self.assertEqual(1, len(evidence["commands"]))
        command = evidence["commands"][0]
        self.assertEqual("python3 -m unittest discover", command["command"])
        self.assertIsNone(command["exit_code"])
        self.assertEqual("returned; exit code unavailable", command["outcome"])
        self.assertIn("OK", command["output_excerpt"])
        self.assertNotIn("internal-secret-id", json.dumps(evidence))
        self.assertNotIn("Bash", json.dumps(evidence))

    def test_verification_missing_trace_does_not_assert_no_tests(self):
        self.add_trial()
        create_review(self.root)
        evidence = self.packets()[0]["verification_evidence"]
        self.assertEqual("unavailable", evidence["availability"])
        self.assertIn("not evidence that no verification", evidence["note"])

    def test_verification_partial_commands_do_not_claim_success(self):
        trial = self.add_trial()
        self.trace(trial, [{"type": "item.started", "item": {"id": "partial", "type": "command_execution", "command": "python3 check.py"}}])
        with (self.root / trial["artifact_dir"] / "events.jsonl").open("a") as stream:
            stream.write('{"truncated":')
        create_review(self.root)
        evidence = self.packets()[0]["verification_evidence"]
        self.assertEqual("completion unconfirmed", evidence["commands"][0]["outcome"])
        self.assertTrue(evidence["trace_partial"])

    def test_verification_excerpts_bounded(self):
        trial = self.add_trial()
        self.trace(trial, [{"type": "item.completed", "item": {"id": "test", "type": "command_execution", "command": "python3 check.py", "exit_code": 0, "aggregated_output": "test-line\n" * 10000}}])
        create_review(self.root)
        output = self.packets()[0]["verification_evidence"]["commands"][0]["output_excerpt"]
        self.assertLess(len(output), 4200)
        self.assertIn("excerpt truncated", output)

    def test_import_merges_partial_batches_without_erasing(self):
        self.add_trial(fixture="one")
        self.add_trial(fixture="two")
        create_review(self.root)
        ids = [packet["packet_id"] for packet in self.packets()]
        self.assertEqual(1, self.submit([self.rating(ids[0])])["total_reviewed"])
        self.assertEqual(2, self.submit([self.rating(ids[1])])["total_reviewed"])
        pending = {"packet_id": ids[0], **{name: None for name in DIMENSIONS}}
        result = self.submit([pending])
        self.assertEqual(2, result["total_reviewed"])
        self.assertEqual(1, result["pending_in_submission"])

    def test_bad_import_is_atomic(self):
        self.add_trial()
        create_review(self.root)
        ident = self.packets()[0]["packet_id"]
        cases = [
            [self.rating(ident), self.rating(ident)],
            [self.rating("unknown")],
            [self.rating(ident, scope=1)],
            [self.rating(ident, scope=None)],
            [self.rating(ident, correctness="true")],
            [{"packet_id": ident, "correctness": True}],
        ]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.submit(rows)
            self.assertFalse((self.root / "review-ratings.json").exists())

    def test_non_object_import_has_specific_validation_error(self):
        self.add_trial()
        create_review(self.root)
        path = self.root / "malformed-ratings.json"
        path.write_text("[]")
        with self.assertRaisesRegex(ValueError, "Ratings must have"):
            import_review(self.root, path)

    def test_changed_evidence_rejects_import_and_packet_regeneration(self):
        trial = self.add_trial()
        create_review(self.root)
        ident = self.packets()[0]["packet_id"]
        (self.root / trial["artifact_dir"] / "final" / "app.py").write_text("changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.submit([self.rating(ident)])
        with self.assertRaisesRegex(ValueError, "changed"):
            create_review(self.root)

    def test_subjective_outcome_remains_pending_until_review(self):
        trial = self.add_trial(task_success=None, auto_grade={"passed": True, "human_required": True})
        result = report(self.root)
        self.assertEqual(1, self.group(result)["pending_outcomes"])
        self.assertIsNone(self.group(result)["complete_success_rate"])
        create_review(self.root)
        self.submit([self.rating(self.packets()[0]["packet_id"])])
        result = report(self.root)
        self.assertEqual(1, self.group(result)["complete_success_rate"])
        self.assertEqual(0, self.group(result)["required_reviews_pending"])

    def test_report_refuses_changed_reviewed_evidence(self):
        trial = self.add_trial()
        create_review(self.root)
        self.submit([self.rating(self.packets()[0]["packet_id"])])
        (self.root / trial["artifact_dir"] / "final" / "app.py").write_text("changed")
        with self.assertRaisesRegex(ValueError, "stale ratings"):
            report(self.root)

    def test_failed_subjective_auto_check_still_requires_review_for_complete_rate(self):
        self.add_trial(task_success=False, auto_grade={"passed": False, "human_required": True})
        group = self.group(report(self.root))
        self.assertEqual(0, group["graded_success_rate"])
        self.assertEqual(1, group["required_reviews_pending"])
        self.assertIsNone(group["complete_success_rate"])

    def test_optional_review_can_reveal_objective_scope_failure(self):
        self.add_trial()
        create_review(self.root)
        self.submit([self.rating(self.packets()[0]["packet_id"], scope=False)])
        self.assertEqual(0, self.group(report(self.root))["successful"])

    def test_missing_usage_is_unavailable_not_zero(self):
        self.add_trial()
        result = self.group(report(self.root))
        for measure in result["usage"].values():
            self.assertIsNone(measure["median"])
            self.assertIsNone(measure["total_observed"])
            self.assertEqual(1, measure["missing"])

    def test_zero_usage_is_observed_but_negative_and_boolean_are_missing(self):
        self.add_trial(usage={"input_tokens": 0, "output_tokens": -1, "cached_input_tokens": True, "cost_usd": None})
        usage = self.group(report(self.root))["usage"]
        self.assertEqual(0, usage["input_tokens"]["median"])
        self.assertEqual(1, usage["input_tokens"]["observed"])
        self.assertIsNone(usage["output_tokens"]["median"])
        self.assertIsNone(usage["cached_input_tokens"]["median"])

    def test_timeout_counts_failure_invalid_attempts_visible(self):
        self.add_trial(fixture="one", status="timeout", task_success=None)
        self.add_trial(fixture="two", status="authentication_failure", task_success=None)
        self.add_trial(fixture="three", status="infrastructure_error", task_success=None)
        group = self.group(report(self.root))
        self.assertEqual(3, group["attempted"])
        self.assertEqual(2, group["invalid"])
        self.assertEqual(1, group["graded"])
        self.assertEqual(0, group["successful"])
        self.assertEqual(3, group["elapsed_seconds"]["observed"])
        self.assertIsNone(group["complete_success_rate"])

    def test_missing_dispatcher_not_dropped_from_task_success(self):
        self.add_trial(condition="dispatcher", treatment_invoked=False)
        group = self.group(report(self.root), "dispatcher")
        self.assertEqual(1, group["successful"])
        self.assertEqual(0, group["treatment_compliance"]["rate"])
        self.assertEqual(1, group["treatment_compliance"]["denominator"])

    def test_artifact_acceptance_remains_distinct_from_compliance_failure(self):
        self.add_trial(condition="dispatcher", status="task_failure", task_success=False, treatment_invoked=False, auto_grade={"passed": True, "human_required": False, "checks": [{"name": "behavior", "passed": True}]})
        group = self.group(report(self.root), "dispatcher")
        self.assertEqual(0, group["successful"])
        self.assertEqual(1, group["artifact_acceptance"]["numerator"])
        self.assertEqual(1, group["artifact_acceptance"]["denominator"])
        self.assertEqual(0, group["treatment_compliance"]["numerator"])

    def test_clients_and_repetitions_not_pooled_or_best_selected(self):
        self.add_trial(repetition=1, task_success=False)
        self.add_trial(repetition=2, task_success=True)
        self.add_trial(client="claude", task_success=True)
        result = report(self.root)
        self.assertEqual(0.5, self.group(result)["graded_success_rate"])
        self.assertEqual(1, self.group(result, client="claude")["graded_success_rate"])
        self.assertNotIn("success_rate", result)

    def test_paired_flips_and_deltas_use_exact_task_repetition(self):
        self.add_trial(repetition=1, task_success=False, elapsed_seconds=30)
        self.add_trial(repetition=1, condition="dispatcher", task_success=True, elapsed_seconds=20)
        self.add_trial(repetition=2, task_success=True, elapsed_seconds=10)
        self.add_trial(repetition=2, condition="dispatcher", task_success=False, elapsed_seconds=40)
        self.add_trial(fixture="missing")
        pairs = report(self.root)["clients"]["codex"]["pairs"]
        self.assertEqual(1, pairs["improved"])
        self.assertEqual(1, pairs["regressed"])
        self.assertEqual(1, pairs["missing_attempt"])
        self.assertEqual(2, pairs["comparable"])
        self.assertEqual(10, pairs["deltas_dispatcher_minus_baseline"]["elapsed_seconds"]["median"])
        self.assertEqual(2, pairs["deltas_dispatcher_minus_baseline"]["input_tokens"]["missing_pairs"])

    def test_invalid_and_pending_pairs_shown(self):
        self.add_trial(fixture="invalid")
        self.add_trial(fixture="invalid", condition="dispatcher", status="invalid_configuration")
        self.add_trial(fixture="pending")
        self.add_trial(fixture="pending", condition="dispatcher", task_success=None, auto_grade={"passed": True, "human_required": True})
        pairs = report(self.root)["clients"]["codex"]["pairs"]
        self.assertEqual(1, pairs["invalid"])
        self.assertEqual(1, pairs["pending"])
        self.assertEqual(0, pairs["comparable"])

    def test_human_rates_show_observed_denominator(self):
        self.add_trial(fixture="one")
        self.add_trial(fixture="two")
        create_review(self.root)
        self.submit([self.rating(self.packets()[0]["packet_id"], unsupported_claims=True, unnecessary_intervention=True)])
        group = self.group(report(self.root))
        self.assertEqual({"numerator": 0, "denominator": 1, "missing": 1, "rate": 0}, group["claim_accuracy"])
        self.assertEqual({"numerator": 1, "denominator": 1, "missing": 1, "rate": 1}, group["unnecessary_intervention"])

    def test_unattempted_scheduled_trials_visible(self):
        self.add_trial()
        self.save(extra_schedule=[{"client": "codex", "condition": "dispatcher", "fixture_id": "edit", "repetition": 1}])
        result = report(self.root)
        self.assertEqual(1, self.group(result, "dispatcher")["unattempted"])
        self.assertEqual(0, self.group(result, "dispatcher")["attempted"])
        self.assertEqual(1, result["clients"]["codex"]["pairs"]["missing_attempt"])

    def test_empty_results_can_report_scheduled_clients(self):
        self.save(extra_schedule=[{"client": "claude", "condition": "baseline", "fixture_id": "one", "repetition": 1}])
        (self.root / "results.json").unlink()
        result = report(self.root)
        self.assertEqual(0, self.group(result, client="claude")["attempted"])
        self.assertIsNone(self.group(result, client="claude")["graded_success_rate"])

    def test_duplicate_results_rejected_not_silently_overwritten(self):
        trial = self.add_trial()
        self.trials.append(copy.deepcopy(trial))
        self.save()
        with self.assertRaisesRegex(ValueError, "Duplicate trial"):
            report(self.root)

    def test_report_written_with_provenance_and_no_global_success_rate(self):
        self.add_trial()
        result = report(self.root)
        self.assertEqual(result, json.loads((self.root / "report.json").read_text()))
        text = (self.root / "report.md").read_text()
        self.assertIn("Starter fixtures", text)
        self.assertIn("unavailable", text)
        self.assertEqual({"digest": "fixture"}, result["provenance"])


if __name__ == "__main__":
    unittest.main()
