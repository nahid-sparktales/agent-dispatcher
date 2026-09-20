"""Loopback-only anonymous review UI. No model calls or external services are used."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
from urllib.parse import urlsplit

from . import reporting

MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_REQUEST_BYTES = 64 * 1024
MAX_NOTES = 6000
PACKET_ID = re.compile(r"R-[a-f0-9]{20}\Z")
_UNSET = object()
SCENARIOS = {
    "review_transfer": ("Review money transfers", "Assess a code review of wallet transfers and its concrete defect evidence."),
    "review_cache": ("Find cache bugs", "Assess a cache review against its contract and reproducible examples."),
    "migration_plan": ("Plan a safe CSV migration", "Assess a plan to migrate a local CSV catalog to SQLite without implementing it."),
    "storage_research": ("Choose storage for a desktop app", "Assess a recommendation based only on the supplied project documents."),
    "clarify_timezone": ("Choose the missing time zone", "The request needs one timezone decision. A necessary clarification is not unnecessary intervention."),
    "docs_only_scope": ("Change one README heading", "Assess the requested heading change and whether every other file stayed untouched."),
}
DIMENSIONS = [
    {"id": "correctness", "label": "Correctness", "question": "Is the answer correct?",
     "help": "Check the answer and artifacts against the request and supplied evidence."},
    {"id": "completeness", "label": "Completeness", "question": "Does it cover the whole request?",
     "help": "Check every requested outcome. A necessary clarification can be the complete requested response."},
    {"id": "scope", "label": "Scope", "question": "Did it stay within scope?",
     "help": "Look for unrequested changes, implementation, browsing, or other actions."},
    {"id": "unsupported_claims", "label": "Supported claims", "question": "Are its claims supported by the evidence?",
     "help": "Compare factual and testing claims with source and observed verification. Choose unsure when evidence is missing."},
    {"id": "unnecessary_intervention", "label": "Independence", "question": "Did it avoid unnecessary questions or hand-offs?",
     "help": "Necessary clarification, including the requested timezone decision, is appropriate. Judge only avoidable requests for help."},
]


class ReviewError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _json(raw):
    return json.loads(raw, object_pairs_hook=_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Invalid JSON number")))


def _display_answer(text):
    """Hide routing announcements in a display copy; never change bound review evidence."""
    kept, skip_paragraph = [], False
    for line in text.splitlines():
        if not line.strip():
            skip_paragraph = False
            kept.append(line)
            continue
        if re.match(r"^\s*(?:→|->)\s*[\w-]+\s*[·|].*\bskills?\b", line, re.I):
            continue
        standalone_signals = (re.match(r"^\s*Signals\s+`[a-z][a-z_]+`", line, re.I)
                              and re.search(r"\bestablished\b", line, re.I)
                              and re.search(r"\b(?:were|was) (?:not )?loaded\b", line, re.I))
        if standalone_signals or re.match(r"^\s*(?:\*\*)?routing signals(?:\*\*)?\s*[:—–]", line, re.I):
            skip_paragraph = True
        if not skip_paragraph:
            kept.append(line)
    return "\n".join(kept).strip()


class ReviewApp:
    """One fixed batch, anonymous browser data, and evidence-bound revisioned drafts."""

    def __init__(self, batch):
        self.batch = Path(batch).expanduser().resolve()
        if not self.batch.is_dir():
            raise ReviewError(400, "Choose an existing evaluation batch.")
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(32)
        self._check_outputs()
        # Refuse an arbitrary folder before create_review can write any files.
        metadata = self._read("batch.json")
        results = self._read("results.json")
        if (not isinstance(metadata, dict) or metadata.get("schema_version") != 1
                or not isinstance(results, dict) or results.get("schema_version") != 1):
            raise ReviewError(409, "Choose a valid evaluation batch with captured results.")
        have_map = self._path("review-map.json").exists()
        have_packets = self._path("review/packets.json").exists()
        if have_map != have_packets:
            raise ReviewError(409, "Review packets are incomplete; restore the original review bundle.")
        if not have_map:
            if self._path("review-ratings.json").exists() or self._path("review-ui-state.json").exists():
                raise ReviewError(409, "Existing ratings need their original anonymous review packets.")
            try:
                reporting.create_review(self.batch)
            except (ValueError, OSError, KeyError, TypeError) as error:
                raise ReviewError(409, "Review evidence is invalid; packets could not be prepared.") from error
        self.evidence, self.trials, self.mapping, self.original_packets, self.metadata = self._snapshot()
        self.by_trial = {trial["id"]: trial for trial in self.trials}
        self.required = {trial["id"] for trial in self.trials
                         if trial.get("auto_grade", {}).get("human_required") is True}
        self.packets = []
        self.scenarios = []
        scenario_ids = {}
        for packet in self.original_packets:
            trial = self.by_trial[self.mapping[packet["packet_id"]]["trial_id"]]
            if trial["id"] not in self.required:
                continue
            fixture = trial.get("fixture_id", "")
            if fixture not in scenario_ids:
                ident = "scenario-" + str(len(scenario_ids) + 1)
                scenario_ids[fixture] = ident
                label, description = SCENARIOS.get(fixture, ("Scenario " + str(len(scenario_ids)),
                                                            "Assess this response against the supplied request and evidence."))
                self.scenarios.append({"id": ident, "label": label, "description": description})
            scenario = next(row for row in self.scenarios if row["id"] == scenario_ids[fixture])
            display = copy.deepcopy(packet)
            display["final_answer"] = _display_answer(display["final_answer"])
            display.update(scenario_id=scenario["id"], scenario_label=scenario["label"])
            self.packets.append(display)
        self.packet_ids = {packet["packet_id"] for packet in self.packets}
        self.state = self._load_state()
        self.official_digest = _digest(self._official())

    def _path(self, relative):
        path = self.batch / relative
        cursor = self.batch
        for part in Path(relative).parts:
            if part in ("..", "/"):
                raise ReviewError(409, "Unsafe review file location.")
            cursor = cursor / part
            if cursor.is_symlink():
                raise ReviewError(409, "Review files must not be symbolic links.")
        if not path.resolve().is_relative_to(self.batch):
            raise ReviewError(409, "Review files must remain inside the selected batch.")
        return path

    def _check_outputs(self):
        for relative in ("batch.json", "results.json", "review-map.json", "review/packets.json",
                         "review/ratings-template.json", "review/packets.md", "review-ratings.json",
                         "review-ui-state.json", "report.json", "report.md"):
            path = self._path(relative)
            self._path(relative + ".tmp")
            if path.exists() and not path.is_file():
                raise ReviewError(409, "A review file location is not a regular file.")

    def _read(self, relative, default=None):
        path = self._path(relative)
        if not path.exists() and default is not None:
            return copy.deepcopy(default)
        try:
            if not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
                raise ValueError()
            raw = path.read_bytes()
            if len(raw) > MAX_JSON_BYTES:
                raise ValueError()
            return _json(raw)
        except (OSError, ValueError, UnicodeError, RecursionError) as error:
            raise ReviewError(409, "A review data file is invalid or unavailable.") from error

    def _snapshot(self):
        self._check_outputs()
        try:
            metadata = self._read("batch.json")
            results = self._read("results.json")
            trials = reporting._trials(self.batch)
            if any(not isinstance(trial.get("auto_grade", {}), dict) for trial in trials):
                raise ValueError()
            mapping_file = self._read("review-map.json")
            packets_file = self._read("review/packets.json")
            mapping = mapping_file["packets"]
            packets = packets_file["packets"]
            if not isinstance(mapping, dict) or not isinstance(packets, list) or len(packets) > 1000:
                raise ValueError()
            by_trial = {trial["id"]: trial for trial in trials}
            seen, seen_trials = set(), set()
            for packet in packets:
                packet_id = packet["packet_id"]
                if not isinstance(packet_id, str) or not PACKET_ID.fullmatch(packet_id) or packet_id in seen:
                    raise ValueError()
                seen.add(packet_id)
                item = mapping[packet_id]
                trial_id = item["trial_id"]
                if trial_id in seen_trials:
                    raise ValueError()
                seen_trials.add(trial_id)
                expected = reporting._packet(self.batch, by_trial[trial_id])
                given = {key: value for key, value in packet.items() if key != "packet_id"}
                if reporting._digest(expected) != item["digest"] or given != expected:
                    raise ValueError()
            if seen != set(mapping) or seen_trials != set(by_trial):
                raise ValueError()
            fingerprint = _digest({"metadata": metadata, "results": results, "mapping": mapping_file,
                                   "packets": packets_file})
            return fingerprint, trials, mapping, packets, metadata
        except ReviewError:
            raise
        except (ValueError, OSError, KeyError, TypeError, AttributeError, RecursionError) as error:
            raise ReviewError(409, "Review evidence changed or is invalid; original packets must be restored.") from error

    @property
    def revision(self):
        return self.state["revision"]

    def _answers(self, row):
        if not isinstance(row, dict) or set(row) - set(reporting.DIMENSIONS):
            raise ReviewError(400, "Answers must use the five displayed review questions.")
        if any(value not in (None, "yes", "no", "unsure") for value in row.values()):
            raise ReviewError(400, "Choose yes, no, unsure, or leave a question unanswered.")
        return {key: row.get(key) for key in reporting.DIMENSIONS}

    def _draft(self, row):
        if not isinstance(row, dict) or set(row) != {"answers", "notes"}:
            raise ReviewError(400, "A draft needs answers and notes.")
        notes = row["notes"]
        if not isinstance(notes, str) or len(notes) > MAX_NOTES or "\0" in notes:
            raise ReviewError(400, "Notes must contain at most 6000 characters.")
        return {"answers": self._answers(row["answers"]), "notes": notes}

    def _official(self):
        value = self._read("review-ratings.json", {"schema_version": 1, "ratings": {}})
        try:
            ratings = value["ratings"]
            if value["schema_version"] != 1 or not isinstance(ratings, dict):
                raise ValueError()
            for trial_id, row in ratings.items():
                if self.mapping[row["packet_id"]]["trial_id"] != trial_id:
                    raise ValueError()
                if any(type(row[key]) is not bool for key in reporting.DIMENSIONS):
                    raise ValueError()
                if not isinstance(row.get("notes", ""), str):
                    raise ValueError()
            return ratings
        except (KeyError, TypeError, ValueError) as error:
            raise ReviewError(409, "Existing official reviews are invalid; they were not changed.") from error

    def _load_state(self):
        default = {"schema_version": 1, "evidence_digest": self.evidence, "revision": 0,
                   "saved_at": None, "drafts": {}}
        state = self._read("review-ui-state.json", default)
        try:
            if set(state) != set(default) or state["schema_version"] != 1 or state["evidence_digest"] != self.evidence:
                raise ValueError()
            if type(state["revision"]) is not int or state["revision"] < 0 or not isinstance(state["drafts"], dict):
                raise ValueError()
            if set(state["drafts"]) - self.packet_ids:
                raise ValueError()
            state["drafts"] = {key: self._draft(value) for key, value in state["drafts"].items()}
        except (TypeError, ValueError, KeyError) as error:
            raise ReviewError(409, "Saved drafts do not match the current review evidence.") from error
        self.disk_state = copy.deepcopy(state) if self._path("review-ui-state.json").exists() else None
        official = self._official()
        for packet in self.packets:
            packet_id = packet["packet_id"]
            if packet_id in state["drafts"]:
                continue
            rating = official.get(self.mapping[packet_id]["trial_id"])
            if rating:
                answers = {key: "yes" if (rating[key] if key in reporting.DIMENSIONS[:3] else not rating[key]) else "no"
                           for key in reporting.DIMENSIONS}
                state["drafts"][packet_id] = {"answers": answers, "notes": rating.get("notes", "")}
            else:
                state["drafts"][packet_id] = {"answers": {key: None for key in reporting.DIMENSIONS}, "notes": ""}
        return state

    def _fresh(self, revision=_UNSET):
        if revision is not _UNSET and (type(revision) is not int or revision != self.revision):
            raise ReviewError(409, "Drafts changed. Reload before saving another change.")
        if self._snapshot()[0] != self.evidence:
            raise ReviewError(409, "Review evidence changed. No ratings were applied.")
        current = self._read("review-ui-state.json", {})
        if current != (self.disk_state or {}):
            raise ReviewError(409, "Saved drafts changed elsewhere. Restart or reload the review server.")
        if _digest(self._official()) != self.official_digest:
            raise ReviewError(409, "Official reviews changed elsewhere. Restart the review server before applying changes.")

    def _write_bytes(self, relative, raw):
        target = self._path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".review-ui-", suffix=".tmp", dir=target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self._path(relative)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def _write_json(self, relative, value):
        self._write_bytes(relative, (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode())

    def _save(self, state):
        state["revision"] += 1
        state["saved_at"] = _now()
        self._write_json("review-ui-state.json", state)
        self.state = state
        self.disk_state = copy.deepcopy(state)

    def _canonical(self, packet_id):
        row = self.state["drafts"][packet_id]
        complete = all(value in ("yes", "no") for value in row["answers"].values())
        values = {key: ((row["answers"][key] == "yes") if key in reporting.DIMENSIONS[:3]
                        else (row["answers"][key] == "no")) if complete else None
                  for key in reporting.DIMENSIONS}
        return {"packet_id": packet_id, **values, "notes": row["notes"]}

    def _applied(self):
        official = self._official()
        return [packet["packet_id"] for packet in self.packets
                if self._canonical(packet["packet_id"]) == official.get(self.mapping[packet["packet_id"]]["trial_id"])]

    def _official_ids(self):
        official = self._official()
        return [packet["packet_id"] for packet in self.packets
                if self.mapping[packet["packet_id"]]["trial_id"] in official]

    def review(self):
        with self.lock:
            self._fresh()
            return {"title": "Anonymous review", "total": len(self.packets), "dimensions": copy.deepcopy(DIMENSIONS),
                    "scenarios": copy.deepcopy(self.scenarios), "packets": copy.deepcopy(self.packets),
                    "drafts": copy.deepcopy(self.state["drafts"]), "applied_ids": self._applied(),
                    "official_ids": self._official_ids(),
                    "token": self.token, "revision": self.revision}

    def save_draft(self, body):
        with self.lock:
            if not isinstance(body, dict) or set(body) != {"packet_id", "answers", "notes", "revision"}:
                raise ReviewError(400, "A draft needs a packet, answers, notes, and revision.")
            self._fresh(body["revision"])
            if not isinstance(body["packet_id"], str) or body["packet_id"] not in self.packet_ids:
                raise ReviewError(400, "Unknown anonymous packet.")
            draft = self._draft({"answers": body["answers"], "notes": body["notes"]})
            state = copy.deepcopy(self.state)
            state["drafts"][body["packet_id"]] = draft
            self._save(state)
            return {"revision": self.revision, "saved_at": self.state["saved_at"],
                    "applied_ids": self._applied(), "official_ids": self._official_ids()}

    def export(self):
        with self.lock:
            self._fresh()
            return {"schema_version": 1, "ratings": [self._canonical(packet["packet_id"]) for packet in self.packets]}

    def apply(self, body):
        with self.lock:
            if not isinstance(body, dict) or set(body) != {"revision"}:
                raise ReviewError(400, "Apply needs the current revision.")
            self._fresh(body["revision"])
            exported = self.export()
            targets = ("review-ratings.json", "report.json", "report.md", "review-ui-state.json")
            backups = {name: self._path(name).read_bytes() if self._path(name).exists() else None for name in targets}
            descriptor, name = tempfile.mkstemp(prefix=".review-ui-import-", suffix=".json", dir=self.batch)
            temporary = Path(name)
            removed = 0
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(exported, stream, ensure_ascii=False, allow_nan=False)
                # Explicit UI Apply synchronizes the latest required-packet choices.
                # Raw import_review keeps its existing merge-only/pending semantics.
                official = self._official()
                for row in exported["ratings"]:
                    trial_id = self.mapping[row["packet_id"]]["trial_id"]
                    if all(row[key] is None for key in reporting.DIMENSIONS) and trial_id in official:
                        del official[trial_id]
                        removed += 1
                if removed:
                    self._write_json("review-ratings.json", {"schema_version": 1, "ratings": official})
                reporting.import_review(self.batch, temporary)
                generated = reporting.report(self.batch)
                if "postprocessing" in self.metadata:
                    generated["postprocessing"] = copy.deepcopy(self.metadata["postprocessing"])
                    self._write_json("report.json", generated)
                    markdown = self._path("report.md").read_text()
                    markdown += "\n## Postprocessing\n\nThis report includes the recorded postprocessing corrections; original trial evidence is unchanged.\n"
                    self._write_bytes("report.md", markdown.encode())
                self._save(copy.deepcopy(self.state))
                self.official_digest = _digest(self._official())
            except (ValueError, OSError, KeyError, TypeError) as error:
                for relative, raw in backups.items():
                    if raw is None:
                        self._path(relative).unlink(missing_ok=True)
                    else:
                        self._write_bytes(relative, raw)
                raise ReviewError(409, "Reviews could not be applied safely; previous ratings were restored.") from error
            finally:
                temporary.unlink(missing_ok=True)
            applied = self._applied()
            return {"revision": self.revision, "applied_ids": applied, "applied_count": len(applied),
                    "official_ids": self._official_ids(), "removed_count": removed,
                    "remaining": len(self.packets) - len(applied)}

    def results(self):
        with self.lock:
            self._fresh()
            if len(self._applied()) != len(self.packets):
                raise ReviewError(403, "Apply a complete review for every packet before viewing results.")
            ratings = self._official()
            schedule = self.metadata.get("schedule", [])
            clients = {}
            for client in sorted({trial["client"] for trial in self.trials}):
                trials = [trial for trial in self.trials if trial["client"] == client]
                planned = [item for item in schedule if item.get("client") == client]
                conditions = {condition: reporting._group([trial for trial in trials if trial["condition"] == condition],
                              ratings, sum(row.get("condition") == condition for row in planned))
                              for condition in reporting.CONDITIONS}
                pairs = reporting._pairs(trials, ratings, planned)
                pairs.pop("details", None)
                clients[client] = {"conditions": conditions, "pairs": pairs}
            return {"schema_version": 1, "suite": self.metadata.get("suite"), "clients": clients,
                    "limitations": ["These small fixtures do not establish benefit on real workloads.",
                                    "Each attempt is counted; repetitions are not independent tasks.",
                                    "Review evidence was blinded; writing style may still reveal its origin."]}


class ReviewHandler(BaseHTTPRequestHandler):
    server_version = "LocalReview/1"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        # Do not log packet content, tokens, or request paths containing user text.
        pass

    def _reply(self, status, raw, content_type="application/json; charset=utf-8", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def _send_json(self, status, value, extra=None):
        self._reply(status, json.dumps(value, ensure_ascii=False, allow_nan=False).encode(), extra=extra)

    def _origin(self, mutate=False):
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            hosts |= {"127.0.0.1", "localhost"}
        host = self.headers.get("Host", "")
        if len(self.headers.get_all("Host", [])) != 1 or host not in hosts:
            raise ReviewError(403, "Use the local review address shown by the server.")
        origin = self.headers.get("Origin")
        if (origin is not None and origin != "http://" + host) or (mutate and origin is None):
            raise ReviewError(403, "This request must come from the local review page.")
        if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
            raise ReviewError(403, "Cross-site requests are not permitted.")
        if mutate and not secrets.compare_digest(self.headers.get("X-Review-Token", "").encode(), self.server.app.token.encode()):
            raise ReviewError(403, "Refresh the review page before saving.")

    def _body(self):
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
            raise ReviewError(400, "Supply one bounded JSON request body.")
        if self.headers.get_content_type() != "application/json":
            raise ReviewError(415, "Use a JSON request body.")
        try:
            length = int(self.headers["Content-Length"])
        except (TypeError, ValueError):
            raise ReviewError(400, "Invalid request length.") from None
        if not 0 < length <= MAX_REQUEST_BYTES:
            raise ReviewError(413, "The review request is too large.")
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError()
            return _json(raw)
        except (ValueError, UnicodeError, RecursionError, OSError):
            raise ReviewError(400, "The request must contain valid JSON.") from None

    def _route(self, mutate=False):
        try:
            self._origin(mutate)
            if urlsplit(self.path).query or self.path not in {"/", "/app.js", "/styles.css", "/api/review", "/api/draft", "/api/apply", "/api/export", "/api/results"}:
                raise ReviewError(404, "Unknown review route.")
            app = self.server.app
            if mutate:
                actions = {"/api/draft": app.save_draft, "/api/apply": app.apply}
                if self.path not in actions:
                    raise ReviewError(405, "This route is read-only.")
                self._send_json(200, actions[self.path](self._body()))
            elif self.path in {"/", "/app.js", "/styles.css"}:
                filename, content_type = {"/": ("index.html", "text/html; charset=utf-8"),
                                          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                                          "/styles.css": ("styles.css", "text/css; charset=utf-8")}[self.path]
                path = self.server.web_root / filename
                if path.is_symlink() or not path.is_file():
                    raise ReviewError(404, "Review interface file unavailable.")
                self._reply(200, path.read_bytes(), content_type)
            elif self.path == "/api/review":
                self._send_json(200, app.review())
            elif self.path == "/api/export":
                self._send_json(200, app.export(), {"Content-Disposition": 'attachment; filename="review-ratings.json"'})
            elif self.path == "/api/results":
                self._send_json(200, app.results())
            else:
                raise ReviewError(405, "Use POST for review changes.")
        except ReviewError as error:
            self._send_json(error.status, {"error": str(error), "revision": self.server.app.revision})
        except (OSError, ValueError, TypeError, KeyError):
            self._send_json(500, {"error": "The local review request could not be completed safely."})

    def do_GET(self):
        self._route()

    def do_POST(self):
        self._route(mutate=True)

    def do_OPTIONS(self):
        self._send_json(405, {"error": "Cross-origin access is not supported."})


def make_server(app, host="127.0.0.1", port=8765, web_root=None):
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("Review server only binds to the local loopback address.")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535.")
    server = HTTPServer(("127.0.0.1", port), ReviewHandler)
    server.app = app
    server.web_root = Path(web_root or Path(__file__).with_name("review_web")).resolve()
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    try:
        app = ReviewApp(args.batch)
        server = make_server(app, port=args.port)
    except (ReviewError, OSError, ValueError):
        parser.exit(2, "Review server could not start: check the batch evidence, saved drafts, and local port.\n")
    print(f"Review {len(app.packets)} anonymous packets at http://127.0.0.1:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
