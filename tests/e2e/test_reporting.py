"""Offline tests for blinded review and paired report denominators."""

import contextlib
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import tempfile
import unittest

from evals.end_to_end import run as runner
from evals.end_to_end.reporting import DIMENSIONS, audit, create_review, import_review, report


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

    def save(self, extra_schedule=None, config=None):
        schedule = [{k: trial[k] for k in ("client", "condition", "fixture_id", "repetition")} for trial in self.trials]
        schedule.extend(extra_schedule or [])
        (self.root / "results.json").write_text(json.dumps({"schema_version": 1, "trials": self.trials}))
        batch = {"schema_version": 1, "suite": "smoke", "seed": 7, "provenance": {"digest": "fixture"}, "schedule": schedule}
        if config:
            batch["config"] = config
        (self.root / "batch.json").write_text(json.dumps(batch))

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

    def usage(self, cost, **split):
        return {"input_tokens": 5, "output_tokens": 1, "cached_input_tokens": 9, "cost_usd": cost, **split}

    def test_cost_is_labelled_estimate_with_lower_bounds_and_explicit_undefined_reasons(self):
        list_basis = {"cost_basis": "list", "cost_source": "runtime_reported_estimate", "cache_creation_input_tokens": 40}
        self.add_trial(fixture="one", usage=self.usage(0.1, **list_basis))
        self.add_trial(fixture="two", status="infrastructure_error", task_success=None, usage=self.usage(0.2, **list_basis))
        self.add_trial(fixture="one", condition="dispatcher", status="task_failure", task_success=False, usage=self.usage(2.0))
        self.add_trial(fixture="two", condition="dispatcher", status="timeout", task_success=False)
        self.add_trial(fixture="one", client="claude")  # a verified success with unknown cost
        self.save(config={"clients": {"codex": {"auth": "subscription"}}})
        result = report(self.root)
        baseline, dispatcher = (self.group(result, name)["cost_accounting"] for name in ("baseline", "dispatcher"))
        self.assertEqual(baseline["measured_cost_usd_total"], math.fsum([0.1, 0.2]))  # unrounded in JSON
        self.assertEqual((baseline["invalid_attempts"], baseline["invalid_known_cost_usd"], baseline["invalid_cost_unknown_for"]), (1, 0.2, 0))
        self.assertEqual((baseline["verified_successes"], baseline["cost_usd_per_verified_success_reason"]), (1, None))
        self.assertEqual(baseline["cost_usd_per_verified_success"], math.fsum([0.1, 0.2]))
        self.assertEqual((baseline["pricing_mode"], baseline["cost_basis"]), ("subscription", ["list"]))
        self.assertIn("not billed spend", baseline["note"])
        self.assertIn("API-equivalent", baseline["note"])
        self.assertIsNone(dispatcher["measured_cost_usd_total"])  # one unknown keeps the total null...
        self.assertEqual((dispatcher["known_partial_cost_usd_total"], dispatcher["cost_unknown_for"]), (2.0, 1))  # ...beside a lower bound
        self.assertIsNone(dispatcher["cost_usd_per_verified_success"])
        self.assertEqual(dispatcher["cost_usd_per_verified_success_reason"], "zero_verified_successes")
        self.assertEqual((dispatcher["invalid_attempts"], dispatcher["invalid_known_cost_usd"]), (0, 0))  # nothing invalid costs exactly 0
        unknown = self.group(result, client="claude")["cost_accounting"]
        self.assertEqual((unknown["cost_usd_per_verified_success"], unknown["cost_usd_per_verified_success_reason"]), (None, "cost_unknown"))
        self.assertIsNone(unknown["pricing_mode"])
        usage = self.group(result)["usage"]
        self.assertEqual((usage["cache_creation_input_tokens"]["observed"], usage["cache_creation_input_tokens"]["median"]), (2, 40))
        self.assertEqual(self.group(result, "dispatcher")["usage"]["cache_read_input_tokens"]["missing"], 2)  # old trials: missing, not zero
        text = (self.root / "report.md").read_text()
        self.assertIn("| Arm total (USD, runtime-reported estimate) | 0.3000 | at least 2.0000 (lower bound; 1 unknown) |", text)
        self.assertIn("| Cost per verified success (USD, runtime-reported estimate) | 0.3000 | unavailable (zero_verified_successes) |", text)
        self.assertIn("| Billing basis (auth; runtime costBasis) | subscription; list | subscription; unknown |", text)
        self.assertIn("| Invalid attempts (known cost USD) | 1 (0.2000; 0 unknown) | 0 (0.0000; 0 unknown) |", text)
        self.assertIn("| Median cache_read_input_tokens | unavailable (0 observed; 2 missing) |", text)
        self.assertNotIn("Measured cost", text)

    def test_pending_outcomes_leave_cost_per_success_undefined(self):
        human = {"passed": True, "checks": [], "human_required": True}  # passing, awaiting a required review
        self.add_trial(fixture="auto", usage=self.usage(1.0))
        self.add_trial(fixture="review", usage=self.usage(2.0), auto_grade=human)
        self.add_trial(fixture="review", condition="dispatcher", usage=self.usage(2.0), auto_grade=human)
        result = report(self.root)
        for condition, verified in (("baseline", 1), ("dispatcher", 0)):
            cost = self.group(result, condition)["cost_accounting"]
            self.assertEqual((cost["verified_successes"], cost["cost_usd_per_verified_success"], cost["cost_usd_per_verified_success_reason"]),
                             (verified, None, "outcomes_pending"))
        self.assertIn("| Cost per verified success (USD, runtime-reported estimate) | unavailable (outcomes_pending) | unavailable (outcomes_pending) |",
                      (self.root / "report.md").read_text())

    def test_cost_per_success_counts_the_same_outcomes_as_successful_row(self):
        self.add_trial(usage=self.usage(1.0))
        create_review(self.root)
        self.submit([self.rating(self.packets()[0]["packet_id"], scope=False)])
        group = self.group(report(self.root))
        self.assertEqual((group["successful"], group["cost_accounting"]["verified_successes"]), (0, 0))
        self.assertEqual(group["cost_accounting"]["cost_usd_per_verified_success_reason"], "zero_verified_successes")

    def test_helper_execution_is_separate_from_treatment_compliance(self):
        self.add_trial(fixture="ran", condition="dispatcher", activity=self.activity(count=1))
        self.add_trial(fixture="missed", condition="dispatcher", activity=self.activity(count=0))
        self.add_trial(fixture="partial", condition="dispatcher", activity=self.activity("partial", count=0))
        group = self.group(report(self.root), "dispatcher")
        self.assertEqual(group["treatment_compliance"], {"numerator": 3, "denominator": 3, "missing": 0, "rate": 1})
        self.assertEqual(group["helper_execution"], {"numerator": 1, "denominator": 2, "missing": 1, "rate": 0.5})
        self.assertEqual(group["successful"], 3)  # a diagnostic, never a grade
        self.assertIn("| Helper execution (activity helper successes) | 0/0 observed; 0 missing | 1/2 observed; 1 missing |", (self.root / "report.md").read_text())

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

    def activity(self, availability="complete", role="explorer", count=2):
        return {"schema_version": 1, "availability": availability,
                "summary": {"helper_attempts": count, "helper_successes": count,
                            "guidance_returned_chars": 30, "roles_read": [role]},
                "route": {"role": role, "basis": "role_read", "consistent": True},
                "actions": [{"target": "private-profile/skills/secret-guide", "helper": "context"}]}

    def test_activity_complete_partial_and_missing_have_separate_denominators(self):
        self.add_trial(fixture="complete", activity=self.activity(count=3))
        self.add_trial(fixture="partial", activity=self.activity("partial", count=2))
        self.add_trial(fixture="old")
        metric = self.group(report(self.root))["activity"]["metrics"]["helper_successes"]
        self.assertEqual(metric, {"observed": 1, "missing": 2, "total": 3, "median": 3,
                                  "partial_observed_total": 2, "partial_attempts": 1})
        self.assertIn("partial lower bound", (self.root / "report.md").read_text())

    def test_helper_coverage_uses_eligible_treatment_tasks_and_retains_unknowns(self):
        def observed(availability="complete", origin=None, count=0):
            record = self.activity(availability)
            record["actions"] = [{"kind": "helper", "helper": "context", "outcome": "succeeded"}]
            if origin:
                record["actions"][0].update(map_evidence_origin=origin, map_entries=count)
            return record
        self.add_trial(fixture="auth", condition="dispatcher", category="context_retrieval", activity=observed())
        self.add_trial(fixture="stale", condition="dispatcher", category="context_freshness", activity=observed("partial", "preview", 2))
        self.add_trial(fixture="architecture", condition="dispatcher", category="architecture_discovery", activity=observed("complete", "stored", 0))
        self.add_trial(fixture="missing", condition="dispatcher", category="context_retrieval", activity=self.activity())
        self.add_trial(fixture="partial", condition="dispatcher", category="context_freshness", activity=self.activity("partial"))
        self.add_trial(fixture="trivial", condition="dispatcher", category="edit", activity=observed())
        self.add_trial(fixture="baseline", category="context_retrieval", activity=observed())
        result = report(self.root)
        coverage = result["clients"]["codex"]["helper_coverage"]
        self.assertEqual(coverage["baseline_not_applicable"], 1)
        self.assertEqual({key: coverage["context"][key] for key in ("eligible", "observed_success", "not_observed", "unknown")},
                         {"eligible": 5, "observed_success": 3, "not_observed": 1, "unknown": 1})
        self.assertIsNone(coverage["context"]["complete_rate"])
        self.assertEqual(coverage["context"]["observed_rate"], 0.75)
        self.assertEqual({key: coverage["map"][key] for key in ("eligible", "observed_success", "unknown", "nonempty_facts", "empty_facts")},
                         {"eligible": 3, "observed_success": 2, "unknown": 1, "nonempty_facts": 1, "empty_facts": 1})
        self.assertEqual(self.group(result, "dispatcher")["successful"], 6)
        self.assertIn("Helper adoption on eligible tasks", (self.root / "report.md").read_text())

    def test_route_variation_is_diagnostic_without_changing_success(self):
        self.add_trial(repetition=1, activity=self.activity(role="explorer"))
        self.add_trial(repetition=2, activity=self.activity(role="implementer"))
        result = report(self.root)
        self.assertEqual(self.group(result)["successful"], 2)
        agreement = result["clients"]["codex"]["route_agreement"]
        self.assertEqual(agreement["groups_varied"], 1)
        self.assertEqual(agreement["groups_agreed"], 0)

    def test_preparation_and_exclusions_are_private_quality_independent_diagnostics(self):
        def observed(status, availability="complete", attempt="early", outcome="succeeded"):
            record = self.activity("partial")
            record["preparation"] = {"schema_version": 1, "status": status, "availability": availability,
                                     "attempt_timing": attempt, "first_context_attempt_outcome": outcome}
            record["actions"] = [{"kind": "helper", "helper": "context", "outcome": "succeeded",
                                  "context_exclusions": {"availability": "complete", "automatic_enabled": True,
                                  "automatic_count": 2, "manual_count": 0, "applied_count": 2, "unresolved_count": 0, "unresolved_total": 0}}]
            return record
        self.add_trial(fixture="first", condition="dispatcher", category="context_retrieval", activity=observed("before_investigation"))
        self.add_trial(fixture="late", condition="dispatcher", category="context_freshness", activity=observed("after_investigation", "partial", "early", "denied"))
        self.add_trial(fixture="uncertain", condition="dispatcher", category="architecture_discovery", activity=observed("before_investigation", "partial", "unknown"))
        self.add_trial(fixture="old", condition="dispatcher", category="context_retrieval", activity=self.activity())
        self.add_trial(fixture="trivial", condition="dispatcher", category="edit", activity=observed("before_investigation"))
        self.add_trial(fixture="baseline", category="context_retrieval", activity=observed("before_investigation"))
        output = report(self.root)
        coverage = output["clients"]["codex"]["helper_coverage"]
        prep = coverage["preparation"]
        self.assertEqual({key: prep[key] for key in ("eligible", "before_investigation", "after_investigation", "not_observed", "unknown")},
                         {"eligible": 4, "before_investigation": 1, "after_investigation": 1, "not_observed": 0, "unknown": 2})
        self.assertEqual(prep["first_attempt"], {"early": 2, "late": 0, "not_observed": 0, "unknown": 2, "early_failed_or_denied": 1})
        exclusions = coverage["exclusions"]
        self.assertEqual(exclusions["successful_context_calls"], 3)
        self.assertEqual(exclusions["counts"]["automatic_count"], {"observed_calls": 3, "total": 6})
        self.assertEqual(self.group(output, "dispatcher")["successful"], 5)
        self.assertIn("First context attempt:", (self.root / "report.md").read_text())
        create_review(self.root)
        self.assertNotIn("preparation", json.dumps(self.packets()))
        self.assertNotIn("automatic_count", json.dumps(self.packets()))

    def test_missing_exclusion_counts_are_unknown_not_zero(self):
        record = self.activity()
        record["actions"] = [{"kind": "helper", "helper": "context", "outcome": "succeeded"},
                             {"kind": "helper", "helper": "context", "outcome": "succeeded", "context_exclusions": {
                                 "availability": "partial", "applied_count": 1, "manual_count": True}}]
        self.add_trial(condition="dispatcher", category="context_retrieval", activity=record)
        exclusions = report(self.root)["clients"]["codex"]["helper_coverage"]["exclusions"]
        self.assertEqual((exclusions["unknown_metadata"], exclusions["partial_metadata"]), (1, 1))
        self.assertEqual(exclusions["counts"]["applied_count"], {"observed_calls": 1, "total": 1})
        self.assertEqual(exclusions["counts"]["manual_count"], {"observed_calls": 0, "total": 0})

    def test_matching_cleanup_observations_never_establish_absence_or_change_grade(self):
        record = self.activity()
        record["actions"] = [{"kind": "write", "target": "trial/check.py", "outcome": "succeeded"},
                             {"kind": "cleanup_attempt", "target": "trial/check.py", "outcome": "succeeded", "matched_prior_write": True},
                             {"kind": "cleanup_attempt", "target": "trial/check.py", "outcome": "failed", "matched_prior_write": True},
                             {"kind": "cleanup_attempt", "target": "outside-owned-trial", "outcome": "succeeded", "matched_prior_write": True}]
        self.add_trial(activity=record, scope_audit={"schema_version": 1, "availability": "complete", "entry_count": 0}, scope_check={"passed": True})
        create_review(self.root)
        scope = self.packets()[0]["scope_evidence"]
        write = scope["outside_project_writes"][0]
        self.assertEqual(write["observed_matched_cleanup_successes"], 1)
        self.assertEqual(scope["outside_project_write_count"], 1)
        self.assertTrue(scope["requires_human_inspection"])
        self.assertEqual(scope["outside_audit_remaining_state"], "unknown")
        self.assertIn("do not independently verify file absence", write["cleanup_limit"])
        self.assertEqual(self.group(report(self.root))["successful"], 1)

    def test_scope_evidence_is_neutral_and_private_activity_is_never_blinded_packet_data(self):
        self.add_trial(activity=self.activity(), scope_audit={"schema_version": 1, "availability": "complete",
                       "entry_count": 1, "entries": [{"path": "/Users/private-profile/model-secret"}]},
                       scope_check={"passed": False, "reason": "/private/leak"}, task_success=False,
                       auto_grade={"passed": True, "checks": [{"name": "code", "passed": True}], "human_required": False})
        create_review(self.root)
        packet = self.packets()[0]
        self.assertFalse(packet["scope_evidence"]["passed"])
        self.assertEqual(packet["scope_evidence"]["residue_entries"], 1)
        for text in ("private-profile", "secret-guide", "model-secret", "explorer", "helper_successes", "/private/leak"):
            self.assertNotIn(text, json.dumps(packet))
        grouped = self.group(report(self.root))
        self.assertEqual(grouped["artifact_acceptance"]["numerator"], 1)
        self.assertEqual(grouped["successful"], 0)
        self.assertEqual(grouped["scope_acceptance"]["numerator"], 0)
        self.assertIn("Scope evidence", (self.root / "review/packets.md").read_text())

    def test_successful_writes_beyond_owned_audit_require_inspection_without_changing_grade(self):
        activity = self.activity("partial")
        activity["actions"] = [
            {"kind": "write", "target": "outside-owned-trial", "outcome": "succeeded"},
            {"kind": "write", "target": "trial/check_map.py", "outcome": "succeeded"},
            {"kind": "write", "target": "outside-owned-trial", "outcome": "denied"},
            {"kind": "write", "target": "outside-owned-trial", "outcome": "failed"},
            {"kind": "write", "target": "project/source.py", "outcome": "succeeded"},
            {"kind": "guidance_read", "target": "package/roles/explorer.md", "outcome": "succeeded"},
        ]
        self.add_trial(activity=activity, scope_audit={"schema_version": 1, "availability": "complete",
                       "entry_count": 0, "entries": [], "clean": True}, scope_check={"passed": True})
        create_review(self.root)
        scope = self.packets()[0]["scope_evidence"]
        self.assertTrue(scope["passed"])
        self.assertEqual(scope["residue_entries"], 0)
        self.assertTrue(scope["requires_human_inspection"])
        self.assertEqual(scope["outside_project_write_count"], 2)
        self.assertEqual(scope["write_observation_availability"], "partial")
        self.assertEqual(scope["outside_audit_remaining_state"], "unknown")
        self.assertEqual(scope["outside_project_writes"], [
            {"target": "outside-owned-trial", "observed_successful_writes": 1, "remaining_state": "unknown"},
            {"target": "trial/check_map.py", "observed_successful_writes": 1, "remaining_state": "see_owned_directory_audit"}])
        self.assertEqual(self.group(report(self.root))["successful"], 1)
        self.assertIn("human inspection required: True", (self.root / "review/packets.md").read_text())
        self.assertNotIn("explorer", json.dumps(scope))

    def test_outside_write_flag_is_conservative_even_with_later_cleanup_evidence(self):
        activity = self.activity()
        activity["actions"] = [{"kind": "write", "target": "outside-owned-trial", "outcome": "succeeded"}]
        trial = self.add_trial(activity=activity, scope_audit={"schema_version": 1, "availability": "complete", "entry_count": 0}, scope_check={"passed": True})
        self.trace(trial, [{"type": "item.completed", "item": {"type": "command_execution", "command": "rm -rf /tmp/cleanup && echo removed", "exit_code": 0, "aggregated_output": "removed"}}])
        create_review(self.root)
        self.assertTrue(self.packets()[0]["scope_evidence"]["requires_human_inspection"])
        self.assertEqual(self.packets()[0]["scope_evidence"]["outside_audit_remaining_state"], "unknown")
        self.assertTrue(trial["task_success"])

    def test_outside_write_paths_cannot_leak_identity_routing_or_escape(self):
        activity = self.activity()
        activity["actions"] = [{"kind": "write", "target": target, "outcome": "succeeded"} for target in (
            "trial/explorer/report.md", "trial/claude-baseline/secret.md", "trial/../outside", "trial/evil\nHeading")]
        self.add_trial(activity=activity, scope_audit={"schema_version": 1, "availability": "complete", "entry_count": 0}, scope_check={"passed": True})
        create_review(self.root)
        scope = self.packets()[0]["scope_evidence"]
        self.assertEqual(scope["outside_project_writes"], [{"target": "trial/[path withheld]", "observed_successful_writes": 4, "remaining_state": "see_owned_directory_audit"}])
        for secret in ("explorer", "claude", "baseline", "secret.md", "Heading", "../"):
            self.assertNotIn(secret, json.dumps(scope))

    def test_scope_residue_is_bounded_neutral_metadata_and_incomplete_audit_requires_inspection(self):
        entries = [{"path": "check_map.py", "kind": "file", "size": 123},
                   {"path": "/Users/private/trial", "kind": "file", "size": 5},
                   {"path": "../escape", "kind": "symlink", "size": 19},
                   {"path": "explorer/notes.md", "kind": "directory", "size": 7},
                   {"path": "scratch.tmp", "kind": "untrusted arbitrary kind", "size": True}]
        entries += [{"path": f"scratch-{index}.py", "kind": "file", "size": 0} for index in range(50)]
        self.add_trial(activity=self.activity(), scope_audit={"schema_version": 1, "availability": "partial",
                       "entry_count": len(entries), "entries": entries}, scope_check={"passed": None})
        create_review(self.root)
        scope = self.packets()[0]["scope_evidence"]
        self.assertTrue(scope["requires_human_inspection"])
        self.assertIsNone(scope["passed"])
        self.assertEqual(len(scope["residue"]), 50)
        self.assertEqual(scope["residue_omitted"], 5)
        self.assertEqual(scope["residue"][0], {"path": "check_map.py", "kind": "file", "size": 123})
        self.assertEqual(scope["residue"][2], {"path": "[path withheld]", "kind": "symlink", "size": None})
        self.assertEqual(scope["residue"][4], {"path": "scratch.tmp", "kind": "unknown", "size": None})
        for secret in ("/Users", "../escape", "explorer", "untrusted arbitrary"):
            self.assertNotIn(secret, json.dumps(scope))
        self.assertIn('"path": "check_map.py"', (self.root / "review/packets.md").read_text())

    def test_old_packets_do_not_gain_scope_fields_or_change_from_private_metrics(self):
        trial = self.add_trial()
        create_review(self.root)
        old = self.packets()
        self.assertNotIn("scope_evidence", old[0])
        trial["activity"] = self.activity()
        trial["activity"]["actions"] = [{"kind": "write", "target": "outside-owned-trial", "outcome": "succeeded"}]
        self.save()
        create_review(self.root)
        self.assertEqual(self.packets(), old)


