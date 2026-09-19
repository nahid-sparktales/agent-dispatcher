#!/usr/bin/env python3
"""Compare decision engines on identical fixtures. Nothing here is fabricated or hardcoded.

    python3 evals/decision/run.py                          # the offline baseline only
    python3 evals/decision/run.py --engine jev             # needs your own credential
    python3 evals/decision/run.py --engine both --json out.json

The question this answers is *whether* Jev helps, not that it does. If the baseline routes
better, the report says so; if Jev improves skill selection but not agent routing, the report
says that too. The architecture exists so each decision can use whichever mechanism the
evidence supports — see `docs/jev.md`.

Two engines are compared:

  `default`  the lexical baseline in `decision/default.py`. It is a *measurement floor*, not
             the dispatcher's production default: in production the default engine defers
             agent routing to the model, which is not something this harness can score
             offline. The report repeats that caveat rather than letting the number imply
             otherwise.
  `jev`      the real thing, through whichever provider is configured. Costs money, billed to
             the account that owns the key. Not run unless asked for and credentialed.
"""
import argparse
import json
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent.parent))
sys.path.insert(0, str(ROOT))

from decision import Registry, load_config                          # noqa: E402
from baseline import LexicalDecisionEngine                           # noqa: E402
from decision.types import (AgentDecisionInput, DecisionError, SkillDecisionInput,  # noqa: E402
                            ToolDecisionInput)

BANDS = ((0.9, 1.01), (0.8, 0.9), (0.7, 0.8), (0.5, 0.7), (0.0, 0.5))


def load_cases(name):
    path = ROOT / f"{name}.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text()).get("cases", [])


def build_engine(kind, registry, provider_instance=None, **over):
    cfg = load_config(project_root=str(ROOT), mode="off" if kind == "default" else "required",
                      **over)
    if kind == "default":
        return LexicalDecisionEngine(registry), cfg
    from decision.jev import JevDecisionEngine
    return JevDecisionEngine(cfg, registry, provider=provider_instance), cfg


# ------------------------------------------------------------------ scoring

def score_agents(engine, registry, cases):
    candidates = registry.agent_candidates()
    rows, failures = [], 0
    for case in cases:
        started = time.monotonic()
        try:
            out = engine.choose_agent(AgentDecisionInput(
                task=case["task"], candidates=candidates, stack=tuple(case.get("stack", ()))))
            error = ""
        except Exception as exc:                                    # noqa: BLE001
            failures += 1
            out, error = None, f"{exc.__class__.__name__}"
        latency = int((time.monotonic() - started) * 1000)
        picked = out.selected.id if (out and out.selected) else ""
        conf = out.selected.confidence if (out and out.selected) else None
        acceptable = set(case.get("acceptable") or ([case["expected"]] if case.get("expected")
                                                     else []))
        rows.append({
            "id": case["id"], "kind": case.get("kind", "obvious"),
            "expected": case.get("expected", ""), "picked": picked, "confidence": conf,
            "latency_ms": latency, "error": error,
            "top1": bool(picked) and picked == case.get("expected"),
            "acceptable": bool(picked) and picked in acceptable,
            "avoided": picked not in set(case.get("not_routes") or ()),
        })
    return {"rows": rows, "failures": failures}


def _pr(selected, required, irrelevant):
    """Precision and recall for a multi-select decision, plus the noise rate we care about."""
    sel = set(selected)
    req, irr = set(required), set(irrelevant)
    hit = len(sel & req)
    precision = hit / len(sel) if sel else 0.0
    recall = hit / len(req) if req else 1.0
    noise = len(sel & irr) / len(sel) if sel else 0.0
    return precision, recall, noise, sorted(sel & irr)


