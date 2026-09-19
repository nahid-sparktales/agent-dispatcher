"""`python3 -m decision` — what the dispatcher shells out to, and what a user inspects.

    python3 -m decision status
    python3 -m decision plan  --task "..." [--agent <role-id>] [--stack next.js,tailwind]
                              [--mode off|auto|required] [--json] [--explain]
    python3 -m decision mode  off | auto | required        (writes the project config file)

Nothing here prints a credential. `status` says `configured` or `not configured`, which is the
whole of what a user needs to know and the whole of what this program will say.
"""
import argparse
import json
import pathlib
import sys

from . import config as config_mod
from . import service
from .engine import plan as build_plan
from .types import DecisionError


def _fmt_pct(value):
    return "" if value is None else f"{round(value * 100)}%"


def render_status(cfg):
    st = cfg.status()
    lines = ["Jev Decision Engine", "",
             f"Mode          {st['mode']}",
             f"Provider      {st['provider']}",
             f"Model         {st['model']}",
             f"Credentials   {st['credentials']}  (env: {st['credential_env'] or 'n/a'})",
             f"Timeout       {st['timeout_seconds']:g}s",
             f"Status        {st['status']}", "",
             "Decision scopes"]
    for name, on in st["scopes"].items():
        lines.append(f"  {name:<13}{'on' if on else 'off'}")
    lines += ["", "Thresholds (provisional — see evals/decision)"]
    for name, val in st["thresholds"].items():
        lines.append(f"  {name:<20}{val:g}")
    lines += ["", "Config from   " + ", ".join(st["config_sources"])]
    if st["mode"] != "off" and not any(st["scopes"].values()):
        lines += ["", "No decision scope is enabled, so Jev will not be called. That is the",
                  "shipped default: on this repository's own evaluation the default path matched",
                  "or beat Jev on every decision, so it is installed inert. Enable what you want",
                  "it for — latency and cost are the real trade:", "",
                  "  AGENT_DISPATCHER_DECISION_SCOPES=skills,tools", "",
                  "See docs/jev.md for the numbers."]
    elif st["mode"] != "off" and st["credentials"] == "not configured":
        lines += ["", "No credential is configured, so the default engine is in use. That is a",
                  "supported configuration: agent-dispatcher needs no Jev account. To enable",
                  f"Jev, set {st['credential_env']} in your environment; usage is billed to the",
                  "account that owns that key."]
    return "\n".join(lines)


def render_plan(result, explain=False):
    engine = result.get("engine", "default")
    label = {"jev": "Jev", "default": "Default", "lexical-baseline": "Lexical baseline"}.get(
        engine, engine)
    lines = ["Decision Engine", f"  {label}"]
    if result.get("fallback"):
        why = result.get("fallback_reason") or "unavailable"
        lines.append(f"  {result.get('attempted') or 'the decision engine'} attempted "
                     f"but unavailable: {why}")
        lines.append("  Fallback: successful")
    agent = result.get("agent")
    lines.append("")
    if agent:
        note = {"forced": " — named by the user", "jev": "", "default": "",
                "recipe": " — from a recipe"}.get(agent["selected_by"], "")
        pct = _fmt_pct(agent.get("confidence"))
        lines += ["Selected Agent", f"  {agent['id']}" + (f" — {pct}" if pct else "") + note]
    else:
        lines += ["Selected Agent",
                  "  not decided here — the dispatcher's own routing owns this"]
    for key, heading in (("skills", "Skills"), ("tools", "Tools")):
        rows = result.get(key) or []
        if rows:
            lines += ["", heading]
            for row in rows:
                pct = _fmt_pct(row.get("confidence"))
                lines.append(f"  {row['id']}" + (f" — {pct}" if pct else ""))
    if explain:
        for key, heading, field in (("agent_ranked", "Agent candidates", "probability"),
                                    ("skill_ranked", "Skill relevance", "relevance"),
                                    ("tool_ranked", "Tool relevance", "relevance")):
            rows = result.get(key) or []
            if rows:
                lines += ["", heading]
                for row in rows:
                    lines.append(f"  {row['id']:<32}{_fmt_pct(row.get(field))}")
    diags = result.get("diagnostics") or []
    if diags:
        lines += ["", "Diagnostics"]
        lines += [f"  {d}" for d in diags]
    lines += ["", "Relevance is not authorization. Nothing above grants a permission, and the",
              "runtime's permission layer never reads it."]
    return "\n".join(lines)


# What a broken installation actually raises: a catalog that was not copied, a registry file
# someone truncated, a JSON file half-written. None of them deserve a traceback.
BROKEN = (DecisionError, FileNotFoundError, json.JSONDecodeError, KeyError, OSError, ValueError)


def cmd_status(args):
    try:
        cfg = config_mod.load(project_root=args.project, mode=args.mode, provider=args.provider)
    except BROKEN as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(render_status(cfg))
    return 0


def cmd_mode(args):
    path = pathlib.Path(args.project or ".").resolve() / config_mod.PROJECT_CONFIG
    raw = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError:
            raw = {}
    raw["mode"] = args.value
    path.write_text(json.dumps(raw, indent=2) + "\n")
    print(f"decision mode set to `{args.value}` in {path}")
    return 0


def cmd_plan(args):
    stack = tuple(s.strip() for s in (args.stack or "").split(",") if s.strip())
    try:
        svc = service(project_root=args.project, mode=args.mode, provider=args.provider)
        result = build_plan(svc, args.task, forced_agent=args.agent, stack=stack,
                            skill_limit=args.skill_limit)
    except BROKEN as exc:
        print(str(exc), file=sys.stderr)
        return 2
    result["decisions"] = svc.diag.as_list()
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render_plan(result, explain=args.explain))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m decision",
                                     description="The agent-dispatcher Decision Engine.")
    parser.add_argument("--project", help="project root (default: the working directory)")
    parser.add_argument("--mode", choices=config_mod.MODES,
                        help="override the configured mode for this call only")
    parser.add_argument("--provider", choices=sorted(config_mod.PROVIDERS),
                        help="override the provider for this call only")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="show the current decision configuration").set_defaults(
        func=cmd_status)

    m = sub.add_parser("mode", help="write the mode into the project config file")
    m.add_argument("value", choices=config_mod.MODES)
    m.set_defaults(func=cmd_mode)

    p = sub.add_parser("plan", help="decide agent, skills and tools for one task")
    p.add_argument("--task", required=True)
    p.add_argument("--agent", help="a role the user already named; skips agent selection")
    p.add_argument("--stack", help="comma-separated detected technologies")
    p.add_argument("--skill-limit", type=int, default=5)
    p.add_argument("--json", action="store_true")
    p.add_argument("--explain", action="store_true", help="show every candidate's score")
    p.set_defaults(func=cmd_plan)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
