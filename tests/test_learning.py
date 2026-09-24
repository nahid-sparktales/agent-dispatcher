#!/usr/bin/env python3
"""Procedural learning: disabled equivalence, observations, the shared lifecycle for every kind, composition contracts,
identity and stale approvals, concurrency and rollback, evaluation statuses, invalidation propagation, shadow and canary,
installed packages and the CLI. Offline; no model, no network, no credentials."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import context
import context_packet
import experience
import learning
import learning_compose as lc
import learning_eval as le
import repo_store
from tests._learning_support import ENVIRONMENT, PACK, ROOT, TASK, LearningFixture

EVAL_ERRORS = (learning.LearningError, le.EvaluationError)


def base_guide(guide_id):
    manifest = json.loads((PACK / "catalog/resource-paths.json").read_text())
    return context_packet._guidance({"id": guide_id, "path": str(PACK / manifest["guides"][guide_id])}, PACK)


class EquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.fx = LearningFixture(self)

    def test_disabled_and_no_data_packets_and_state_are_unchanged(self):
        before = self.fx.snapshot()
        baseline = self.fx.packet()
        self.assertNotIn("learning", baseline)
        self.assertNotIn("derived", baseline["guidance"])
        self.assertEqual(self.fx.snapshot(), before)
        self.assertFalse(learning.store_exists(self.fx.directory))
        self.assertIsNone(learning.resolve(self.fx.project, PACK, TASK, settings=learning.load_settings(project=self.fx.project)))
        # Enabled (shadow, then active) with nothing recorded: byte-for-byte the same packet, still no store.
        for mode in ("shadow", "active"):
            self.fx.enable(mode)
            packet = self.fx.packet()
            self.assertNotIn("learning", packet)
            self.assertEqual(context_packet.dumps({k: v for k, v in packet.items() if k != "reuse"}), context_packet.dumps({k: v for k, v in baseline.items() if k != "reuse"}))
        self.assertFalse(learning.store_exists(self.fx.directory))
        # A recorded experience event alone changes nothing either: learning stores are created only by explicit mutations.
        self.fx.record_events(2)
        self.assertNotIn("learning", self.fx.packet())
        self.assertFalse(learning.store_exists(self.fx.directory))

    def test_settings_locations_and_values_are_validated(self):
        inside = self.fx.project / "procedural-learning.json"
        inside.write_text(json.dumps({"enabled": True}))
        with self.assertRaisesRegex(learning.LearningError, "outside the inspected project"):
            learning.load_settings(inside, project=self.fx.project)
        with mock.patch.dict(os.environ, {"AGENT_DISPATCHER_LEARNING_CONFIG": str(inside)}):
            with self.assertRaisesRegex(learning.LearningError, "outside"):
                learning.load_settings(project=self.fx.project)
            self.assertNotIn("learning", self.fx.packet())  # The runtime declines rather than obeying a project file.
        for bad in ({"mode": "canary"}, {"approval": {"policy": "automatic"}}, {"kinds": ["magic"]}, {"budget": {"max_added_share": 0.9}},
                    {"evaluation": {"practical_threshold": 0}}, {"profile": "Bad Name"}, {"enabled": "yes"}):
            with self.subTest(bad=bad):
                self.fx.settings_path.parent.mkdir(parents=True, exist_ok=True)
                self.fx.settings_path.write_text(json.dumps(dict({"enabled": True}, **bad)))
                with self.assertRaises(learning.LearningError):
                    learning.load_settings(project=self.fx.project)
        self.fx.settings_path.write_text("[]")
        with self.assertRaises(learning.LearningError):
            learning.load_settings(project=self.fx.project)
        with self.assertRaises(learning.LearningError):
            learning.write_settings(None, {"enabled": True}, project=self.fx.project)  # configure never silently discards a broken file
        self.fx.settings_path.write_text("{}")
        written = learning.write_settings(None, {"enabled": True, "mode": "shadow"}, project=self.fx.project)
        self.assertEqual((written["enabled"], written["mode"]), (True, "shadow"))
        self.assertEqual(oct(self.fx.settings_path.stat().st_mode & 0o777), "0o600")


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.fx = LearningFixture(self)
        self.fx.enable()

    def test_observations_are_validated_idempotent_and_family_deduplicated(self):
        ids = self.fx.record_events(3, outcome="exit_code_only")
        store = self.fx.store()
        self.addCleanup(store.close)
        with self.fx.experience() as es:
            with self.assertRaisesRegex(learning.LearningError, "has not recorded"):
                learning.observe(store, es, {"schema_version": 1, "event_id": "f" * 64})
            with self.assertRaisesRegex(learning.LearningError, "unknown field"):
                learning.observe(store, es, {"schema_version": 1, "event_id": ids[0], "approved": True})
            with self.assertRaisesRegex(learning.LearningError, "unknown is null"):
                learning.observe(store, es, {"schema_version": 1, "event_id": ids[0], "resources": {"tokens": {"value": 0, "provenance": "unavailable"}}})
            first = learning.observe(store, es, {"schema_version": 1, "event_id": ids[0], "task_family": "fam-a", "user_accepted": True,
                                                 "resources": {"tokens": {"value": None, "provenance": "unavailable"}}})
            again = learning.observe(store, es, {"schema_version": 1, "event_id": ids[0], "task_family": "fam-a"})
            self.assertTrue(first["stored"])
            self.assertFalse(again["stored"])
            stored = store.observation(ids[0])
            self.assertEqual(stored["outcome"], "exit_code_only")  # user acceptance is kept apart from the checked outcome
            self.assertTrue(stored["user_accepted"])
            self.assertEqual(stored["resources"]["tokens"], {"value": None, "provenance": "unavailable"})
            self.assertEqual(stored["exposure"], [])
            # Paraphrases and retries collapse into one family for support counts.
            learning.observe(store, es, {"schema_version": 1, "event_id": ids[1], "task_family": "fam-a"})
            learning.observe(store, es, {"schema_version": 1, "event_id": ids[2]})  # derived family from the request's terms
            review = learning.review_experience(store, es, self.fx.settings, learning.package_catalog(PACK))
            self.assertEqual(review["filtered"]["events"], 3)
            self.assertEqual(review["filtered"]["families"], 2)
            self.assertEqual(review["cost"], {"model_calls": 0})
            weak = next(h for h in review["hypotheses"] if h["pattern"] == "weak_verification_evidence")
            self.assertEqual(weak["support_families"], 2)
            self.assertEqual(weak["kind"], "verification_hint")
            self.assertTrue(set(weak["payload"]["order_first"]) <= learning.package_catalog(PACK)["checks"])
        due = learning.review_due(store, self.fx.settings)
        self.assertEqual((due["observations"], due["due"]), (3, True))


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fx = LearningFixture(self)
        self.fx.enable()
        self.events = self.fx.record_events(3)
        self.store = self.fx.store()
        self.addCleanup(self.store.close)

    def test_every_kind_shares_the_lifecycle_and_invalid_combinations_are_rejected(self):
        documents = {
            "skill_overlay": self.fx.skill_document(self.events),
            "role_method_overlay": {**self.fx.skill_document(self.events), "kind": "role_method_overlay", "target": {"artifact_id": "debugger", "slot": "method_advice"},
                                    "payload": {"slot": "method_advice", "text": "Check the token clock skew before blaming the caller."}},
            "recipe_overlay": {**self.fx.skill_document(self.events), "kind": "recipe_overlay", "operation": "refine", "target": {"artifact_id": "debug-application", "slot": "workflow"},
                               "payload": {"slot": "workflow", "insert": [{"id": "history-expansion", "after": "gather-evidence", "text": "Expand evidence with eligible commit history for the failing files.",
                                                                            "condition": "history is available", "fallback": "continue with source retrieval"}]},
                               "applicability": {"recipes": ["debug-application"], "roles": ["debugger"]}},
            "retrieval_profile": {**self.fx.skill_document(self.events), "kind": "retrieval_profile", "operation": "create", "target": {"artifact_id": "retrieval"},
                                  "payload": {"strategy": "full+deep", "overrides": {"rrf_weights": {"git": 1.0}, "graph": {"max_hops": 1}}}},
            "verification_hint": {**self.fx.skill_document(self.events), "kind": "verification_hint", "operation": "create", "target": {"artifact_id": "verification"},
                                  "payload": {"order_first": ["api-contract-verification"], "note": "Run the scoped regression test before reporting."}},
        }
        for kind, document in documents.items():
            with self.subTest(kind=kind):
                result = self.fx.propose(self.store, document)
                self.assertEqual((result["kind"], result["state"]), (kind, "validated"))
                self.assertEqual(self.store.history(result["revision_id"])[0]["state"], "proposed")
                report = le.component_checks(self.store, result["revision_id"], self.fx.settings, pack=PACK)
                self.assertEqual(report["status"], "passed", [c for c in report["checks"] if not c["passed"]])
                self.assertFalse(report["evaluator"]["authoritative"])
        invalid = [
            ("recipe without sidecar", {**documents["recipe_overlay"], "target": {"artifact_id": "ship-feature", "slot": "workflow"}, "applicability": {"recipes": ["ship-feature"]}}, "workflow sidecar"),
            ("provider strategy", {**documents["retrieval_profile"], "payload": {"strategy": "full+rerank"}}, "approved deterministic strategy"),
            ("out-of-range weight", {**documents["retrieval_profile"], "payload": {"overrides": {"rrf_weights": {"git": 4.0}}}}, "trusted range"),
            ("provider parameter", {**documents["retrieval_profile"], "payload": {"overrides": {"llm_rerank": {"enabled": True}}}}, "not allowlisted"),
            ("unregistered check", {**documents["verification_hint"], "payload": {"order_first": ["run-my-script"]}}, "registered verification"),
            ("check with a command", {**documents["verification_hint"], "payload": {"add_checks": [{"check": "api-contract-verification", "command": "pytest"}]}}, "unknown field"),
            ("protected role slot", {**documents["role_method_overlay"], "target": {"artifact_id": "debugger", "slot": "deliverable"}, "payload": {"slot": "deliverable", "text": "x"}}, "evolvable"),
            ("missing applicability", {k: v for k, v in documents["skill_overlay"].items() if k != "applicability"}, "Applicability is required"),
            ("everything applicability", {**documents["skill_overlay"], "applicability": {}}, "not narrow"),
            ("unknown kind", {**documents["skill_overlay"], "kind": "tool_grant"}, "Unknown artifact kind"),
            ("removed step", {**documents["recipe_overlay"], "payload": {"slot": "workflow", "insert": [], "remove": ["reproduce"]}}, "unknown field"),
            ("insert after a gate", {**documents["recipe_overlay"], "payload": {"slot": "workflow", "insert": [{"id": "x", "after": "regression-test", "text": "extra"}]}}, "not evolvable"),
            ("too many steps", {**documents["recipe_overlay"], "payload": {"slot": "workflow", "insert": [{"id": f"s{n}", "after": "reproduce", "text": "extra"} for n in range(5)]}}, "between 1 and 4"),
        ]
        for label, document, message in invalid:
            with self.subTest(label=label), self.assertRaisesRegex(learning.LearningError, message):
                self.fx.propose(self.store, document)
        disabled = self.fx.enable(kinds=["skill_overlay"])
        with self.assertRaisesRegex(learning.LearningError, "not enabled"):
            self.fx.propose(self.store, documents["verification_hint"])
        self.assertEqual(disabled["kinds"], ["skill_overlay"])

    def test_overlay_applies_only_in_its_namespace_and_applicability_domain(self):
        revision, promoted = self.fx.admit(self.store, self.fx.skill_document(self.events))
        self.assertEqual(self.store.revision(revision)["state"], "active")
        packet = self.fx.packet()
        guide = packet["guidance"]["guides"][0]
        self.assertEqual(guide["source"], "derived")
        self.assertEqual(guide["base_sha256"], base_guide("systematic-debugging")["sha256"])
        self.assertEqual(lc._strip_derived(guide["content"]), base_guide("systematic-debugging")["content"])
        self.assertEqual(packet["learning"]["status"], "active")
        self.assertEqual(packet["learning"]["exposure"]["revisions"], [{"revision_id": revision, "state": "emitted"}])
        self.assertLessEqual(packet["learning"]["added_tokens"], packet["learning"]["budget"]["added_token_limit"])
        self.assertEqual(packet["budget"]["estimated_tokens"], -(-len(context_packet.dumps(packet)) // 4))
        # Other role, other task, other guide: pristine.
        self.assertNotIn("learning", self.fx.packet(role="implementer", guides=("regression-testing",)))
        self.assertNotIn("learning", self.fx.packet(task="Write the release notes for the billing changes", role="documentation-writer", guides=()))
        unselected = self.fx.packet(guides=("regression-testing",))
        self.assertEqual(unselected["guidance"]["guides"][0].get("source"), None)
        self.assertEqual(unselected["learning"]["overlays"][0]["state"], "not_applicable")
        # A second clone is another namespace: nothing crosses.
        clone = self.fx.make_project("clone")
        self.assertNotIn("learning", self.fx.packet(project=clone))
        self.assertFalse(learning.store_exists(repo_store.state_directory(clone)))
        # Non-compact inspection output carries the explanation but never bodies.
        plain = context.select_context(self.fx.project, TASK, role="debugger", pack=ROOT)
        self.assertEqual(plain["learning"]["overlays"][0]["state"], "active")
        self.assertNotIn("guidance", plain)

    def test_layers_compose_in_order_and_fail_closed_on_incompatibility(self):
        profile_dir = learning.profile_directory("tests")
        profile = learning.LearningStore(profile_dir, create=True, readonly=False, namespace_kind="test")
        self.addCleanup(profile.close)
        with profile.transaction():
            profile.set_meta("pack", str(PACK))
        self.fx.enable(profile="tests")
        general = {**self.fx.skill_document([], text="Reproduce with an empty and an expired token before reading callers.", roles=("debugger",), terms=("token",)),
                   "scope": "global", "operation": "generalize", "privacy_classification": "sanitized_general", "created_by_kind": "human"}
        global_revision = learning.propose_candidate(profile, None, general, self.fx.settings, pack=PACK, namespace="profile:tests", scope="global")["revision_id"]
        le.component_checks(profile, global_revision, self.fx.settings, pack=PACK)
        with self.fx.experience() as es:
            report = le.evaluate_candidate(profile, es, global_revision, {"schema_version": 1, "objective": "correctness", "runner": "fake_test_runner", "environment": dict(ENVIRONMENT)},
                                           self.fx.settings, pack=PACK, runner="fake_test_runner",
                                           fixture_results={"pairs": [{"family": f"g{n}", "block": n % 2, "candidate": True, "incumbent": n % 3 == 0} for n in range(8)]})
            learning.approve_candidate(profile, es, global_revision, report["evaluation_id"], None, {"kind": "human", "actor": "tester"}, self.fx.settings, pack=PACK)
            learning.promote_candidate(profile, es, global_revision, None, self.fx.settings, pack=PACK)
        packet = self.fx.packet(task="Fix the token bug")
        self.assertEqual([layer["scope"] for layer in packet["guidance"]["guides"][0]["layers"]], ["global"])
        # A repository specialization evaluated against that global revision composes after it.
        specialization = self.fx.skill_document(self.events, text="Here the token branch lives in auth/tokens.py; check the boolean short-circuit first.", parent_revision_ids=[global_revision])
        specialization["parent_revision_ids"] = []  # parents are namespace-local; record the binding through dependencies of the same store instead
        repo_revision, _ = self.fx.admit(self.store, specialization)
        packet = self.fx.packet(task="Fix the regression in validate_token")
        self.assertEqual([layer["scope"] for layer in packet["guidance"]["guides"][0]["layers"]], ["global", "repo"])
        self.assertLess(packet["guidance"]["guides"][0]["content"].index("Reproduce with an empty"), packet["guidance"]["guides"][0]["content"].index("Here the token branch"))
        # Same slot, same scope, second admitted revision: promotion refuses unless it names the first as its parent.
        rival = self.fx.propose(self.store, self.fx.skill_document(self.events, text="A rival wording for the same slot."))
        le.component_checks(self.store, rival["revision_id"], self.fx.settings, pack=PACK)
        evaluation = self.fx.evaluate(self.store, rival["revision_id"])
        active = self.store.active_generation()["generation_id"]
        self.fx.approve(self.store, rival["revision_id"], evaluation["evaluation_id"], expected=active)
        with self.assertRaisesRegex(learning.LearningError, "same slot"):
            self.fx.promote(self.store, rival["revision_id"], expected=active)
        refinement = self.fx.skill_document(self.events, text="A refined wording that supersedes the first.", operation="refine", parent_revision_ids=[repo_revision])
        refined, promoted = self.fx.admit(self.store, refinement)
        self.assertEqual(promoted["superseded"], [repo_revision])
        self.assertEqual(self.store.revision(repo_revision)["state"], "deprecated")
        # Forcing two live revisions into one generation (a corrupt or hand-edited generation) is a runtime conflict: base used.
        with self.store.transaction():
            self.store.transition(repo_revision, "active", "test: forced back")
            record = dict(self.store.active_generation(), revision_ids=sorted([refined, repo_revision]), created=learning._now(), reason="test conflict")
            record["generation_id"] = learning._digest(record)
            self.store.publish_generation(record, self.store.active_generation()["generation_id"])
        packet = self.fx.packet(task="Fix the regression in validate_token")
        states = {row["revision_id"]: row["state"] for row in packet["learning"]["overlays"]}
        self.assertEqual((states[refined], states[repo_revision]), ("conflict", "conflict"))
        self.assertEqual([layer["scope"] for layer in packet["guidance"]["guides"][0]["layers"]], ["global"])  # the global layer still composes alone

    def test_protected_contracts_hold_under_composition(self):
        catalog = learning.package_catalog(PACK)
        role = learning.base_body(PACK, "role_method_overlay", "debugger")
        composed = lc.compose("role_method_overlay", role["content"], [{"revision_id": "a" * 64, "scope": "repo", "slot": "method_advice", "text": "Check clock skew first."}])
        self.assertEqual(composed["state"], "active")
        for name in lc.PROTECTED_ROLE_SECTIONS:
            self.assertEqual(lc._protected(role["content"], name), lc._protected(composed["content"], name), name)
        self.assertEqual(lc._strip_derived(composed["content"]), role["content"])
        workflow = catalog["workflows"]["debug-application"]
        inserted = lc.compose_workflow(workflow, [{"id": "history", "after": "gather-evidence", "text": "expand", "condition": None, "capability": None, "fallback": None}])
        self.assertEqual([s["id"] for s in inserted["steps"] if not s["derived"]], [s["id"] for s in workflow["steps"]])
        self.assertEqual(inserted["gates"], workflow["gates"])
        self.assertEqual(inserted["steps"][2]["requires"], ["gather-evidence"])
        for bad in ({"id": "x", "after": "fix", "text": "t", "condition": None, "capability": None, "fallback": None},
                    {"id": "reproduce", "after": "reproduce", "text": "t", "condition": None, "capability": None, "fallback": None}):
            with self.assertRaises(lc.LearningValidationError):
                lc.validate_recipe_insertions(workflow, [bad])
        with self.assertRaises(lc.LearningValidationError):
            lc.validate_workflow({**workflow, "steps": workflow["steps"][:1]})
        cyclic = json.loads(json.dumps(workflow))
        cyclic["steps"][0]["requires"] = ["fix"]
        with self.assertRaisesRegex(lc.LearningValidationError, "no cycles"):
            lc.validate_workflow(cyclic)
        # Retrieval profiles: the effective profile keeps caller caps and never touches provider settings or benchmark switches.
        profile = {"typed_payload": {"strategy": "full+deep", "overrides": {"rrf_weights": {"git": 1.5}, "context": {"max_files": 50, "radius": 8},
                                                                            "names": {"case_only": "resolved"}, "oversized": {"lexical": False}}}, "revision_id": "b" * 64}
        effective, state = lc.effective_profile([profile], {}, caller_strategy_explicit=False)
        self.assertEqual(effective["overrides"], {"rrf_weights": {"git": 1.5}, "context": {"radius": 8}})
        explicit, _ = lc.effective_profile([profile], {}, caller_strategy_explicit=True)
        self.assertIsNone(explicit["strategy"])
        _, conflict = lc.effective_profile([profile, dict(profile, revision_id="c" * 64)], {})
        self.assertEqual(conflict["state"], "conflict")
        # Provider-assisted proposals stay off without explicit enablement and never fall back.
        with self.assertRaisesRegex(learning.LearningError, "off"):
            learning.propose_with_provider({}, self.fx.settings, scrub=self.fx.scrub)

    def test_revision_identity_binds_material_fields_and_stale_approvals_fail(self):
        base = self.fx.skill_document(self.events)
        first = self.fx.propose(self.store, base)["revision_id"]
        changed_payload = self.fx.propose(self.store, self.fx.skill_document(self.events, text="Different wording."))["revision_id"]
        changed_terms = self.fx.propose(self.store, self.fx.skill_document(self.events, terms=("token",)))["revision_id"]
        self.assertEqual(len({first, changed_payload, changed_terms}), 3)
        self.assertEqual(self.fx.propose(self.store, base)["revision_id"], first)  # identical material is the same revision, once
        self.assertEqual(len(self.store.revisions()), 3)
        # Approvals bind the incumbent generation: promoting another candidate first makes the approval stale.
        for revision in (first, changed_payload):
            le.component_checks(self.store, revision, self.fx.settings, pack=PACK)
        report_first = self.fx.evaluate(self.store, first)
        report_second = self.fx.evaluate(self.store, changed_payload)
        self.fx.approve(self.store, first, report_first["evaluation_id"], expected=None)
        self.fx.approve(self.store, changed_payload, report_second["evaluation_id"], expected=None)
        promoted = self.fx.promote(self.store, changed_payload, expected=None)
        with self.assertRaisesRegex(learning.LearningError, "Stale approval"):
            self.fx.promote(self.store, first, expected=promoted["generation_id"])
        with self.assertRaisesRegex(learning.LearningError, "Stale approval"):
            self.fx.promote(self.store, first, expected=None)
        # An evaluation belongs to one candidate and one policy.
        self.fx.enable(review={"min_support_families": 2, "due_after_observations": 2})
        le.component_checks(self.store, changed_terms, self.fx.settings, pack=PACK)
        report_third = self.fx.evaluate(self.store, changed_terms)
        with self.assertRaisesRegex(learning.LearningError, "does not belong"):
            self.fx.approve(self.store, changed_terms, report_first["evaluation_id"], expected=promoted["generation_id"])
        self.fx.enable()
        with self.assertRaisesRegex(learning.LearningError, "policy changed"):
            self.fx.approve(self.store, changed_terms, report_third["evaluation_id"], expected=promoted["generation_id"])

    def test_concurrent_promotion_interruption_and_rollback(self):
        first = self.fx.propose(self.store, self.fx.skill_document(self.events))["revision_id"]
        second = self.fx.propose(self.store, self.fx.skill_document(self.events, text="Second, competing candidate.", slot="failure_branch"))["revision_id"]
        reports = {}
        for revision in (first, second):
            le.component_checks(self.store, revision, self.fx.settings, pack=PACK)
            reports[revision] = self.fx.evaluate(self.store, revision)
            self.fx.approve(self.store, revision, reports[revision]["evaluation_id"], expected=None)
        other = learning.open_store(self.fx.directory, readonly=False)
        self.addCleanup(other.close)
        generation = self.fx.promote(self.store, first, expected=None)["generation_id"]
        # The second approval expected an empty generation: another connection's promotion made it stale, visibly.
        with self.fx.experience() as es:
            with self.assertRaisesRegex(learning.LearningError, "Stale approval"):
                learning.promote_candidate(other, es, second, None, self.fx.settings, pack=PACK)
            with self.assertRaisesRegex(learning.LearningError, "Stale approval"):
                learning.promote_candidate(other, es, second, generation, self.fx.settings, pack=PACK)
        # Re-approval against the current generation needs a fresh evaluation of the composed bundle.
        with self.fx.experience() as es:
            with self.assertRaisesRegex(learning.LearningError, "different incumbent|Candidate is approved"):
                learning.approve_candidate(self.store, es, second, reports[second]["evaluation_id"], generation, {"kind": "human", "actor": "tester"}, self.fx.settings, pack=PACK)
        with self.store.transaction():
            self.store.transition(second, "rejected", "test: withdraw the stale approval path")
        second = self.fx.propose(self.store, self.fx.skill_document(self.events, text="Second candidate, re-proposed.", slot="failure_branch"))["revision_id"]
        le.component_checks(self.store, second, self.fx.settings, pack=PACK)
        report = self.fx.evaluate(self.store, second)
        self.fx.approve(self.store, second, report["evaluation_id"], expected=generation)
        # Interruption inside publication rolls the whole transaction back: no half-published generation, approval unconsumed.
        with self.fx.experience() as es:
            with mock.patch.object(learning.LearningStore, "publish_generation", side_effect=RuntimeError("interrupted")):
                with self.assertRaises(RuntimeError):
                    learning.promote_candidate(self.store, es, second, generation, self.fx.settings, pack=PACK)
        self.assertEqual(self.store.active_generation()["generation_id"], generation)
        self.assertEqual(self.store.revision(second)["state"], "approved")
        self.assertEqual(len(self.store.approvals(second, unconsumed=True)), 1)
        later = self.fx.promote(self.store, second, expected=generation)["generation_id"]
        self.assertEqual(sorted(self.store.active_generation()["revision_ids"]), sorted([first, second]))
        # Rollback restores the complete earlier generation atomically and refuses a target with a revoked member.
        with self.fx.experience() as es:
            restored = learning.rollback_generation(self.store, later, generation, {"kind": "human", "actor": "tester"}, self.fx.settings, pack=PACK)
        self.assertEqual(self.store.active_generation()["revision_ids"], [first])
        self.assertEqual(self.store.revision(second)["state"], "rolled_back")
        self.assertEqual(restored["restored_from"], generation)
        learning.revoke(self.store, first, "unsafe", self.fx.settings)
        with self.assertRaisesRegex(learning.LearningError, "revoked"):
            learning.rollback_generation(self.store, self.store.active_generation()["generation_id"], generation, {"kind": "human", "actor": "tester"}, self.fx.settings, pack=PACK)
        base = learning.rollback_generation(self.store, self.store.active_generation()["generation_id"], None, {"kind": "human", "actor": "tester"}, self.fx.settings, pack=PACK)
        self.assertEqual((base["restored_from"], base["revision_ids"]), ("base", []))
        self.assertNotIn("learning", self.fx.packet())


class EvaluationTests(unittest.TestCase):
    def test_paired_statistics_edge_cases(self):
        empty = le.paired_success([])
        self.assertEqual((empty["n"], empty["difference"]), (0, None))
        same = le.paired_success(le.family_pairs([{"family": f"f{n}", "candidate": True, "incumbent": True} for n in range(10)]))
        self.assertTrue(same["degenerate"])
        self.assertEqual((same["discordant"], same["sign_p"]), (0, None))
        tiny = le.paired_success(le.family_pairs([{"family": "a", "candidate": True, "incumbent": False}, {"family": "b", "candidate": True, "incumbent": False}]))
        self.assertTrue(tiny["degenerate"])
        repeated = le.family_pairs([{"family": "a", "candidate": True, "incumbent": False}, {"family": "a", "candidate": False, "incumbent": False}])
        self.assertEqual((len(repeated), repeated[0]["repetitions"], repeated[0]["candidate_rate"]), (1, 2, 0.5))
        clear = le.paired_success(le.family_pairs([{"family": f"f{n}", "candidate": True, "incumbent": n % 4 == 0} for n in range(40)]))
        self.assertGreater(clear["low"], 0.5)
        self.assertLess(clear["sign_p"], 0.001)
        self.assertEqual(clear["method"].split(";")[0], "family-level paired bootstrap of success-rate difference")
        worse = le.paired_success(le.family_pairs([{"family": f"f{n}", "candidate": n % 4 == 0, "incumbent": True} for n in range(40)]))
        self.assertLess(worse["high"], 0)
        cost = le.paired_delta([1.0, None, 2.0, float("nan")])
        self.assertEqual((cost["n"], cost["missing"]), (2, 2))
        self.assertIsNone(le.paired_delta([])["mean"])
        blocks = le.block_bootstrap(le.family_pairs([{"family": f"f{n}", "block": n % 3, "candidate": True, "incumbent": False} for n in range(9)]))
        self.assertEqual(blocks["blocks"], 3)
        self.assertEqual(le.retrieval_metrics(["a", "b"], [], 5)["defined"], False)
        self.assertEqual(le.retrieval_metrics(["a", "b"], None, 5)["reason"], "gold targets unavailable")
        self.assertEqual(le.retrieval_metrics(["a", "b", "c"], ["a", "c", "d"], 3), {"recall": 2 / 3, "hit": 1.0, "all": 0.0, "defined": True})
        self.assertAlmostEqual(le.z_value(0.95), 1.959964, places=4)

    def test_evaluation_statuses_are_gated_by_coverage_intervals_and_validity(self):
        fx = LearningFixture(self)
        fx.enable()
        events = fx.record_events(3)
        store = fx.store()
        self.addCleanup(store.close)
        revision = fx.propose(store, fx.skill_document(events))["revision_id"]
        pairs = lambda n, good: {"pairs": [{"family": f"f{k}", "block": k % 2, "candidate": good(k), "incumbent": k % 3 == 0} for k in range(n)]}  # noqa: E731
        cases = [
            ("passed", pairs(12, lambda k: True), {}, "passed"),
            ("too few families", pairs(2, lambda k: True), {}, "inconclusive"),
            ("no discordant pairs", {"pairs": [{"family": f"f{k}", "candidate": True, "incumbent": True} for k in range(12)]}, {}, "inconclusive"),
            ("worse", {"pairs": [{"family": f"f{k}", "block": k % 2, "candidate": False, "incumbent": True} for k in range(12)]}, {}, "failed"),
            ("mixed, no clear signal", pairs(12, lambda k: k % 5 == 0), {}, "inconclusive"),
            ("safety violation", dict(pairs(12, lambda k: True), safety_violations=1), {}, "failed"),
            ("infrastructure share", dict(pairs(12, lambda k: True), attempts=24, infrastructure_errors=10), {}, "invalid"),
            ("no outcomes", {"pairs": []}, {}, "not_run"),
            ("efficiency without cost", pairs(12, lambda k: True), {"objective": "efficiency", "noninferiority_margin": 0.1}, "inconclusive"),
            ("efficiency passes", {"pairs": [dict(p, candidate_cost=0.5 + 0.01 * n, incumbent_cost=1.0) for n, p in enumerate(pairs(12, lambda k: True)["pairs"])]},
             {"objective": "efficiency", "noninferiority_margin": 0.1}, "passed"),
            ("cheaper but worse", {"pairs": [dict(p, candidate_cost=0.4, incumbent_cost=1.0) for p in pairs(12, lambda k: k % 4 == 0)["pairs"]]},
             {"objective": "efficiency", "noninferiority_margin": 0.05}, "failed"),
        ]
        for label, fixture, extra, expected in cases:
            with self.subTest(label=label):
                report = fx.evaluate(store, revision, pairs=fixture, spec_extra=extra, objective=extra.get("objective", "correctness"))
                self.assertEqual(report["status"], expected, report["reasons"])
                self.assertFalse(report["evaluator"]["authoritative"])
                self.assertEqual(report["candidate_revision_id"], revision)
                self.assertIn("margin", " ".join(report["reasons"]) if extra.get("objective") == "efficiency" and expected != "inconclusive" else "margin")
        with self.assertRaisesRegex(EVAL_ERRORS, "noninferiority_margin"):
            fx.evaluate(store, revision, objective="efficiency")
        with self.assertRaisesRegex(EVAL_ERRORS, "unregistered runner"):
            with fx.experience() as es:
                le.evaluate_candidate(store, es, revision, {"schema_version": 1, "runner": "my_runner", "environment": dict(ENVIRONMENT)}, fx.settings, pack=PACK)
        contaminated = fx.evaluate(store, revision, pairs=pairs(12, lambda k: True), spec_extra={"data": {"final_test": {"families": ["fam-x"]}}, "min_paired_families": 4})
        self.assertEqual(contaminated["status"], "passed")  # no overlap declared
        with store.transaction():
            store.connection.execute("UPDATE revisions SET record=json_set(record, '$.task_families', json('[\"fam-x\"]')) WHERE revision_id=?", (revision,))
        self.assertFalse(lc.revision_digest_matches(store.revision(revision)))  # the tamper is visible
        # Every evaluated candidate stays on record, failures included.
        self.assertGreaterEqual(len([e for e in store.evaluations(revision) if e["status"] == "failed"]), 2)
        self.assertGreaterEqual(len([e for e in store.evaluations(revision) if e["status"] == "invalid"]), 1)

    def test_authoritative_batch_runner_pairs_completed_trials_and_binds_the_batch(self):
        fx = LearningFixture(self)
        fx.enable()
        events = fx.record_events(3)
        store = fx.store(namespace_kind="production")
        self.addCleanup(store.close)
        revision = fx.propose(store, fx.skill_document(events))["revision_id"]
        batch = fx.root / "batch"
        batch.mkdir()
        trials = []
        for n in range(8):
            for condition, success in (("warm_experience", n % 3 == 0), ("learned_skills", True)):
                trials.append({"id": f"claude-fix-{n}-{condition}", "client": "claude", "condition": condition, "fixture_id": f"fix-{n}", "repetition": 1,
                               "status": "completed", "task_success": success, "category": "bug", "usage": {"cost_usd": 1.0 if condition == "warm_experience" else 0.8}})
        trials.append({"id": "bad", "client": "claude", "condition": "learned_skills", "fixture_id": "fix-9", "repetition": 1, "status": "infrastructure_error"})
        (batch / "batch.json").write_text(json.dumps({"suite": "pilot", "seed": 1, "provenance": {"config_fingerprint": "abc"}}))
        (batch / "results.json").write_text(json.dumps({"trials": trials}))
        spec = {"schema_version": 1, "objective": "correctness", "runner": "end_to_end_batch", "min_paired_families": 6, "min_blocks": 1,
                "environment": dict(ENVIRONMENT, batch_fingerprint="abc"), "arms": {"candidate": "learned_skills", "incumbent": "warm_experience"}}
        with fx.experience() as es:
            report = le.evaluate_candidate(store, es, revision, spec, fx.settings, pack=PACK, batch=str(batch))
        self.assertEqual(report["status"], "passed", report["reasons"])
        self.assertTrue(report["evaluator"]["authoritative"])
        self.assertEqual(report["families"], 8)
        self.assertEqual(report["outcomes"]["infrastructure_errors"], 1)
        # Only the authoritative, passed report can be approved in a production namespace.
        approval = fx.approve(store, revision, report["evaluation_id"], expected=None)
        self.assertEqual(approval["rollout"], "active")
        other = fx.propose(store, fx.skill_document(events, text="Another candidate for the unrun cases."))["revision_id"]
        with fx.experience() as es:
            with self.assertRaisesRegex(EVAL_ERRORS, "fingerprint"):
                le.evaluate_candidate(store, es, other, dict(spec, environment=dict(ENVIRONMENT, batch_fingerprint="other")), fx.settings, pack=PACK, batch=str(batch))
            self.assertEqual(store.revision(other)["state"], "inconclusive")  # unusable runner input never invalidates the candidate itself
            not_run = le.evaluate_candidate(store, es, other, spec, fx.settings, pack=PACK)
        self.assertEqual(not_run["status"], "not_run")
        with self.assertRaisesRegex(learning.LearningError, "inconclusive"):
            fx.approve(store, other, not_run["evaluation_id"], expected=None)


class InvalidationTests(unittest.TestCase):
    def setUp(self):
        self.fx = LearningFixture(self)
        self.fx.enable()
        self.events = self.fx.record_events(3)
        self.store = self.fx.store()
        self.addCleanup(self.store.close)

    def test_corrections_forgetting_and_unenrollment_propagate(self):
        revision, promoted = self.fx.admit(self.store, self.fx.skill_document(self.events))
        key_before = self.fx.packet()["learning"]["reuse_key"]
        # A record-level correction supersedes the event: the runtime withholds the overlay before any maintenance runs.
        with self.fx.experience(readonly=False) as es:
            experience.recorrect(es, self.events[0], "reverted_or_invalidated", "the fix was reverted", self.fx.scrub)
        packet = self.fx.packet()
        self.assertEqual(packet["learning"]["overlays"][0]["state"], "insufficient_evidence")
        self.assertIsNone(packet["guidance"]["guides"][0].get("source"))
        self.assertNotEqual(packet["learning"]["reuse_key"], key_before)
        with self.fx.experience() as es:
            synced = learning.sync_support(self.store, es, self.fx.settings)
        self.assertEqual(synced, {"changed": [], "suspended": []})  # two families remain, above the configured minimum of one
        with self.fx.experience(readonly=False) as es:
            for ident in self.events[1:]:
                experience.forget(es, event_id=ident)
        with self.fx.experience() as es:
            synced = learning.sync_support(self.store, es, self.fx.settings)
        self.assertEqual(synced["suspended"], [revision])
        self.assertEqual(self.store.revision(revision)["state"], "stale_support")
        self.assertEqual(self.store.active_generation()["revision_ids"], [])
        self.assertNotIn("learning", self.fx.packet())
        # Forgetting an observation keeps only a non-content tombstone.
        with self.fx.experience() as es:
            learning.observe(self.store, es, {"schema_version": 1, "event_id": self.events[0], "task_family": "fam", "notes": "private detail"})
            result = learning.forget(self.store, es, self.fx.settings, event_id=self.events[0])
        self.assertEqual(result["observations_removed"], 1)
        self.assertIsNone(self.store.observation(self.events[0]))
        tombstones = self.store.tombstones()
        self.assertEqual(tombstones[-1]["kind"], "observation")
        self.assertNotIn("private detail", json.dumps(tombstones))
        # Unenrollment suspends global revisions that rested on the repository's evidence.
        profile = learning.LearningStore(learning.profile_directory("tests"), create=True, readonly=False, namespace_kind="test")
        self.addCleanup(profile.close)
        with profile.transaction():
            profile.set_meta("pack", str(PACK))
        learning.enroll(profile, self.store, self.fx.directory.name, consent_aggregate=True)
        general = {**self.fx.skill_document([], text="Reproduce with an empty token first.", terms=("token",)), "scope": "global", "operation": "generalize",
                   "privacy_classification": "sanitized_general", "created_by_kind": "human"}
        proposed = learning.propose_candidate(profile, None, general, self.fx.settings, pack=PACK, namespace="profile:tests", scope="global",
                                              provenance={"namespaces": [self.fx.directory.name]})
        with profile.transaction():
            profile.transition(proposed["revision_id"], "evaluating", "test")
            profile.transition(proposed["revision_id"], "evaluation_passed", "test")
            profile.transition(proposed["revision_id"], "awaiting_approval", "test")
            profile.transition(proposed["revision_id"], "approved", "test")
            profile.transition(proposed["revision_id"], "active", "test")
        learning._new_generation(profile, [proposed["revision_id"]], None, self.fx.settings, "test", pack_digest=learning.package_digest(PACK))
        result = learning.unenroll(profile, self.fx.directory.name, self.fx.settings)
        self.assertEqual(result["suspended"], [proposed["revision_id"]])
        self.assertEqual(profile.active_generation()["revision_ids"], [])
        self.assertEqual(profile.enrollments(), [])

    def test_revocation_takes_descendants_and_deprecation_keeps_history(self):
        parent, _ = self.fx.admit(self.store, self.fx.skill_document(self.events))
        child = self.fx.propose(self.store, self.fx.skill_document(self.events, text="A refinement.", operation="refine", parent_revision_ids=[parent]))["revision_id"]
        result = learning.revoke(self.store, parent, "unsafe wording", self.fx.settings)
        self.assertEqual(set(result["affected"]), {parent, child})
        self.assertEqual({self.store.revision(i)["state"] for i in (parent, child)}, {"revoked"})
        self.assertEqual(self.store.active_generation()["revision_ids"], [])
        with self.assertRaisesRegex(learning.LearningError, "revoked"):
            self.fx.propose(self.store, self.fx.skill_document(self.events, text="Grandchild.", operation="refine", parent_revision_ids=[child]))
        again, _ = self.fx.admit(self.store, self.fx.skill_document(self.events, text="Another wording entirely."))
        deprecated = learning.deprecate(self.store, again, "obsolete", self.fx.settings)
        self.assertEqual(self.store.revision(again)["state"], "deprecated")
        self.assertTrue(self.store.history(again))
        pruned = learning.prune(self.store, self.fx.settings, max_age_days=0, now=learning._now() + 10)
        self.assertTrue(pruned["dry_run"])
        self.assertEqual({c["revision_id"] for c in pruned["candidates"]}, {parent, child, again})
        applied = learning.prune(self.store, self.fx.settings, apply=True, max_age_days=0, now=learning._now() + 10)
        self.assertEqual(set(applied["removed"]), {parent, child, again})
        self.assertIsNone(self.store.revision(again))
        self.assertEqual({t["ident"] for t in self.store.tombstones() if t["kind"] == "revision"}, {parent, child, again})


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.fx = LearningFixture(self)
        self.fx.enable()
        self.events = self.fx.record_events(3)
        self.store = self.fx.store()
        self.addCleanup(self.store.close)

    def test_shadow_emits_nothing_and_canaries_need_authorization_and_bounds(self):
        revision, _ = self.fx.admit(self.store, self.fx.skill_document(self.events), rollout="canary", canary={"max_tasks": 1, "max_days": 1})
        self.assertEqual(self.store.revision(revision)["state"], "canary")
        self.fx.enable("shadow")
        shadow = self.fx.packet()
        self.assertEqual(shadow["learning"]["status"], "shadow")
        self.assertEqual(shadow["learning"]["overlays"][0]["state"], "shadow")
        self.assertIsNone(shadow["guidance"]["guides"][0].get("source"))
        self.assertEqual(shadow["learning"]["exposure"]["revisions"][0]["state"], "eligible")
        self.fx.enable("active")
        first = self.fx.packet()
        self.assertEqual(first["guidance"]["guides"][0]["source"], "derived")
        # The canary's task budget is consumed by explicit observations, never by reads.
        self.assertEqual(self.fx.packet()["guidance"]["guides"][0]["source"], "derived")
        with self.fx.experience() as es:
            learning.observe(self.store, es, {"schema_version": 1, "event_id": self.events[0], "exposure": first["learning"]["exposure"]["revisions"]})
        exhausted = self.fx.packet()
        self.assertEqual(exhausted["learning"]["overlays"][0]["state"], "not_approved")
        self.assertIsNone(exhausted["guidance"]["guides"][0].get("source"))
        with self.assertRaisesRegex(learning.LearningError, "ceilings"):
            self.fx.admit(self.store, self.fx.skill_document(self.events, slot="failure_branch", text="Another."), rollout="canary", canary={"max_tasks": 5000, "max_days": 1})
        # Experimental canaries need Tier B first and an explicit human authorization with an experiment id.
        candidate = self.fx.propose(self.store, self.fx.skill_document(self.events, slot="retrieval_hint", text="Read the token tests first."))["revision_id"]
        with self.assertRaisesRegex(learning.LearningError, "Component checks"):
            learning.start_experimental_canary(self.store, candidate, {"kind": "human", "actor": "tester"}, self.fx.settings, experiment="exp-1")
        le.component_checks(self.store, candidate, self.fx.settings, pack=PACK)
        with self.assertRaises(learning.LearningError):
            learning.start_experimental_canary(self.store, candidate, {"kind": "model", "actor": "assistant"}, self.fx.settings, experiment="exp-1")
        started = learning.start_experimental_canary(self.store, candidate, {"kind": "human", "actor": "tester"}, self.fx.settings, experiment="exp-1", max_tasks=2, max_days=1)
        self.assertEqual(started["state"], "experimental_canary")
        packet = self.fx.packet()
        row = next(r for r in packet["learning"]["overlays"] if r["revision_id"] == candidate)
        self.assertEqual(row["state"], "active")
        _, rows = learning.eligible_revisions(self.store, self.fx.settings, now=learning._now() + 2 * 86400)
        self.assertEqual(next(r for r in rows if r["revision_id"] == candidate)["runtime_state"], "not_approved")
        report = self.fx.evaluate(self.store, candidate)
        self.assertEqual(report["lifecycle_state"], "evaluation_passed")


class PackageAndCliTests(unittest.TestCase):
    def setUp(self):
        self.fx = LearningFixture(self)

    def run_cli(self, helper, *arguments, cwd=None, env=None, stdin=None):
        return subprocess.run([sys.executable, "-B", str(helper), *arguments, "--project", str(self.fx.project), "--json"], cwd=cwd or self.fx.root,
                              capture_output=True, text=True, env=env or dict(os.environ), input=stdin, timeout=120)

    def test_installed_claude_and_codex_packages_resolve_learning_helpers_from_elsewhere(self):
        import build
        import build_codex
        import install_claude
        manual = self.fx.root / "manual"
        install_claude.stage_pack(ROOT, manual)
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            data = build.main()
        codex = build_codex.export_package(self.fx.root / "codex", data)
        self.fx.enable()
        events = self.fx.record_events(3)
        store = self.fx.store()
        self.fx.admit(store, self.fx.skill_document(events))
        store.close()
        elsewhere = self.fx.root / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "learning.py").write_text("raise AssertionError('project code must not be imported')\n")
        for label, helper, pack in (("manual", manual / "learning.py", manual), ("codex", codex / "scripts/learning.py", codex), ("source", ROOT / "learning.py", ROOT)):
            with self.subTest(label=label):
                status = self.run_cli(helper, "status", cwd=elsewhere)
                self.assertEqual(status.returncode, 0, status.stderr)
                self.assertEqual(json.loads(status.stdout)["stores"]["repo"]["active_revisions"], 1)
                explain = self.run_cli(helper, "explain", "--task", TASK, "--role", "debugger", cwd=elsewhere)
                self.assertEqual(explain.returncode, 0, explain.stderr)
                self.assertEqual(json.loads(explain.stdout)["overlays"][0]["state"], "active")
                effective = self.run_cli(helper, "effective", "systematic-debugging", "--kind", "skill_overlay", cwd=elsewhere)
                self.assertEqual(effective.returncode, 0, effective.stderr)
                self.assertIn(lc.DERIVED_MARK, json.loads(effective.stdout)["content"])
                packet = subprocess.run([sys.executable, "-B", str(pack / ("scripts/context.py" if label == "codex" else "context.py")), "--project", str(self.fx.project),
                                         "--task", TASK, "--role", "debugger", "--compact", "--guide", "systematic-debugging", "--json"],
                                        cwd=elsewhere, capture_output=True, text=True, env=dict(os.environ), timeout=120)
                self.assertEqual(packet.returncode, 0, packet.stderr)
                self.assertEqual(json.loads(packet.stdout)["guidance"]["guides"][0]["source"], "derived")
        coordinator = self.run_cli(ROOT / "repository_intelligence.py", "learning", "status", cwd=elsewhere)
        self.assertEqual(coordinator.returncode, 0, coordinator.stderr)
        self.assertIn("stores", json.loads(coordinator.stdout))
        status = subprocess.run([sys.executable, "-B", str(ROOT / "repository_intelligence.py"), "status", "--project", str(self.fx.project), "--json"],
                                capture_output=True, text=True, env=dict(os.environ), timeout=60)
        self.assertEqual(json.loads(status.stdout)["learning"]["store"], "present")

    def test_cli_round_trip_and_read_only_commands_create_nothing(self):
        helper = ROOT / "learning.py"
        configure = self.run_cli(helper, "configure", "--enable", "--mode", "active", "--record-observations", "on")
        self.assertEqual(configure.returncode, 0, configure.stderr)
        self.assertTrue(self.fx.settings_path.is_file())
        self.fx.enable(review={"min_support_families": 1, "due_after_observations": 1})
        events = self.fx.record_events(2, outcome="exit_code_only")
        observation = {"schema_version": 1, "event_id": events[0], "task_family": "fam-a", "workflow": {"retrieval": {"history_expansion": "used"}}}
        observed = self.run_cli(helper, "observe", "--event", events[0], "--observation-file", "-", stdin=json.dumps(observation))
        self.assertEqual(observed.returncode, 0, observed.stderr)
        self.assertTrue(json.loads(observed.stdout)["stored"])
        mismatch = self.run_cli(helper, "observe", "--event", events[1], "--observation-file", "-", stdin=json.dumps(observation))
        self.assertEqual(mismatch.returncode, 2)
        review = self.run_cli(helper, "review", "--packet")
        self.assertEqual(review.returncode, 0, review.stderr)
        packet = json.loads(review.stdout)
        self.assertFalse(packet["stored"])
        self.assertIn("instructions", packet["packet"])
        self.assertNotIn(TASK, review.stdout)  # the review packet carries ids and counts, never task prose
        applied = self.run_cli(helper, "review", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        candidates = json.loads(applied.stdout)["candidates"]
        self.assertTrue(any(c.get("state") == "validated" for c in candidates), candidates)
        proposed = self.run_cli(helper, "propose", "--from-file", "-", stdin=json.dumps(self.fx.skill_document(events)))
        self.assertEqual(proposed.returncode, 0, proposed.stderr)
        revision = json.loads(proposed.stdout)["revision_id"]
        rejected = self.run_cli(helper, "propose", "--from-file", "-", stdin=json.dumps(dict(self.fx.skill_document(events), approved=True)))
        self.assertEqual(rejected.returncode, 2)
        self.assertNotIn("validate_token", rejected.stderr)
        checks = self.run_cli(helper, "component-check", revision)
        self.assertEqual(json.loads(checks.stdout)["status"], "passed", checks.stderr)
        spec = self.fx.root / "spec.json"
        spec.write_text(json.dumps({"schema_version": 1, "objective": "correctness", "runner": "fake_test_runner", "environment": ENVIRONMENT}))
        results = self.fx.root / "pairs.json"
        results.write_text(json.dumps({"pairs": [{"family": f"f{n}", "block": n % 2, "candidate": True, "incumbent": n % 3 == 0} for n in range(8)]}))
        evaluated = self.run_cli(helper, "evaluate", revision, "--spec", str(spec), "--fixture-results", str(results))
        self.assertEqual(evaluated.returncode, 0, evaluated.stderr)
        report = json.loads(evaluated.stdout)
        self.assertEqual(report["status"], "passed")
        approve = self.run_cli(helper, "approve", revision, "--evaluation", report["evaluation_id"], "--authorize-as", "tester")
        self.assertEqual(approve.returncode, 2)  # production namespace: a test-only report is never enough
        self.assertIn("non-authoritative", approve.stderr)
        for command in (("list",), ("show", revision), ("diff", revision), ("history", revision), ("evaluations", revision), ("effective", "systematic-debugging", "--kind", "skill_overlay"),
                        ("explain", "--task", TASK, "--role", "debugger"), ("status",), ("review",), ("prune",), ("export", "--dry-run")):
            with self.subTest(command=command):
                before = self.fx.snapshot()
                done = self.run_cli(helper, *command)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(self.fx.snapshot(), before)
                self.assertFalse(any(name.endswith(("-journal", "-wal", "-shm")) for name in self.fx.snapshot()))
        with_scope = self.run_cli(helper, "list", "--scope", "global")
        self.assertEqual(with_scope.returncode, 2)
        self.assertIn("never falls back", with_scope.stderr)
        exported = self.run_cli(helper, "export-generation", "--output", str(self.fx.root / "library.json"))
        self.assertEqual(exported.returncode, 0, exported.stderr)
        self.assertEqual(json.loads((self.fx.root / "library.json").read_text())["revisions"], [])
        forgotten = self.run_cli(helper, "forget", "--event", events[0])
        self.assertEqual(json.loads(forgotten.stdout)["observations_removed"], 1)


if __name__ == "__main__":
    unittest.main()