def score_multi(engine, registry, cases, kind):
    rows, failures = [], 0
    for case in cases:
        agent = case["agent"]
        if kind == "skills":
            inp = SkillDecisionInput(task=case["task"], agent=agent,
                                     candidates=registry.skill_candidates(agent),
                                     stack=tuple(case.get("stack", ())), limit=5)
            call = engine.choose_skills
        else:
            inp = ToolDecisionInput(task=case["task"], agent=agent,
                                    candidates=registry.tool_candidates(),
                                    stack=tuple(case.get("stack", ())))
            call = engine.choose_tools
        started = time.monotonic()
        try:
            out = call(inp)
            error = ""
        except Exception as exc:                                    # noqa: BLE001
            failures += 1
            out, error = None, exc.__class__.__name__
        latency = int((time.monotonic() - started) * 1000)
        picked = [s.id for s in out.selected] if out else []
        precision, recall, noise, leaked = _pr(picked, case.get("required", ()),
                                               case.get("irrelevant", ()))
        rows.append({"id": case["id"], "agent": agent, "picked": picked,
                     "precision": round(precision, 4), "recall": round(recall, 4),
                     "noise": round(noise, 4), "leaked_irrelevant": leaked,
                     "selected_count": len(picked), "latency_ms": latency, "error": error})
    return {"rows": rows, "failures": failures}


def calibration(rows):
    """Observed accuracy per confidence band. Empirical — never assume the number is calibrated."""
    out = []
    for low, high in BANDS:
        band = [r for r in rows if r.get("confidence") is not None
                and low <= r["confidence"] < high]
        if not band:
            continue
        out.append({"band": f"{low:.2f}–{min(high, 1.0):.2f}", "n": len(band),
                    "top1_accuracy": round(sum(r["top1"] for r in band) / len(band), 4),
                    "acceptable_rate": round(sum(r["acceptable"] for r in band) / len(band), 4)})
    return out


def summarise(agents, skills, tools):
    rows = agents["rows"]
    n = len(rows) or 1
    by_kind = {}
    for row in rows:
        bucket = by_kind.setdefault(row["kind"], {"n": 0, "top1": 0, "acceptable": 0})
        bucket["n"] += 1
        bucket["top1"] += row["top1"]
        bucket["acceptable"] += row["acceptable"]
    lat = [r["latency_ms"] for r in rows] or [0]
    out = {
        "agent_routing": {
            "cases": len(rows),
            "top1_correct": sum(r["top1"] for r in rows),
            "acceptable": sum(r["acceptable"] for r in rows),
            "avoided_wrong_route": sum(r["avoided"] for r in rows),
            "no_decision": sum(1 for r in rows if not r["picked"]),
            "failures": agents["failures"],
            "median_latency_ms": int(statistics.median(lat)),
            "p90_latency_ms": int(sorted(lat)[max(0, int(len(lat) * 0.9) - 1)]),
            "by_kind": {k: {"n": v["n"], "top1": v["top1"], "acceptable": v["acceptable"]}
                        for k, v in sorted(by_kind.items())},
            "calibration": calibration(rows),
        }
    }
    for name, data in (("skill_selection", skills), ("tool_selection", tools)):
        rs = data["rows"]
        if not rs:
            continue
        out[name] = {
            "cases": len(rs),
            "mean_precision": round(sum(r["precision"] for r in rs) / len(rs), 4),
            "mean_recall": round(sum(r["recall"] for r in rs) / len(rs), 4),
            "mean_irrelevant_rate": round(sum(r["noise"] for r in rs) / len(rs), 4),
            "mean_selected": round(sum(r["selected_count"] for r in rs) / len(rs), 2),
            "failures": data["failures"],
            "median_latency_ms": int(statistics.median(
                [r["latency_ms"] for r in rs] or [0])),
        }
    return out


# ------------------------------------------------------------------ reporting

