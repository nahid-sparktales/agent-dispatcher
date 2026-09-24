"""Local review UI tests use disposable evidence, never the user's pilot ratings."""
import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from evals.end_to_end import reporting, review_app


class ReviewFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.trials = []
        for fixture in review_app.SCENARIOS:
            for repetition in (1, 2):
                for condition in ("baseline", "dispatcher"):
                    self.add_trial(fixture, repetition, condition)
        self.add_trial("objective-task", 1, "baseline", required=False)
        self.save()
        self.app = review_app.ReviewApp(self.root)

    def add_trial(self, fixture, repetition, condition, required=True):
        ident = f"claude-{fixture}-{repetition}-{condition}"
        artifact_dir = "trials/" + ident
        folder = self.root / artifact_dir / "final"
        folder.mkdir(parents=True)
        (folder / "source.py").write_text("print('source evidence')\n")
        self.trials.append({"id": ident, "client": "claude", "condition": condition,
                            "fixture_id": fixture, "category": "review", "repetition": repetition,
                            "status": "completed", "artifact_dir": artifact_dir,
                            "task_success": None, "treatment_invoked": condition == "dispatcher",
                            "auto_grade": {"passed": True, "checks": [], "human_required": required},
                            "prompt": "Inspect the supplied code.", "acceptance": ["Identify the defect."],
                            "rubric": {}, "final_answer": "The defect is supported by source evidence.",
                            "elapsed_seconds": 10, "usage": {}})

    def save(self):
        (self.root / "results.json").write_text(json.dumps({"schema_version": 1, "trials": self.trials}))
        self.batch = {"schema_version": 1, "suite": "pilot", "seed": 7,
                      "provenance": {"private_path": "/private/evaluation/config.json"},
                      "postprocessing": {"reason": "native replay recognition corrected", "rerun": False},
                      "schedule": [{k: trial[k] for k in ("client", "condition", "fixture_id", "repetition")}
                                   for trial in self.trials]}
        (self.root / "batch.json").write_text(json.dumps(self.batch))

    def draft(self, packet_id=None, answer="yes", notes="Checked."):
        packet_id = packet_id or self.app.review()["packets"][0]["packet_id"]
        return self.app.save_draft({"packet_id": packet_id,
                                   "answers": {key: answer for key in reporting.DIMENSIONS},
                                   "notes": notes, "revision": self.app.revision})


