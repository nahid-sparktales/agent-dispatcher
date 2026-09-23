"""Shared fixture for the procedural-learning test groups: an isolated project, config home, experience events and stores.

Not a test module (no `test_` prefix), so the runner manifest does not list it.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest import mock

import context
import experience
import learning
import learning_eval
import repo_store

ROOT = Path(__file__).resolve().parents[1]
PACK = context.find_pack(str(ROOT))
FILES = {"auth/tokens.py": "def validate_token(token):\n    return bool(token)\n",
         "auth/session.py": "def open_session(user):\n    return {'user': user}\n",
         "tests/test_tokens.py": "from auth.tokens import validate_token\n"}
TASK = "Fix the failing regression bug in validate_token"
ENVIRONMENT = {"model": "synthetic", "effort": "n/a", "auth_mode": "none", "cli_version": "none", "seed": 0}


class LearningFixture:
    def __init__(self, test, name="project", files=FILES):
        self.test = test
        self.temporary = tempfile.TemporaryDirectory(prefix="dispatcher-learning-")
        test.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.config_home = self.root / "config"
        self.config_home.mkdir()
        # One cache home per fixture as well: profile stores are keyed by name, so two tests must never share one.
        patcher = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config_home), "XDG_CACHE_HOME": str(self.root / "cache")})
        patcher.start()
        test.addCleanup(patcher.stop)
        os.environ.pop("AGENT_DISPATCHER_LEARNING_CONFIG", None)
        self.project = self.make_project(name, files)
        self.directory = repo_store.state_directory(self.project)
        self.scrub = context._scrubber(PACK)
        self.settings_path = self.config_home / "agent-dispatcher" / "procedural-learning.json"

    def make_project(self, name, files=FILES):
        project = self.root / name
        for path, text in files.items():
            (project / path).parent.mkdir(parents=True, exist_ok=True)
            (project / path).write_text(text, encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        return project

    def enable(self, mode="active", **overrides):
        settings = {"enabled": True, "mode": mode, "observation": {"record": True}, "review": {"min_support_families": 1, "due_after_observations": 2},
                    "evaluation": {"min_paired_families": 4, "min_blocks": 1}}
        for key, value in overrides.items():
            settings[key] = value
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(settings))
        return learning.load_settings(project=self.project)

    @property
    def settings(self):
        return learning.load_settings(project=self.project)

    def record_events(self, count=3, *, role="debugger", outcome="accepted", task=TASK, edited=("auth/tokens.py",), prefix="t"):
        ids = []
        with repo_store.ExperienceStore(self.directory, create=True) as store:
            for number in range(count):
                event = experience.build_event(project=self.project, task_id=f"{prefix}-{number}", task=f"{task} case {number}", scrub=self.scrub, role=role,
                                               edited=edited, outcome=outcome)
                experience.record(store, event)
                ids.append(event["id"])
        return ids

    def experience(self, readonly=True):
        return repo_store.ExperienceStore(self.directory, readonly=readonly)

    def store(self, *, create=True, readonly=False, namespace_kind="test"):
        store = learning.LearningStore(self.directory, create=create, readonly=readonly, namespace_kind=namespace_kind)
        if create and not readonly and not store.meta("pack"):
            with store.transaction():
                store.set_meta("pack", str(PACK))
        return store

    @staticmethod
    def skill_document(events, *, text="In this repository, validate_token bugs usually sit in the boolean short-circuit; reproduce with an empty token first.",
                       slot="repository_procedure", terms=("validate_token", "regression"), roles=("debugger",), **extra):
        document = {"schema_version": 1, "kind": "skill_overlay", "operation": "specialize", "scope": "repo",
                    "target": {"artifact_id": "systematic-debugging", "slot": slot}, "payload": {"slot": slot, "text": text},
                    "applicability": {"roles": list(roles), "task_terms": list(terms), "min_term_matches": 1},
                    "hypothesis": "debugger tasks here repeatedly touched the token branch", "created_by_kind": "host_assisted",
                    "supporting_event_ids": list(events)}
        document.update(extra)
        return document

    def propose(self, store, document, scope="repo"):
        with self.experience() as es:
            return learning.propose_candidate(store, es, document, self.settings, pack=PACK, namespace=self.directory.name, scope=scope)

    def evaluate(self, store, revision, *, pairs=None, objective="correctness", spec_extra=None, families=8):
        pairs = pairs if pairs is not None else {"pairs": [{"family": f"f{n}", "block": n % 2, "candidate": True, "incumbent": n % 3 == 0} for n in range(families)]}
        spec = {"schema_version": 1, "objective": objective, "runner": "fake_test_runner", "environment": dict(ENVIRONMENT), **(spec_extra or {})}
        with self.experience() as es:
            return learning_eval.evaluate_candidate(store, es, revision, spec, self.settings, pack=PACK, runner="fake_test_runner", fixture_results=pairs)

    def approve(self, store, revision, evaluation_id, *, rollout="active", canary=None, expected=None):
        with self.experience() as es:
            return learning.approve_candidate(store, es, revision, evaluation_id, expected, {"kind": "human", "actor": "tester", "rollout": rollout},
                                              self.settings, pack=PACK, canary=canary)

    def promote(self, store, revision, expected=None):
        with self.experience() as es:
            return learning.promote_candidate(store, es, revision, expected, self.settings, pack=PACK)

    def admit(self, store, document, *, rollout="active", canary=None):
        """Tier A -> Tier B -> fake Tier C -> approval -> promotion, in a test namespace."""
        proposed = self.propose(store, document)
        revision = proposed["revision_id"]
        learning_eval.component_checks(store, revision, self.settings, pack=PACK)
        report = self.evaluate(store, revision)
        active = store.active_generation()
        expected = active["generation_id"] if active else None
        self.approve(store, revision, report["evaluation_id"], rollout=rollout, canary=canary, expected=expected)
        return revision, self.promote(store, revision, expected)

    def packet(self, task=TASK, role="debugger", guides=("systematic-debugging",), project=None, **kwargs):
        return context.select_context(project or self.project, task, role=role, pack=ROOT, compact=True, guide_ids=list(guides), **kwargs)

    def snapshot(self, directory=None):
        directory = Path(directory or self.directory)
        if not directory.exists():
            return {}
        return {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in directory.iterdir()}
