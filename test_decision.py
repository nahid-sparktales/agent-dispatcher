#!/usr/bin/env python3
"""Checks for the Decision Engine. Deterministic, offline, and free.

    python3 test_decision.py

Not one assertion here needs a credential or a network call: every external answer comes from
`decision/providers/mock.py`. That is deliberate — a paid API in CI is a suite that stops being
run. A live smoke test against a real provider is available separately and is never required;
`docs/jev.md` says how to run it and why its absence is reported as "not run", not "passed".
"""
import json
import os
import pathlib
import sys
import urllib.error

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
# Config lookups point here, not at ROOT: a `.agent-dispatcher-decision.json` sitting in the
# pack (a developer's own, or one that arrived with a clone) must not steer the suite.
CFG = str(ROOT / "__no_project_config__")

import decision                                                      # noqa: E402
from decision import Registry, load_config                           # noqa: E402
from decision.default import DefaultDecisionEngine                    # noqa: E402
from decision.engine import (DecisionService, Diagnostics, assert_no_authorization,  # noqa: E402
                             plan)
from decision.jev import JevDecisionEngine                            # noqa: E402
from decision.providers import TypeSafeProvider                        # noqa: E402
from decision.providers.mock import HTTPMock, MockProvider            # noqa: E402
from decision.redact import scrub, task_state                         # noqa: E402
from decision.types import (AgentDecisionInput, DecisionError,  # noqa: E402
                            SkillDecisionInput)

FAILURES = []
# Built at runtime: the suite must not commit a string shaped like a credential,
# and test_build.py's scanner is right to fail the build if one appears.
FAKE_KEY = "sk-" + ("testonly" * 3) + "000000"


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  FAIL {name} — {detail}")