class ReviewAppTests(ReviewFixture, unittest.TestCase):
    def test_scope_evidence_reaches_review_without_private_activity_or_default_ratings(self):
        scoped = self.root / "scope-batch"
        scoped.mkdir()
        trial = copy.deepcopy(self.trials[0])
        trial.update(status="task_failure", task_success=False,
                     scope_check={"passed": False},
                     scope_audit={"schema_version": 1, "availability": "complete",
                                  "entry_count": 1, "entries": [
                                      {"path": "check_report.py", "kind": "file", "size": 1903}]},
                     activity={"schema_version": 1, "availability": "partial",
                               "summary": {"roles_read": ["documentation-writer"]},
                               "actions": [{"kind": "write", "target": "outside-owned-trial",
                                            "outcome": "succeeded", "event_line": 5}]})
        (scoped / "results.json").write_text(json.dumps({"schema_version": 1, "trials": [trial]}))
        batch = copy.deepcopy(self.batch)
        batch["schedule"] = [batch["schedule"][0]]
        (scoped / "batch.json").write_text(json.dumps(batch))
        response = review_app.ReviewApp(scoped).review()
        packet = response["packets"][0]
        evidence = packet["scope_evidence"]
        self.assertTrue(evidence["requires_human_inspection"])
        self.assertEqual(evidence["residue"], [{"path": "check_report.py", "kind": "file", "size": 1903}])
        self.assertEqual(evidence["outside_audit_remaining_state"], "unknown")
        self.assertNotIn("documentation-writer", json.dumps(response))
        self.assertNotIn('"activity"', json.dumps(response))
        self.assertTrue(all(value is None for value in response["drafts"][packet["packet_id"]]["answers"].values()))

    def test_selects_24_required_packets_without_identity_or_performance(self):
        response = self.app.review()
        self.assertEqual(response["total"], 24)
        original = json.loads((self.root / "review/packets.json").read_text())["packets"]
        expected = [p["packet_id"] for p in original if p["packet_id"] in self.app.packet_ids]
        self.assertEqual([p["packet_id"] for p in response["packets"]], expected)
        self.assertEqual(len(response["scenarios"]), 6)
        text = json.dumps(response)
        for key in ("condition", "trial_id", "elapsed_seconds", "provenance", "private_path", "usage"):
            self.assertNotIn('"' + key + '"', text)
        for trial in self.trials:
            self.assertNotIn(trial["id"], text)
        self.assertFalse(response["applied_ids"])
        self.assertTrue(all(value is None for row in response["drafts"].values() for value in row["answers"].values()))

    def test_yes_no_polarity_and_unsure_export(self):
        ids = [p["packet_id"] for p in self.app.review()["packets"]]
        self.draft(ids[0], "yes")
        self.draft(ids[1], "no")
        self.draft(ids[2], "unsure")
        rows = {row["packet_id"]: row for row in self.app.export()["ratings"]}
        self.assertEqual([rows[ids[0]][key] for key in reporting.DIMENSIONS], [True, True, True, False, False])
        self.assertEqual([rows[ids[1]][key] for key in reporting.DIMENSIONS], [False, False, False, True, True])
        self.assertTrue(all(rows[ids[2]][key] is None for key in reporting.DIMENSIONS))
        result = self.app.apply({"revision": self.app.revision})
        self.assertEqual(result["applied_count"], 2)
        self.assertEqual(result["remaining"], 22)

    def test_drafts_persist_and_reload_without_defaults(self):
        packet = self.app.review()["packets"][0]["packet_id"]
        self.app.save_draft({"packet_id": packet, "answers": {"correctness": "yes"},
                             "notes": "<script>inert notes</script>", "revision": 0})
        fresh = review_app.ReviewApp(self.root)
        self.assertEqual(fresh.revision, 1)
        self.assertEqual(fresh.review()["drafts"][packet]["answers"]["correctness"], "yes")
        self.assertIsNone(fresh.review()["drafts"][packet]["answers"]["completeness"])
        self.assertEqual(fresh.review()["drafts"][packet]["notes"], "<script>inert notes</script>")
        self.assertNotEqual(self.app.token, fresh.token)

    def test_stale_revision_and_invalid_input_do_not_write(self):
        self.draft()
        before = (self.root / "review-ui-state.json").read_bytes()
        packet = self.app.review()["packets"][0]["packet_id"]
        bad_rows = [({"packet_id": packet, "answers": {}, "notes": "", "revision": 0}, 409),
                    ({"packet_id": packet, "answers": {}, "notes": "", "revision": None}, 409),
                    ({"packet_id": "../results.json", "answers": {}, "notes": "", "revision": 1}, 400),
                    ({"packet_id": packet, "answers": {"correctness": True}, "notes": "", "revision": 1}, 400),
                    ({"packet_id": packet, "answers": {}, "notes": "x" * 6001, "revision": 1}, 400)]
        for body, status in bad_rows:
            with self.subTest(status=status):
                with self.assertRaises(review_app.ReviewError) as caught:
                    self.app.save_draft(body)
                self.assertEqual(caught.exception.status, status)
                self.assertEqual((self.root / "review-ui-state.json").read_bytes(), before)

    def test_non_batch_directory_is_rejected_without_creating_review_files(self):
        empty = self.root / "not-a-batch"
        empty.mkdir()
        with self.assertRaises(review_app.ReviewError):
            review_app.ReviewApp(empty)
        self.assertEqual(list(empty.iterdir()), [])

    def test_packet_tampering_and_symlink_state_are_refused(self):
        packets = self.root / "review/packets.json"
        original = packets.read_bytes()
        changed = json.loads(original)
        changed["packets"][0]["final_answer"] = "Forged review evidence"
        packets.write_text(json.dumps(changed))
        with self.assertRaises(review_app.ReviewError):
            self.app.review()
        packets.write_bytes(original)
        outside = self.root / "unrelated.json"
        outside.write_text("untouched")
        (self.root / "review-ui-state.json").symlink_to(outside)
        with self.assertRaises(review_app.ReviewError):
            self.draft()
        self.assertEqual(outside.read_text(), "untouched")

    def test_failed_report_restores_previous_ratings_reports_and_state(self):
        self.draft()
        self.app.apply({"revision": self.app.revision})
        self.draft(answer="no")
        targets = ("review-ratings.json", "report.json", "report.md", "review-ui-state.json")
        before = {name: (self.root / name).read_bytes() for name in targets}
        with patch.object(reporting, "report", side_effect=ValueError("simulated failure")):
            with self.assertRaises(review_app.ReviewError):
                self.app.apply({"revision": self.app.revision})
        self.assertEqual({name: (self.root / name).read_bytes() for name in targets}, before)
        self.assertFalse(list(self.root.glob(".review-ui-*.json")))

    def test_changed_source_and_packet_tampering_are_rejected(self):
        self.draft()
        target = self.root / self.trials[0]["artifact_dir"] / "final/source.py"
        target.write_text("changed evidence\n")
        with self.assertRaises(review_app.ReviewError) as caught:
            self.app.apply({"revision": self.app.revision})
        self.assertEqual(caught.exception.status, 409)
        self.assertFalse((self.root / "review-ratings.json").exists())
        with self.assertRaises(review_app.ReviewError):
            review_app.ReviewApp(self.root)

    def test_existing_ratings_hydrate_and_other_rows_are_preserved(self):
        mapping = json.loads((self.root / "review-map.json").read_text())["packets"]
        ids = [self.app.review()["packets"][0]["packet_id"],
               next(key for key, value in mapping.items() if "objective-task" in value["trial_id"])]
        rating_file = self.root / "existing.json"
        rating_file.write_text(json.dumps({"schema_version": 1, "ratings": [
            {"packet_id": packet, **dict(zip(reporting.DIMENSIONS, [True, True, True, False, False])), "notes": "Existing"}
            for packet in ids]}))
        reporting.import_review(self.root, rating_file)
        self.app = review_app.ReviewApp(self.root)
        self.assertIn(ids[0], self.app.review()["applied_ids"])
        self.assertEqual(self.app.review()["drafts"][ids[0]]["notes"], "Existing")
        self.draft(answer="no")
        self.app.apply({"revision": self.app.revision})
        ratings = json.loads((self.root / "review-ratings.json").read_text())["ratings"]
        self.assertIn(mapping[ids[1]]["trial_id"], ratings)

    def test_apply_preserves_provenance_and_unlocks_only_current_complete_reviews(self):
        for packet in self.app.review()["packets"]:
            self.draft(packet["packet_id"])
        with self.assertRaises(review_app.ReviewError) as caught:
            self.app.results()
        self.assertEqual(caught.exception.status, 403)
        result = self.app.apply({"revision": self.app.revision})
        self.assertEqual(result["remaining"], 0)
        generated = json.loads((self.root / "report.json").read_text())
        self.assertEqual(generated["postprocessing"], self.batch["postprocessing"])
        self.assertEqual(generated["provenance"], self.batch["provenance"])
        self.assertEqual(json.loads((self.root / "batch.json").read_text()), self.batch)
        summary = self.app.results()
        self.assertIn("clients", summary)
        self.assertNotIn("private_path", json.dumps(summary))
        self.assertNotIn("details", summary["clients"]["claude"]["pairs"])
        self.draft(answer="unsure")
        with self.assertRaises(review_app.ReviewError):
            self.app.results()

    def test_apply_retracts_previous_rating_when_latest_draft_is_unsure(self):
        packet_id = self.app.review()["packets"][0]["packet_id"]
        self.draft(packet_id)
        self.app.apply({"revision": self.app.revision})
        changed = self.draft(packet_id, answer="unsure")
        self.assertIn(packet_id, changed["official_ids"])
        self.assertNotIn(packet_id, changed["applied_ids"])
        applied = self.app.apply({"revision": self.app.revision})
        self.assertEqual(applied["removed_count"], 1)
        self.assertEqual(applied["remaining"], 24)
        self.assertNotIn(packet_id, applied["official_ids"])
        report = json.loads((self.root / "report.json").read_text())
        conditions = report["clients"]["claude"]["conditions"]
        self.assertEqual(sum(row["required_reviews_pending"] for row in conditions.values()), 24)
        with self.assertRaises(review_app.ReviewError) as caught:
            self.app.results()
        self.assertEqual(caught.exception.status, 403)

    def test_reviews_imported_elsewhere_are_not_silently_overwritten(self):
        packet_id = self.app.review()["packets"][0]["packet_id"]
        incoming = self.root / "external-ratings.json"
        incoming.write_text(json.dumps({"schema_version": 1, "ratings": [
            {"packet_id": packet_id, **dict(zip(reporting.DIMENSIONS, [True, True, True, False, False]))}]}))
        reporting.import_review(self.root, incoming)
        before = (self.root / "review-ratings.json").read_bytes()
        with self.assertRaises(review_app.ReviewError) as caught:
            self.app.apply({"revision": self.app.revision})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual((self.root / "review-ratings.json").read_bytes(), before)

    def test_routing_announcements_are_removed_only_from_presentation(self):
        self.trials[0]["final_answer"] = (
            "→ planner · Skills loaded: planning\n\nRouting signals: migration.\n\n"
            "Signals `schema_change` and `schema_migration` are established by the request; "
            "`api_change` and `security_sensitive` are not, so `api-design` and `threat-modeling` were not loaded.\n\n"
            "The defect is real. Tests were not run.")
        self.save()
        # A fresh batch gets a fresh review map; the actual user's evidence is never modified.
        import shutil
        (self.root / "review-map.json").unlink()
        shutil.rmtree(self.root / "review")
        app = review_app.ReviewApp(self.root)
        original = (self.root / "review/packets.json").read_bytes()
        response = app.review()
        text = json.dumps(response)
        self.assertNotIn("Skills loaded", text)
        self.assertNotIn("Routing signals", text)
        self.assertNotIn("schema_change", text)
        self.assertIn("Tests were not run", text)
        self.assertEqual((self.root / "review/packets.json").read_bytes(), original)