class AuditTests(unittest.TestCase):
    """Read-only re-derivation from raw events; synthetic batches in the runner's own layout."""

    CWD = "/recorded/trial/project"
    PACK = "/recorded/profile/skills/agent-dispatcher"

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.output = Path(temp.name) / "output"
        package = self.output / "packages/claude"
        package.mkdir(parents=True)
        (package / "SKILL.md").write_text("# Agent Dispatcher\n")
        (package / "context.py").write_text("print('{}')\n")

    def terminal(self, cost):
        return {"type": "result", "subtype": "success", "result": "done", "total_cost_usd": cost, "duration_ms": 2000,
                "duration_api_ms": 1500, "num_turns": 4, "modelUsage": {"m": {"costBasis": "list"}},
                "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 40,
                          "cache_creation": {"ephemeral_1h_input_tokens": 40, "ephemeral_5m_input_tokens": 0}}}

    def batch(self, name, rows):
        batch = self.output / "batches" / name
        trials = []
        for condition, status, success, cost, events, extra in rows:
            ident = f"claude-fx-1-{condition}"
            trial = {"id": ident, "client": "claude", "condition": condition, "fixture_id": "fx", "repetition": 1, "category": "edit",
                     "status": status, "task_success": success, "artifact_dir": "trials/" + ident,
                     "auto_grade": {"passed": success is True, "human_required": False,
                                    "checks": [{"name": "behavior", "passed": success is True}]},
                     "treatment_invoked": None if condition == "baseline" else True, "elapsed_seconds": 3.0,
                     # Stored the way older runs stored it: four keys, no split.
                     "usage": {"input_tokens": 10 if cost else None, "output_tokens": 5 if cost else None,
                               "cached_input_tokens": 100 if cost else None, "cost_usd": cost},
                     "effective_settings": {"auth": "subscription"}, **extra}
            trials.append(trial)
            (batch / trial["artifact_dir"]).mkdir(parents=True)
            init = {"type": "system", "subtype": "init", "cwd": self.CWD}
            (batch / trial["artifact_dir"] / "events.jsonl").write_text("\n".join(json.dumps(event) for event in [init, *events]) + "\n")
        schedule = [{k: trial[k] for k in ("client", "condition", "fixture_id", "repetition")} for trial in trials]
        (batch / "batch.json").write_text(json.dumps({"schema_version": 1, "suite": name, "schedule": schedule, "config": {
            "conditions": ["baseline", "dispatcher"], "clients": {"claude": {"auth": "subscription", "profile_dir": "/recorded/profile"}}}}))
        (batch / "results.json").write_text(json.dumps({"schema_version": 1, "trials": trials}))
        return batch

    def test_audit_rederives_totals_flags_helper_gap_and_writes_nothing(self):
        helper = (f'cd "{self.CWD}" && python3 -B "{self.PACK}/context.py" --project "{self.CWD}" --task=x --json 2>&1 | head -200')
        replay = {"type": "user", "isReplay": True, "message": {"role": "user", "content":
                  "<command-message>agent-dispatcher</command-message>\n<command-name>/agent-dispatcher</command-name>"}}
        helper_events = [replay, {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "h1", "name": "Bash", "input": {"command": helper}}]}},
                         {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "h1", "is_error": False,
                                                                   "content": json.dumps({"schema_version": 1})}]}}]
        missed = {"activity": {"schema_version": 1, "availability": "partial", "summary": {"helper_attempts": 0, "helper_successes": 0}}}
        first = self.batch("first", [("baseline", "completed", True, 0.1, [self.terminal(0.1)], {}),
                                     ("dispatcher", "completed", True, 0.2, [*helper_events, self.terminal(0.2)], missed)])
        second = self.batch("second", [("baseline", "task_failure", False, 0.3, [self.terminal(0.3)], {}),
                                       ("dispatcher", "timeout", False, None, helper_events[:1], {})])  # no terminal event: usage unknown
        digests = lambda: {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(self.output.rglob("*")) if path.is_file()}  # noqa: E731
        before = digests()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(runner.main(["audit", "--batch", str(first), "--batch", str(second)]), 0)
        self.assertEqual(digests(), before)  # read-only: every file byte-identical and nothing added
        printed = stdout.getvalue()
        result = json.loads(printed)
        self.assertEqual(result, audit([first, second]))
        one, two = result["batches"]
        self.assertEqual(one["totals"]["cost_usd"]["total"], math.fsum([0.1, 0.2]))
        self.assertIn(repr(math.fsum([0.1, 0.2])), printed)  # JSON keeps the unrounded value
        self.assertEqual(one["totals"]["cache_creation_input_tokens"]["total"], 80)
        trial = one["trials"][1]
        self.assertEqual(trial["usage"]["cost_usd"], {"value": 0.2, "provenance": "verified"})
        self.assertEqual(trial["usage"]["cache_creation_input_tokens"], {"value": 40, "provenance": "derived"})  # not stored by old runs
        self.assertEqual(trial["usage"]["cost_basis"]["value"], "list")
        self.assertEqual(trial["runtime"]["num_turns"], {"value": 4, "provenance": "derived"})
        self.assertEqual(trial["auth"], {"value": "subscription", "provenance": "stored_only"})
        self.assertEqual(trial["treatment_invoked"]["provenance"], "verified")
        helper_row = trial["helper_successes"]
        self.assertEqual((helper_row["linked_events"]["value"], helper_row["stored_activity"]["value"], helper_row["current_attribution"]["value"]), (1, 0, 1))
        self.assertTrue(helper_row["discrepancy"])
        self.assertTrue(helper_row["resolved_by_current_attribution"])
        self.assertEqual(one["discrepancies"], [{"trial": "claude-fx-1-dispatcher", "fields": ["helper_successes"]}])
        arm = one["clients"]["claude"]["arms"]["dispatcher"]
        self.assertEqual((arm["cost"]["cost_usd_per_verified_success"], arm["cost"]["pricing_mode"]), (0.2, "subscription"))
        self.assertEqual(arm["totals"]["cost_input_provenance"], {"verified": 1})
        self.assertEqual(arm["medians"]["duration_api_ms"], 1500)
        self.assertEqual(one["clients"]["claude"]["pairs"]["vs_baseline"]["dispatcher"]["both_pass"], 1)
        # Missing usage stays unknown; zero successes leave cost per success undefined with a reason, never 0.
        self.assertEqual(two["trials"][1]["usage"]["cost_usd"], {"value": None, "provenance": "unavailable"})
        self.assertEqual(two["totals"]["cost_usd"], {"total": None, "known_partial_total": 0.3, "unknown_for": 1})
        for name in ("baseline", "dispatcher"):
            cost = two["clients"]["claude"]["arms"][name]["cost"]
            self.assertEqual((cost["cost_usd_per_verified_success"], cost["cost_usd_per_verified_success_reason"]), (None, "zero_verified_successes"))
        self.assertEqual(two["clients"]["claude"]["arms"]["dispatcher"]["counts"]["verified_successes"], 0)
        combined = result["combined"]
        self.assertEqual(combined["label"], "sum across batches; not an experimental estimate")
        self.assertEqual((combined["trials"], combined["cost_usd"]["total"], combined["cost_usd"]["known_partial_total"]), (4, None, math.fsum([0.1, 0.2, 0.3])))
        self.assertNotIn("combined", audit([first]))

    def test_audit_flags_stored_mismatches_and_links_helpers_by_the_attribution_rule(self):
        replay = {"type": "user", "isReplay": True, "message": {"role": "user", "content":
                  "<command-message>agent-dispatcher</command-message>\n<command-name>/agent-dispatcher</command-name>"}}

        def tool(ident, name, inputs, content, error=False):
            return [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": ident, "name": name, "input": inputs}]}},
                    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": ident, "is_error": error, "content": content}]}}]

        def dispatcher(name, events, stored, **extra):
            record = {"activity": {"schema_version": 1, "availability": "complete", "summary": {"helper_attempts": stored, "helper_successes": stored}}}
            batch = self.batch(name, [("dispatcher", "completed", True, 0.2, [replay, *events, self.terminal(0.2)], {**record, **extra})])
            return audit([batch])["batches"][0]

        # Documented text mode and the cd-into-package form succeed on exit status, as attribution counts them.
        # Stored usage, runtime and treatment values that differ from the events are kept beside them and flagged.
        text = dispatcher("text", tool("t", "Bash", {"command": f'python3 -B "{self.PACK}/context.py" --project . --task=x --explain'}, "Context: 3 files")
                          + tool("c", "Bash", {"command": f"cd {self.PACK} && python3 context.py --project {self.CWD} --task x --json"}, '{"schema_version": 1}'),
                          2, usage={"input_tokens": 10, "output_tokens": 5, "cached_input_tokens": 100, "cost_usd": 0.5},
                          runtime={"num_turns": 9}, treatment_invoked=False)
        row = text["trials"][0]
        self.assertEqual(row["usage"]["cost_usd"], {"value": 0.2, "stored": 0.5, "provenance": "derived", "discrepancy": True})
        self.assertEqual(row["runtime"]["num_turns"], {"value": 4, "stored": 9, "provenance": "derived", "discrepancy": True})
        self.assertEqual(row["treatment_invoked"], {"value": True, "stored": False, "provenance": "derived", "discrepancy": True})
        self.assertEqual(text["totals"]["cost_usd"]["total"], 0.2)  # totals use the re-derived value
        helper = row["helper_successes"]
        self.assertEqual([helper[key]["value"] for key in ("linked_events", "stored_activity", "current_attribution")], [2, 2, 2])
        self.assertEqual((helper["discrepancy"], helper["resolved_by_current_attribution"]), (False, None))
        self.assertEqual(text["discrepancies"], [{"trial": "claude-fx-1-dispatcher", "fields": ["usage.cost_usd", "runtime.num_turns", "treatment_invoked"]}])
        # A piped helper's traceback is not a success, and another tool's versioned JSON is not linked to a helper.
        piped = dispatcher("piped", tool("h", "Bash", {"command": f'python3 "{self.PACK}/context.py" --json 2>&1 | head -200'}, "Traceback (most recent call last):\n  ValueError: boom")
                           + tool("r", "Read", {"file_path": f"{self.CWD}/status.json"}, '{"schema_version": 1}'), 0)
        helper = piped["trials"][0]["helper_successes"]
        self.assertEqual([helper[key]["value"] for key in ("linked_events", "stored_activity", "current_attribution")], [0, 0, 0])
        self.assertEqual((helper["discrepancy"], piped["discrepancies"]), (False, []))
        # Linked evidence that neither stored nor current attribution matches (a helper the staged package lacks) stays unresolved.
        unstaged = dispatcher("unstaged", tool("m", "Bash", {"command": f'python3 "{self.PACK}/project_map.py" show --project .'}, "Project map: fresh"), 0)
        helper = unstaged["trials"][0]["helper_successes"]
        self.assertEqual([helper[key]["value"] for key in ("linked_events", "stored_activity", "current_attribution")], [1, 0, 0])
        self.assertEqual((helper["discrepancy"], helper["resolved_by_current_attribution"]), (True, False))
        # Redaction of the saved events broke a piped helper's JSON: no linked verdict, so nothing is flagged.
        broken = '{"schema_version":1,"excerpt":"url = f\\"https://x?[redacted]""}'
        redacted = dispatcher("redacted", tool("x", "Bash", {"command": f'python3 "{self.PACK}/context.py" --json | head -50'}, broken), 1)
        helper = redacted["trials"][0]["helper_successes"]
        self.assertEqual(helper["linked_events"], {"value": None, "provenance": "unavailable", "reason": "redacted"})
        self.assertEqual((helper["discrepancy"], helper["resolved_by_current_attribution"], redacted["discrepancies"]), (False, None, []))


if __name__ == "__main__":
    unittest.main()