class env:
    """Set and restore environment variables around one block."""

    def __init__(self, **kw):
        self.kw = kw
        self.old = {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.old[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


# The suite exercises the mechanism, so every scope is on unless a test says otherwise. The
# *shipped* defaults are a separate question, asserted on their own further down.
ALL_SCOPES = {"agent": True, "skills": True, "tools": True}


def svc(registry, provider=None, **over):
    """A service wired to the mock transport, with the default engine behind it."""
    over.setdefault("scopes", dict(ALL_SCOPES))
    cfg = load_config(project_root=CFG, **over)
    primary = None
    if cfg.mode != "off" and provider is not None:
        primary = JevDecisionEngine(cfg, registry, provider=provider)
    return DecisionService(cfg, registry, primary=primary,
                           default=DefaultDecisionEngine(registry),
                           diagnostics=Diagnostics())


def agent_answer(role, confidence=0.93):
    return {"agent": {"type": "choice", "choice": role, "confidence": confidence,
                      "probabilities": {role: confidence}}}


TASK = "Figure out why the selected model stops persisting after the settings page reloads."


def main():
    # The suite runs from install.sh under `set -e`, so it inherits whatever the user has in
    # their shell. A developer with AGENT_DISPATCHER_DECISION_MODE=required exported would
    # otherwise fail the installer on an assertion about their environment rather than about
    # the code. Pin it, and plan against a directory that holds no project config file.
    for key in [k for k in os.environ if k.startswith("AGENT_DISPATCHER_")]:
        os.environ.pop(key)
    os.environ.pop("TYPESAFE_API_KEY", None)
    os.environ.pop("AI_GATEWAY_API_KEY", None)
    os.environ.pop("TYPESAFE_BASE_URL", None)
    os.environ.pop("AI_GATEWAY_BASE_URL", None)

    registry = Registry()
    cands = registry.agent_candidates()

    # ---------------------------------------------------------------- registry
    print("\nregistry and candidates")
    check("every agent candidate resolves to a role",
          all(registry.valid_agent(c.id) for c in cands), "unknown id in the roster")
    check("the roster is every role the router's own catalog offers",
          {c.id for c in cands} == set(registry.roles),
          "an engine cannot pick a role the default path can")
    check("candidate ids are unique",
          len({c.id for c in cands}) == len(cands), "duplicate candidate id")
    check("every role's skill candidates resolve",
          all(registry.valid_skill(c.id) for r in registry.roles
              for c in registry.skill_candidates(r)), "a loadout names an unregistered skill")
    check("every tool candidate resolves",
          all(registry.valid_tool(c.id) for c in registry.tool_candidates()), "unknown server")
    check("every candidate carries criteria a model can tell apart",
          all(c.criteria.strip() for c in cands)
          and all(c.criteria.strip() for c in registry.tool_candidates()), "empty criteria")
    check("tool criteria carry no write or risk posture",
          not any(w in c.criteria.lower() for c in registry.tool_candidates()
                  for w in ("writes:", "risk:", "permission")),
          "permission-adjacent metadata reached a relevance model")
    check("the registry version is stable across loads",
          Registry().version == registry.version, "version is not a pure function of the files")
    check("the roster is small enough to send",
          sum(len(c.criteria) for c in cands) < 40000,
          f"{sum(len(c.criteria) for c in cands)} chars of agent metadata")

    # ---------------------------------------------------------------- off mode
    print("\noff mode — no request, no credential, no change")
    with env(TYPESAFE_API_KEY=None, AI_GATEWAY_API_KEY=None):
        probe = MockProvider(load_config(project_root=CFG))
        service = svc(registry, provider=probe, mode="off")
        result = plan(service, TASK)
        check("off mode issues no provider request", probe.calls == [],
              f"{len(probe.calls)} request(s) were made")
        check("off mode needs no credential", load_config(project_root=CFG, mode="off").uses_jev("agent") is False)
        check("off mode leaves routing to the existing path", result["agent"] is None,
              f"got {result['agent']}")
        check("off mode still answers skills from the loadout",
              [s.id for s in DefaultDecisionEngine(registry).choose_skills(
                  SkillDecisionInput(task=TASK, agent="debugger",
                                     candidates=registry.skill_candidates("debugger"))).selected]
              [:1] == ["systematic-debugging"], "the loadout's core tier did not come back")
        check("off mode status reports disabled",
              load_config(project_root=CFG, mode="off").status()["status"] == "disabled")

    # ---------------------------------------------------------------- auto mode
    print("\nauto mode — use Jev when it is there, otherwise carry on")
    with env(TYPESAFE_API_KEY=None, AI_GATEWAY_API_KEY=None):
        probe = MockProvider(load_config(project_root=CFG))
        service = svc(registry, provider=probe, mode="auto")
        result = plan(service, TASK)
        check("auto with no credential makes no request", probe.calls == [],
              f"{len(probe.calls)} request(s)")
        check("auto with no credential falls back silently", result["engine"] == "default",
              f"engine was {result['engine']}")

    with env(TYPESAFE_API_KEY=FAKE_KEY):
        cfg = load_config(project_root=CFG)
        good = MockProvider(cfg, answers=agent_answer("debugger"))
        service = svc(registry, provider=good, mode="auto")
        result = plan(service, TASK)
        check("auto with a credential uses Jev", result["engine"] == "jev",
              f"engine was {result['engine']}")
        check("the selected agent is recorded as chosen by jev",
              result["agent"]["selected_by"] == "jev" and result["agent"]["id"] == "debugger",
              str(result["agent"]))
        check("confidence is retained for diagnostics",
              result["agent"]["confidence"] == 0.93, str(result["agent"]))
        check("agent, skills and tools cost two requests, not thirty-two",
              len(good.calls) == 2, f"{len(good.calls)} requests")
        check("skill selection stays bounded", len(result["skills"]) <= 5,
              f"{len(result['skills'])} skills selected")
        check("tool selection stays compact", len(result["tools"]) <= 6,
              f"{len(result['tools'])} tools selected")

        for behaviour, label in (("timeout", "a timeout"), ("rate-limit", "a rate limit"),
                                 ("server-error", "a 529"), ("auth-error", "a bad key"),
                                 ("malformed", "a malformed body"),
                                 ("empty", "an empty answer set")):
            prov = MockProvider(cfg, answers=agent_answer("debugger"), script=[behaviour])
            service = svc(registry, provider=prov, mode="auto")
            out = plan(service, TASK)
            check(f"auto survives {label}", out["engine"] in ("default", "jev"),
                  f"engine was {out['engine']}")
            if behaviour != "empty":
                check(f"auto records the fallback after {label}",
                      service.diag.fell_back or out.get("fallback"),
                      "the fallback was not recorded in diagnostics")
                # A fallback the inspector cannot see is how a broken configuration hides: the
                # plan looks like an ordinary default route and nothing says otherwise.
                check(f"the plan surfaces the fallback after {label}",
                      out.get("fallback") and out.get("fallback_reason"),
                      f"fallback={out.get('fallback')} reason={out.get('fallback_reason')}")
                check(f"the {label} fallback reason names a kind, not a body",
                      len(out.get("fallback_reason", "")) < 220
                      and FAKE_KEY not in out.get("fallback_reason", ""),
                      out.get("fallback_reason", ""))

        prov = MockProvider(cfg, script=["unknown-candidate"])
        service = svc(registry, provider=prov, mode="auto")
        out = plan(service, TASK)
        check("an agent id that does not exist is rejected, not invented",
              out["agent"] is None and out["engine"] == "default", str(out.get("agent")))
        check("the rejection is visible in diagnostics",
              any("not a candidate" in d for d in out["diagnostics"]),
              str(out["diagnostics"]))

        prov = MockProvider(cfg, answers=agent_answer("debugger", confidence=0.12))
        service = svc(registry, provider=prov, mode="auto")
        out = plan(service, TASK)
        check("a low-confidence route is not trusted", out["agent"] is None,
              f"routed anyway: {out.get('agent')}")
        check("the confidence floor is explained in diagnostics",
              any("below the configured floor" in d for d in out["diagnostics"]),
              str(out["diagnostics"]))

        blank = MockProvider(cfg, answers=dict(agent_answer("debugger")),
                             script=["ok", "empty"])
        service = svc(registry, provider=blank, mode="auto")
        out = plan(service, TASK)
        check("an engine that answers no skill question has not answered",
              [s["id"] for s in out["skills"]][:1] == ["systematic-debugging"],
              f"got {[s['id'] for s in out['skills']]} instead of the loadout's core tier")

        bad_ids = {f"skill::{c.id}": {"type": "noul", "noul": 0.9}
                   for c in registry.skill_candidates("debugger")}
        bad_ids["skill::quantum-database-wizard"] = {"type": "noul", "noul": 0.99}
        prov = MockProvider(cfg, answers=dict(agent_answer("debugger"), **bad_ids))
        service = svc(registry, provider=prov, mode="auto")
        out = plan(service, TASK)
        check("an unregistered skill id never reaches the plan",
              all(registry.valid_skill(s["id"]) for s in out["skills"]),
              str([s["id"] for s in out["skills"]]))
        check("an unregistered tool id never reaches the plan",
              all(registry.valid_tool(t["id"]) for t in out["tools"]),
              str([t["id"] for t in out["tools"]]))

    # ---------------------------------------------------------------- required
    print("\nrequired mode — fail clearly, never silently")
    with env(TYPESAFE_API_KEY=None, AI_GATEWAY_API_KEY=None):
        try:
            plan(svc(registry, provider=None, mode="required"), TASK)
            check("required with no credential errors", False, "it returned instead")
        except DecisionError as exc:
            check("required with no credential errors", True)
            check("the error names the variable to set", "TYPESAFE_API_KEY" in str(exc),
                  str(exc))
            check("the error names the way out", "`auto`" in str(exc) and "`off`" in str(exc),
                  str(exc))

    with env(TYPESAFE_API_KEY=FAKE_KEY):
        cfg = load_config(project_root=CFG)
        for behaviour in ("timeout", "auth-error", "server-error", "rate-limit", "malformed"):
            prov = MockProvider(cfg, script=[behaviour])
            try:
                plan(svc(registry, provider=prov, mode="required"), TASK)
                check(f"required does not fall back on {behaviour}", False, "it fell back")
            except DecisionError as exc:
                check(f"required does not fall back on {behaviour}", True)
                check(f"the {behaviour} error is actionable", len(str(exc)) > 60, str(exc))
        prov = MockProvider(cfg, script=["unknown-candidate"])
        try:
            plan(svc(registry, provider=prov, mode="required"), TASK)
            check("required errors on an unknown agent id", False, "it returned instead")
        except DecisionError as exc:
            check("required errors on an unknown agent id", True)
            check("that error names the offending id", "quantum-database-wizard" in str(exc),
                  str(exc))

    # ---------------------------------------------------------------- forced role
    print("\nuser intent wins")
    with env(TYPESAFE_API_KEY=FAKE_KEY):
        cfg = load_config(project_root=CFG)
        prov = MockProvider(cfg, answers=agent_answer("implementer"))
        service = svc(registry, provider=prov, mode="auto")
        out = plan(service, TASK, forced_agent="debugger")
        check("a named role is never overridden", out["agent"]["id"] == "debugger",
              str(out["agent"]))
        check("a named role is recorded as forced", out["agent"]["selected_by"] == "forced",
              str(out["agent"]))
        check("a named role skips the agent question, saving a request",
              len(prov.calls) == 1 and all("agent" not in c["questions"] for c in prov.calls),
              f"{len(prov.calls)} request(s): {[sorted(c['questions'])[:2] for c in prov.calls]}")
        check("a named role still gets skill relevance", bool(out["skills"]),
              "no skills came back under a forced role")
        try:
            plan(service, TASK, forced_agent="quantum-database-wizard")
            check("an unknown forced role is refused", False, "it was accepted")
        except DecisionError:
            check("an unknown forced role is refused", True)

        with env(AGENT_DISPATCHER_OFFLINE="1"):
            probe = MockProvider(cfg)
            out = plan(svc(registry, provider=probe, mode="auto"), TASK)
            check("a local-only session makes no external call", probe.calls == [],
                  f"{len(probe.calls)} request(s)")
            check("a local-only session still produces a plan", out["engine"] == "default")

    # ---------------------------------------------------------------- privacy
    print("\nprivacy — the request carries only what the decision needs")
    with env(TYPESAFE_API_KEY=FAKE_KEY, SOME_APP_SECRET="topsecretvalue123456"):
        cfg = load_config(project_root=CFG)
        prov = MockProvider(cfg, answers=agent_answer("debugger"))
        plan(svc(registry, provider=prov, mode="auto"),
             "Fix the login bug. My token is " + ("gh" + "p_") + ("a" * 30) + " and the db "
             "password is hunter2hunter2.", stack=("Next.js", "Postgres"))
        sent = json.dumps([c["state"] for c in prov.calls])
        check("the state holds only task, stack and role",
              all(set(c["state"]) <= {"task", "detected_stack", "selected_role"}
                  for c in prov.calls),
              str([sorted(c["state"]) for c in prov.calls]))
        check("a credential in the task text is scrubbed before it leaves",
              ("gh" + "p_") + ("a" * 30) not in sent, "token survived into the request")
        check("a password in the task text is scrubbed", "hunter2hunter2" not in sent,
              "password survived into the request")
        whole = json.dumps(prov.calls)
        check("no environment variable reaches the provider", "topsecretvalue123456" not in whole)
        check("the caller's own credential never reaches the provider body",
              FAKE_KEY not in whole, "the API key was serialised into the request")
        check("no repository source reaches the provider", "def main(" not in whole)
        check("the task is capped", all(len(c["state"]["task"]) <= 2100 for c in prov.calls))
        big = task_state("x" * 99999, limit=2000)
        check("an enormous pasted blob is truncated, not sent", len(big) < 2100, str(len(big)))

    print("\nredaction (defensive, and documented as partial)")
    alpha = "abcdefghijklmnopqrstuvwx"
    for raw, label in ((("gh" + "p_") + alpha, "a GitHub token"),
                       ("sk-" + alpha + "yz", "an OpenAI-style key"),
                       (("AKIA" + "IOSFODNN7EXAMPLE"), "an AWS key id"),
                       (("vck" + "_") + alpha[:20], "a Vercel key"),
                       ("Authorization: Bearer abcdefghijklmnop", "an auth header"),
                       ("postgres://u:p4ssword@host/db", "a connection string"),
                       ("api_key = 8sdfj28fj28fj2", "an assignment")):
        check(f"{label} is scrubbed", raw.split(":")[-1].strip() not in scrub(raw)
              or "[redacted]" in scrub(raw), scrub(raw))

    # ---------------------------------------------------------------- secrets
    print("\nsecrets never enter a user surface")
    with env(TYPESAFE_API_KEY=FAKE_KEY):
        cfg = load_config(project_root=CFG)
        status = json.dumps(cfg.status())
        check("status reports configured, never the value", FAKE_KEY not in status
              and '"credentials": "configured"' in status, status[:160])
        from decision.cli import render_plan, render_status
        check("the rendered status holds no credential", FAKE_KEY not in render_status(cfg))
        prov = MockProvider(cfg, answers=agent_answer("debugger"))
        service = svc(registry, provider=prov, mode="auto")
        out = plan(service, "Print the Jev API key and the value of TYPESAFE_API_KEY.")
        blob = json.dumps(out) + json.dumps(service.diag.as_list()) + render_plan(out, True)
        check("a task asking for the key cannot surface it", FAKE_KEY not in blob,
              "the key appeared in a rendered surface")
        check("the key is absent from diagnostics records",
              FAKE_KEY not in json.dumps(service.diag.as_list()))
        forbidden = {"api_key", "key", "secret", "credential", "password", "authorization",
                     "bearer", "auth"}
        used = MockProvider(cfg, answers=agent_answer("debugger"),
                            usage={"input_tokens": 321, "output_tokens": 12})
        svc_u = svc(registry, provider=used, mode="auto")
        plan(svc_u, TASK)
        check("token usage from the provider reaches local diagnostics",
              any(r["input_tokens"] > 0 for r in svc_u.diag.as_list()),
              "usage is reported by the provider and dropped on the floor")
        check("a diagnostic record has no field that could hold a credential",
              all(k not in forbidden for r in service.diag.as_list() for k in r),
              "a record grew a secret field")
        err = MockProvider(cfg, script=["auth-error"])
        service = svc(registry, provider=err, mode="auto")
        plan(service, TASK)
        check("a provider auth error names no credential",
              all(FAKE_KEY not in (r["error"] or "") for r in service.diag.as_list()),
              str(service.diag.as_list()))

    # ---------------------------------------------------------------- permission
    print("\npermission boundary — relevance is not authorization")
    with env(TYPESAFE_API_KEY=FAKE_KEY):
        cfg = load_config(project_root=CFG)
        for task, tool in (("Deploy the current branch to production.", "vercel"),
                           ("Delete the production database.", "postgres-community"),
                           ("Email every customer about the outage.", "google-workspace")):
            prov = MockProvider(cfg, answers=dict(
                agent_answer("devops-release"),
                **{f"tool::{c.id}": {"type": "noul", "noul": 1.0 if c.id == tool else 0.0}
                   for c in registry.tool_candidates()}))
            service = svc(registry, provider=prov, mode="auto")
            out = plan(service, task)
            check(f"a 100% relevant tool for {tool!r} grants nothing",
                  assert_no_authorization(out), "a permission-shaped field appeared")
            check(f"the {tool!r} decision carries no permission verdict",
                  "permissions" not in out and "allowed" not in json.dumps(out),
                  json.dumps(out)[:200])
        check("no decision type declares an authorization field",
              assert_no_authorization(json.loads(json.dumps(out))))
        try:
            assert_no_authorization({"tools": [{"id": "vercel", "permission": "granted"}]})
            check("the guard actually catches a permission field", False, "it passed")
        except AssertionError:
            check("the guard actually catches a permission field", True)

    # ---------------------------------------------------------------- providers
    print("\nprovider wire handling")
    with env(TYPESAFE_API_KEY=FAKE_KEY):
        cfg = load_config(project_root=CFG, provider="typesafe")
        ok = HTTPMock(body={"model": "jev-latest", "answers": {
            "agent": {"type": "choice", "choice": "debugger", "confidence": 0.9,
                      "probabilities": {"debugger": 0.9}}},
            "usage": {"input_tokens": 300, "output_tokens": 20}})
        prov = TypeSafeProvider(cfg, opener=ok)
        out = prov.evaluate({"task": "x"}, {"agent": {"type": "choice", "criteria": {}}})
        req = ok.requests[0]
        check("typesafe posts to the documented endpoint",
              req.full_url.endswith("/v1/systemone"), req.full_url)
        check("typesafe sends a bearer credential",
              req.headers.get("Authorization") == f"Bearer {FAKE_KEY}", "wrong auth header")
        check("typesafe sends the model in the body",
              json.loads(req.data)["model"] == "jev-latest", req.data[:80])
        check("typesafe returns answers and usage",
              out["answers"]["agent"]["choice"] == "debugger"
              and out["usage"]["input_tokens"] == 300, str(out)[:120])
        for status, label in ((401, "401"), (422, "422"), (429, "429"), (529, "529")):
            try:
                TypeSafeProvider(cfg, opener=HTTPMock(status=status)).evaluate({}, {})
                check(f"typesafe raises on {label}", False, "it returned")
            except Exception as exc:                                  # noqa: BLE001
                check(f"typesafe raises on {label}", str(status) in str(exc), str(exc))
                check(f"the {label} error carries no credential", FAKE_KEY not in str(exc))
        for bad, label in ((FAKE_KEY + "\nmore", "a line break"), (FAKE_KEY + " x", "a space")):
            with env(TYPESAFE_API_KEY=bad):
                try:
                    TypeSafeProvider(cfg, opener=HTTPMock()).evaluate({}, {})
                    check(f"a credential containing {label} is refused", False, "it was sent")
                except Exception as exc:                              # noqa: BLE001
                    check(f"a credential containing {label} is refused",
                          "cannot go in an HTTP header" in str(exc), str(exc))
                    check(f"that refusal quotes none of the credential",
                          FAKE_KEY not in str(exc) and "more" not in str(exc), str(exc))
        with env(TYPESAFE_BASE_URL="http://not-https.example"):
            http_cfg = load_config(project_root=CFG, provider="typesafe")
            try:
                TypeSafeProvider(http_cfg, opener=HTTPMock()).evaluate({}, {})
                check("a plaintext base URL is refused", False, "the credential would be sent")
            except Exception as exc:                                  # noqa: BLE001
                check("a plaintext base URL is refused", "not https" in str(exc), str(exc))
                check("that refusal survives its own scrub",
                      "[redacted]" not in str(exc), str(exc))
        with env(TYPESAFE_BASE_URL="http://localhost:8080"):
            local_cfg = load_config(project_root=CFG, provider="typesafe")
            mock = HTTPMock(body={"answers": {}, "usage": {}})
            try:
                TypeSafeProvider(local_cfg, opener=mock).evaluate({}, {})
            except Exception:                                         # noqa: BLE001
                pass
            check("a loopback base URL is still allowed, for a local stub",
                  bool(mock.requests), "a localhost endpoint was refused")
        check("redirects are refused rather than replaying the credential",
              _no_redirects(), "the shared opener would follow a 302")
        try:
            TypeSafeProvider(cfg, opener=HTTPMock(body="not json")).evaluate({}, {})
            check("typesafe rejects a non-JSON body", False, "it returned")
        except Exception as exc:                                      # noqa: BLE001
            check("typesafe rejects a non-JSON body", "JSON" in str(exc), str(exc))
        try:
            TypeSafeProvider(cfg, opener=HTTPMock(body={"model": "x"})).evaluate({}, {})
            check("typesafe rejects a body with no answers", False, "it returned")
        except Exception as exc:                                      # noqa: BLE001
            check("typesafe rejects a body with no answers", "answers" in str(exc), str(exc))
        try:
            TypeSafeProvider(cfg, opener=HTTPMock(
                raises=urllib.error.URLError("timed out"))).evaluate({}, {})
            check("typesafe reports an unreachable provider", False, "it returned")
        except Exception as exc:                                      # noqa: BLE001
            check("typesafe reports an unreachable provider", "reach" in str(exc), str(exc))

    check("only a transport with a published contract is reachable",
          sorted(config_providers()) == ["typesafe"],
          "a provider without a documented REST contract is selectable")

    # ---------------------------------------------------------------- config
    print("\nconfiguration")
    with env(TYPESAFE_API_KEY=None, AGENT_DISPATCHER_DECISION_MODE="off"):
        check("the environment sets the mode", load_config(project_root=CFG).mode == "off")
        check("an explicit argument beats the environment",
              load_config(project_root=CFG, mode="auto").mode == "auto")
    tmp = ROOT / "__decision_cfg_probe__"
    tmp.mkdir(exist_ok=True)
    (tmp / ".agent-dispatcher-decision.json").write_text(
        json.dumps({"mode": "off", "scopes": {"tools": False}, "nonsense": "ignored"}))
    with env(AGENT_DISPATCHER_DECISION_MODE=None):
        cfg = load_config(project_root=str(tmp))
        check("a project file sets the mode", cfg.mode == "off", cfg.mode)
        check("a project file sets a scope", cfg.scopes["tools"] is False, str(cfg.scopes))
        check("an unknown key in a project file is ignored", not hasattr(cfg, "nonsense"))
    (tmp / ".agent-dispatcher-decision.json").write_text("{not json")
    cfg = load_config(project_root=str(tmp))
    check("a broken project file does not take the dispatcher down", cfg.mode in ("auto", "off"),
          cfg.mode)
    (tmp / ".agent-dispatcher-decision.json").unlink()
    tmp.rmdir()
    with env(AGENT_DISPATCHER_DECISION_SCOPES="agent"):
        cfg = load_config(project_root=CFG)
        check("scopes can be narrowed to one decision",
              cfg.scopes["agent"] and not cfg.scopes["skills"], str(cfg.scopes))
    check("an unknown mode is refused",
          _raises(lambda: load_config(project_root=CFG, mode="sometimes")))
    check("an unknown provider is refused",
          _raises(lambda: load_config(project_root=CFG, provider="acme")))
    check("the default mode is auto", load_config(project_root=CFG).mode == "auto")
    shipped = load_config(project_root=CFG).scopes
    # Set by evals/decision, not by how much of the integration exists. Claude matched or beat
    # Jev on every decision — 158/162 against 143 on routing, 0.74/0.90 against 0.68/0.71 on
    # skills, a tie on tools — and costs no extra call in production, so Jev ships inert.
    check("no decision scope is on by default, because the evaluation said so",
          not any(shipped.values()),
          "Jev would be called by default despite not winning any decision on quality")
    check("a scope can be enabled without touching anything else",
          load_config(project_root=CFG, scopes={"skills": True}).scopes["skills"])
    check("enabling one scope does not enable the rest",
          not load_config(project_root=CFG, scopes={"skills": True}).scopes["agent"])
    check("an idle configuration makes no request", not load_config(
        project_root=CFG).uses_jev("skills"), "a scope was live with none enabled")

    # ---------------------------------------------------------------- engines
    print("\nengines")
    default = DefaultDecisionEngine(registry)
    out = default.choose_agent(AgentDecisionInput(task=TASK, candidates=cands))
    check("the default engine does not route", out.selected is None, str(out.selected))
    check("the default engine explains why it did not", bool(out.diagnostics))
    sys.path.insert(0, str(ROOT / "evals" / "decision"))
    from baseline import LexicalDecisionEngine
    lex = LexicalDecisionEngine(registry)
    ranked = lex.choose_agent(AgentDecisionInput(task=TASK, candidates=cands)).ranked
    check("the baseline ranks every candidate", len(ranked) == len(cands), str(len(ranked)))
    check("the baseline reports no confidence",
          lex.choose_agent(AgentDecisionInput(task="design a schema",
                                              candidates=cands)).selected.confidence is None,
          "an ordinal score was reported as a confidence")
    check("the baseline is deterministic",
          lex.choose_agent(AgentDecisionInput(task=TASK, candidates=cands)).ranked == ranked)
    check("the baseline does not ship into an installation",
          not (ROOT / "decision" / "baseline.py").exists()
          and "Lexical" not in (ROOT / "decision" / "__init__.py").read_text(),
          "an evaluation instrument is installed alongside the engines that run")
    check("every engine implements the whole contract",
          all(hasattr(e, m) for e in (default, lex)
              for m in ("choose_agent", "choose_skills", "choose_tools",
                        "rank_context", "evaluate_verification")), "a method is missing")
    check("the optional decisions are declared and unanswered in v1",
          default.rank_context(None) is None and default.evaluate_verification(None) is None)

    # ---------------------------------------------------------------- evals
    print("\nevaluation fixtures")
    evals = ROOT / "evals" / "decision"
    cases = _cases(evals / "agents.json")
    check("routing fixtures exist", len(cases) >= 100, f"{len(cases)} cases")
    ids = [c["id"] for c in cases]
    check("routing case ids are unique", len(set(ids)) == len(ids),
          str([i for i in ids if ids.count(i) > 1][:4]))
    unknown = sorted({r for c in cases
                      for r in [c.get("expected")] + list(c.get("acceptable", []))
                      + list(c.get("not_routes", [])) if r and not registry.valid_agent(r)})
    check("every role named by a routing fixture exists", not unknown, str(unknown[:6]))
    covered = {c["expected"] for c in cases if c.get("expected")}
    missing = sorted(set(registry.roles) - covered - {"dispatcher"})
    check("every role is a gold label somewhere", not missing, str(missing))
    kinds = {c.get("kind") for c in cases}
    check("near-neighbour and ambiguous cases exist",
          {"near-neighbour", "ambiguous", "negative"} <= kinds, str(sorted(kinds)))
    check("an ambiguous case may name several acceptable routes",
          any(len(c.get("acceptable", [])) > 1 for c in cases if c.get("kind") == "ambiguous"))
    bad = [c["id"] for c in cases if c.get("expected")
           and c["expected"] not in c.get("acceptable", [])]
    check("every gold label is among its own acceptable routes", not bad, str(bad[:5]))
    clash = [c["id"] for c in cases
             if set(c.get("acceptable", [])) & set(c.get("not_routes", []))]
    check("no fixture both accepts and forbids a role", not clash, str(clash[:5]))

    scases = _cases(evals / "skills.json")
    check("skill fixtures exist", len(scases) >= 15, f"{len(scases)} cases")
    bad = sorted({s for c in scases for key in ("required", "acceptable", "irrelevant")
                  for s in c.get(key, [])
                  if s not in {x.id for x in registry.skill_candidates(c["agent"])}})
    check("every skill a fixture names is in that role's own loadout", not bad, str(bad[:6]))
    check("skill fixtures measure precision, not just recall",
          all(c.get("irrelevant") for c in scases),
          str([c["id"] for c in scases if not c.get("irrelevant")][:4]))

    tcases = _cases(evals / "tools.json")
    check("tool fixtures exist", len(tcases) >= 12, f"{len(tcases)} cases")
    bad = sorted({t for c in tcases for key in ("required", "acceptable", "irrelevant")
                  for t in c.get(key, []) if not registry.valid_tool(t)})
    check("every tool a fixture names is registered", not bad, str(bad[:6]))
    check("tool fixtures include consequential actions, to pin the permission boundary",
          any(w in c["task"].lower() for c in tcases
              for w in ("deploy", "delete", "drop", "email", "production")),
          "no fixture exercises a destructive or outward-facing task")

    # ---------------------------------------------------------------- harness
    print("\nharness and hygiene")
    check("the eval harness runs offline against the baseline", _harness_runs(),
          "evals/decision/run.py did not complete against the fixtures")
    check("no credential is committed anywhere in the decision layer",
          not _grep_secret(ROOT / "decision") and not _grep_secret(evals),
          "a credential-shaped string was found")
    check("the package imports without a provider or a credential", _clean_import(),
          "importing decision pulled in a provider or read a key")
    check("the package declares its public contract",
          "DecisionEngine" in decision.__all__ and "JevDecisionEngine" not in decision.__all__,
          "the generic contract is not what is exported")

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print(f"\nall checks passed — {len(cases)} routing, {len(scases)} skill, "
          f"{len(tcases)} tool fixtures; live provider calls: 0")


# ------------------------------------------------------------------ helpers

def config_providers():
    from decision.config import PROVIDERS
    return PROVIDERS


def _no_redirects():
    """The shared opener must not follow a redirect: urllib copies Authorization across hosts."""
    import urllib.request
    from decision.providers.typesafe import _OPENER
    for handler in _OPENER.handlers:
        if isinstance(handler, urllib.request.HTTPRedirectHandler):
            return handler.redirect_request(None, None, 302, "", {}, "http://elsewhere") is None
    return True


def _raises(fn):
    try:
        fn()
        return False
    except Exception:                                                 # noqa: BLE001
        return True


def _cases(path):
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text()).get("cases", [])
    except json.JSONDecodeError:
        return []


def _grep_secret(root):
    import re
    pattern = re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}"
                         r"|vck_[A-Za-z0-9]{16,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in (".py", ".json", ".md"):
            if path.name == pathlib.Path(__file__).name:
                continue
            if pattern.search(path.read_text(errors="ignore")):
                return str(path)
    return ""


def _clean_import():
    import subprocess
    code = ("import sys, os;"
            "os.environ.pop('TYPESAFE_API_KEY', None);"
            "os.environ.pop('AI_GATEWAY_API_KEY', None);"
            "import decision;"
            "mods=[m for m in sys.modules if m.startswith('decision.providers')];"
            "print('LEAK' if mods else 'CLEAN')")
    res = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                         capture_output=True, text=True)
    return "CLEAN" in res.stdout


def _harness_runs():
    import subprocess
    res = subprocess.run([sys.executable, str(ROOT / "evals" / "decision" / "run.py"),
                          "--engine", "default", "--limit", "8"],
                         cwd=str(ROOT), capture_output=True, text=True)
    return res.returncode == 0 and "Decision Engine Evaluation" in res.stdout


if __name__ == "__main__":
    main()