class ReviewHttpTests(ReviewFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.web = self.root / "web"
        self.web.mkdir()
        for name in ("index.html", "app.js", "styles.css"):
            (self.web / name).write_text("fixture static content")
        self.server = review_app.make_server(self.app, port=0, web_root=self.web)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        request_headers = {"Content-Type": "application/json", "Origin": self.origin,
                           "X-Review-Token": self.app.token}
        request_headers.update(headers or {})
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=request_headers)
        response = connection.getresponse()
        status, result_headers, raw = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, result_headers, raw

    def test_http_host_origin_csrf_limits_and_routes(self):
        packet = self.app.review()["packets"][0]["packet_id"]
        body = {"packet_id": packet, "answers": {}, "notes": "", "revision": 0}
        for headers in ({"Host": "attacker.example"}, {"Origin": "https://attacker.example"},
                        {"X-Review-Token": "wrong"}):
            self.assertEqual(self.request("POST", "/api/draft", body, headers)[0], 403)
        self.assertEqual(self.request("GET", "/api/review", headers={"Host": "attacker.example"})[0], 403)
        # The server rejects on Content-Length alone and closes with the body unread, so sending a real
        # oversized body races a TCP reset (seen on macOS); send only the headers.
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.putrequest("POST", "/api/draft")
        for key, value in {"Content-Type": "application/json", "Origin": self.origin, "X-Review-Token": self.app.token,
                           "Content-Length": str(review_app.MAX_REQUEST_BYTES + 1)}.items():
            connection.putheader(key, value)
        connection.endheaders()
        self.assertEqual(connection.getresponse().status, 413)
        connection.close()
        for route in ("/../results.json", "/%2e%2e/results.json", "/api/review?batch=elsewhere", "/review-map.json"):
            self.assertEqual(self.request("GET", route)[0], 404)
        status, headers, raw = self.request("GET", "/api/review")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(json.loads(raw)["total"], 24)
        self.assertEqual(self.request("POST", "/api/draft", body)[0], 200)
        self.assertEqual(self.request("POST", "/api/draft", body)[0], 409)

    def test_static_export_and_no_network_binding(self):
        for route in ("/", "/app.js", "/styles.css"):
            self.assertEqual(self.request("GET", route)[0], 200)
        self.assertEqual(self.request("GET", "/api/results")[0], 403)
        status, headers, raw = self.request("GET", "/api/export")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(len(json.loads(raw)["ratings"]), 24)
        with self.assertRaises(ValueError):
            review_app.make_server(self.app, host="0.0.0.0", port=0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