def render(report):
    lines = ["Decision Engine Evaluation", "─" * 52,
             f"registry {report['registry_version']} · fixtures "
             f"{report['counts']['agents']} routing / {report['counts']['skills']} skill / "
             f"{report['counts']['tools']} tool", ""]
    for engine, res in report["engines"].items():
        if res.get("not_run"):
            lines += [f"{engine}", f"  not run — {res['not_run']}", ""]
            continue
        route = res["agent_routing"]
        lines += [f"{engine}",
                  f"  Agent routing   top-1 {route['top1_correct']}/{route['cases']}"
                  f" · acceptable {route['acceptable']}/{route['cases']}"
                  f" · avoided-wrong {route['avoided_wrong_route']}/{route['cases']}",
                  f"                  no decision {route['no_decision']}"
                  f" · failures {route['failures']}"
                  f" · median {route['median_latency_ms']}ms"
                  f" · p90 {route['p90_latency_ms']}ms"]
        for kind, k in route["by_kind"].items():
            lines.append(f"    {kind:<16}top-1 {k['top1']}/{k['n']}"
                         f" · acceptable {k['acceptable']}/{k['n']}")
        if route["calibration"]:
            lines.append("    confidence      observed top-1")
            for band in route["calibration"]:
                lines.append(f"      {band['band']:<14}{band['top1_accuracy']:.2f}"
                             f"  (n={band['n']})")
        else:
            lines.append("    confidence      none produced by this engine")
        for name, label in (("skill_selection", "Skill selection"),
                            ("tool_selection", "Tool selection")):
            if name in res:
                s = res[name]
                lines.append(f"  {label:<16}precision {s['mean_precision']:.2f}"
                             f" · recall {s['mean_recall']:.2f}"
                             f" · irrelevant {s['mean_irrelevant_rate']:.2f}"
                             f" · mean selected {s['mean_selected']}"
                             f" · failures {s['failures']}")
        lines.append("")
    lines += report["caveats"]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--engine", choices=("default", "jev", "both"), default="default")
    ap.add_argument("--provider", default=None)
    ap.add_argument("--json", help="write the full per-case report here")
    ap.add_argument("--limit", type=int, default=0, help="run only the first N cases of each set")
    args = ap.parse_args(argv)

    registry = Registry()
    agents = load_cases("agents")
    skills = load_cases("skills")
    tools = load_cases("tools")
    if args.limit:
        agents, skills, tools = agents[:args.limit], skills[:args.limit], tools[:args.limit]

    wanted = ("default", "jev") if args.engine == "both" else (args.engine,)
    report = {"registry_version": registry.version,
              "counts": {"agents": len(agents), "skills": len(skills), "tools": len(tools)},
              "engines": {}, "caveats": []}

    for kind in wanted:
        if kind == "jev":
            cfg = load_config(project_root=str(ROOT), provider=args.provider)
            if not cfg.has_credential():
                report["engines"]["jev"] = {
                    "not_run": f"no credential in {cfg.credential_env}. This is not a failure; "
                               f"supply your own key to run it."}
                continue
        try:
            engine, cfg = build_engine(kind, registry, provider_instance=None,
                                       provider=args.provider)
        except (DecisionError, ValueError) as exc:
            report["engines"][kind] = {"not_run": str(exc)}
            continue
        res = summarise(score_agents(engine, registry, agents),
                        score_multi(engine, registry, skills, "skills"),
                        score_multi(engine, registry, tools, "tools"))
        res["provider"] = getattr(cfg, "provider", "")
        res["model"] = getattr(cfg, "model", "")
        report["engines"][kind] = res

    report["caveats"] = [
        "`default` here is the lexical baseline, a measurement floor. In production the",
        "default engine defers agent routing to the model, which cannot be scored offline —",
        "so a Jev number above the baseline is not automatically a number above production.",
        "Confidence bands are observed, not assumed calibrated. Thresholds in decision/config.py",
        "stay provisional until these bands say otherwise.",
    ]
    if args.json:
        detail = dict(report)
        pathlib.Path(args.json).write_text(json.dumps(detail, indent=2) + "\n")
    print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
