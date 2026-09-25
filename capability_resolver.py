#!/usr/bin/env python3
"""Capability Intelligence, routing half: a task-scoped, health-aware capability plan over the role's existing loadout.

Hot path: one catalog read, one read-only snapshot read from the private capability store, no refresh, no probe, no
network, no process and no model call. The role stays the role: a database task keeps the Database Engineer when the
preferred connector is down; only the capability bindings, fallbacks and their stated limits change.

Order of operations, which is also the order of authority:
    1. deterministic eligibility gates (policy, disabled preferences, quarantine, compatibility, fresh failures)
    2. operation requirements and semantically equivalent fallbacks (operation, environment, resource, access,
       identity boundary, sensitivity) or an explicit no-connection route with its coverage limit
    3. the rollout mode: `off` keeps the incumbent route, `shadow` reports proposed changes without applying them,
       `on` applies them. Policy restrictions apply in every mode.
Nothing in a plan grants a permission. The host rechecks authorization when an operation actually runs, and mandatory
verification gates are carried through unchanged.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time

PLAN_SCHEMA = 1
WRITE_WORDS = re.compile(r"\b(?:migrat\w*|delete|drop|insert|update|alter|deploy|write|modify|truncate|backfill|rotate|provision)\b", re.I)
ENVIRONMENTS = (("production", re.compile(r"\b(?:production|prod|live)\b", re.I)), ("staging", re.compile(r"\bstaging\b", re.I)),
                ("development", re.compile(r"\b(?:local|dev|development)\b", re.I)))
DOMAINS = {"database": re.compile(r"\b(?:database|db|sql|postgres\w*|mysql|table|schema|query|queries|rows?)\b", re.I),
           "repository": re.compile(r"\b(?:pull request|pr|issue|github|ci run|workflow run)\b", re.I),
           "logs": re.compile(r"\b(?:logs?|traces?|errors? rate|sentry|incident)\b", re.I),
           "design": re.compile(r"\b(?:figma|design file|mockup)\b", re.I)}
OPERATION_FIELDS = ("name", "access", "environment", "resource", "identity", "sensitivity")


class ResolverError(ValueError):
    """Bounded diagnostic."""


_SIBLINGS = {}


def _sibling(name):
    if name not in _SIBLINGS:
        path = Path(__file__).resolve().with_name(name + ".py")
        namespace = {"__name__": "_dispatcher_resolver_" + name, "__file__": str(path)}
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
        _SIBLINGS[name] = namespace
    return _SIBLINGS[name]


def _catalog(pack):
    pack = Path(pack)
    for base in (pack / "catalog", pack / "scripts/runtime/catalog", pack.parent.parent / "catalog"):
        if (base / "loadouts.json").is_file():
            return base
    raise ResolverError("Catalog metadata not found beside the pack.")


def _read(path):
    with open(path, "rb") as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ResolverError("Catalog file too large.")
    return json.loads(raw)


def load_snapshot(host, config_dir=None, *, session=None, settings=None, catalog_fingerprint=None):
    """Latest complete snapshot, read-only; None when absent. Cross-session live health is demoted to historical, never current."""
    health = _sibling("capability_health")
    directory = health["host_directory"](host, config_dir)
    if not health["store_exists"](directory):
        return None, ["no capability snapshot for this host; health unknown and no refresh was launched"]
    try:
        with health["open_store"](directory, readonly=True) as store:
            snapshot = store.latest_snapshot()
    except health["CapabilityError"] as exc:
        return None, ["capability snapshot unavailable (" + str(exc)[:120] + "); guidance-only routing continues"]
    if snapshot is None:
        return None, ["capability store holds no complete snapshot"]
    notes = []
    if catalog_fingerprint and snapshot["fingerprints"].get("catalog") != catalog_fingerprint:
        notes.append("snapshot predates the installed catalog; its health is treated as unknown")
        return None, notes
    now = int(time.time())
    if snapshot["created"] > now + health["CLOCK_SKEW"]:
        return None, ["snapshot timestamp is in the future (clock anomaly); ignored"]
    if session is None or snapshot.get("session") != session:
        notes.append("snapshot is from another session: live observations are historical, not current connectivity")
        for row in snapshot["instances"]:
            if row["kind"] in ("mcp_server", "mcp_tool", "api", "plugin") and row["display"] in ("HEALTHY", "DEGRADED"):
                row["display"], row["qualifier"] = "UNTESTED", "historical success in another session; current connection untested"
                row["operation_status"] = {op: dict(v, historical=True) for op, v in row.get("operation_status", {}).items()}
    snapshot["_age_seconds"] = max(0, now - snapshot["created"])
    return snapshot, notes


def infer_operations(task, role_id):
    """Heuristic operation requirements (labelled as such): domain, access and target environment named by the task."""
    out = []
    for domain, pattern in DOMAINS.items():
        if not pattern.search(task) and not (domain == "database" and role_id == "database-engineer"):
            continue
        environment = next((name for name, pattern in ENVIRONMENTS if pattern.search(task)), "unknown")
        out.append({"name": domain + "." + ("write" if WRITE_WORDS.search(task) else "read"), "access": "write" if WRITE_WORDS.search(task) else "read",
                    "environment": environment, "resource": None, "identity": None, "sensitivity": "confidential" if environment == "production" else "unknown",
                    "source": "heuristic"})
    return out


def parse_operation(text):
    """name[:access[:environment[:resource]]] from the command line."""
    parts = text.split(":")
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,60}", parts[0]):
        raise ResolverError("Operation names are short lowercase identifiers.")
    op = {"name": parts[0], "access": parts[1] if len(parts) > 1 else ("write" if parts[0].endswith(".write") else "read"),
          "environment": parts[2] if len(parts) > 2 else "unknown", "resource": parts[3] if len(parts) > 3 else None, "identity": None,
          "sensitivity": "confidential" if len(parts) > 2 and parts[2] == "production" else "unknown", "source": "explicit"}
    if op["access"] not in ("read", "write") or op["environment"] not in ("production", "staging", "development", "local", "unknown"):
        raise ResolverError("Operation access must be read|write and environment production|staging|development|local|unknown.")
    return op


def _domain(name):
    return name.split(".")[0]


def serves(descriptor, required):
    """True only when a descriptor offers the same operation on the same established target: same domain and access, the
    same known environment, the same resource when one is required. Unknown environment never matches a named one."""
    if _domain(descriptor.get("name", "")) != _domain(required["name"]):
        return False
    if descriptor.get("access") != required["access"]:
        return False
    if required["environment"] != "unknown" and descriptor.get("environment") != required["environment"]:
        return False
    if required.get("resource") and descriptor.get("resource") != required["resource"]:
        return False
    return True


def equivalent(candidate, preferred, required):
    """Fallback equivalence: operation, environment, resource, access, identity boundary and sensitivity all match."""
    if not serves(candidate, required):
        return False, "different operation, access or target environment"
    if preferred is not None:
        if preferred.get("resource") and candidate.get("resource") != preferred["resource"]:
            return False, "different resource scope"
        if preferred.get("identity") and candidate.get("identity") != preferred["identity"]:
            return False, "different authentication identity boundary"
        if preferred.get("sensitivity", "unknown") != "unknown" and candidate.get("sensitivity") != preferred["sensitivity"]:
            return False, "different data sensitivity classification"
    if candidate.get("environment") == "unknown":
        return False, "target environment not established"
    return True, "same operation, target, access, identity boundary and sensitivity"


def _plain(ident):
    return ident.split(":", 1)[1] if ":" in ident else ident


def _definition_id(plain, known):
    for prefix in ("skill:", "external:", "mcp:", "native:"):
        if prefix + plain in known:
            return prefix + plain
    return None


def resolve(task, *, pack, role=None, snapshot=None, settings=None, operations=None, snapshot_notes=(), utility=None, conditions=None):
    """The structured capability plan for one task (see module docstring)."""
    health = _sibling("capability_health")
    settings = settings or health["DEFAULT_SETTINGS"]
    catalog = _catalog(pack)
    roles = {r["id"]: r for r in _read(catalog / "loadouts.json")["roles"]}
    if role is not None and role not in roles:
        matches = [r for r in roles.values() if role in (r.get("slug"), r.get("name"))]
        if len(matches) != 1:
            raise ResolverError("Role was not found unambiguously.")
        role = matches[0]["id"]
    record = roles.get(role) or {"id": None, "skills": {}, "mcps": {}, "verification": []}
    skills_json = _read(catalog / "skills.json")
    external = {e["id"] for e in _read(catalog / "external-skills.json")["skills"]}
    servers = {s["id"]: s for s in _read(catalog / "mcp.json")["servers"]}
    known = {"skill:" + s["id"] for s in skills_json["skills"]} | {"external:" + e for e in external} | \
            {("native:" if s == "workspace" else "mcp:") + s for s in servers}
    tiers = record.get("skills", {})
    lower = task.lower()
    active_conditions = set(conditions or [])
    for key in tiers.get("conditional", {}):
        words = key.replace("_", " ")
        if words in lower or all(w in lower for w in key.split("_")):
            active_conditions.add(key)
    incumbent = []
    for tier in ("core", "preferred"):
        incumbent += [(n, tier) for n in tiers.get(tier, [])]
    for key in sorted(active_conditions):
        incumbent += [(n, "conditional:" + key) for n in tiers.get("conditional", {}).get(key, [])]
    incumbent += [(n, "mcp_recommended") for n in record.get("mcps", {}).get("recommended", [])]
    checks = list(record.get("verification", []))
    rows = {r["definition_id"]: [] for r in (snapshot or {}).get("instances", [])}
    for row in (snapshot or {}).get("instances", []):
        rows[row["definition_id"]].append(row)
    disabled = set(settings.get("disabled", []))
    required_ops = [dict(o) for o in (operations if operations is not None else infer_operations(task, record.get("id")))]
    plan = {"schema_version": PLAN_SCHEMA, "role": record.get("id"), "mode": {"health_routing": settings["health_routing"], "utility_ranking": settings["utility_ranking"]},
            "snapshot": {"available": snapshot is not None, "age_seconds": (snapshot or {}).get("_age_seconds"), "notes": list(snapshot_notes)},
            "incumbent": [n for n, _ in incumbent], "selected": [], "operations": [], "alternatives_considered": [], "rejected": [], "deferred": [],
            "unknowns": [], "missing_prerequisites": [], "proposed_changes": [], "applied": False,
            "gates": {"authorization": "The host rechecks authorization for every operation at execution time; this plan grants nothing.",
                      "verification": checks, "verification_blockers": []},
            "recommendation_provenance": "heuristic", "evidence": []}

    def best_instance(definition):
        members = rows.get(definition) or []
        ranked = sorted(members, key=lambda r: (not r["eligible"], ["HEALTHY", "DEGRADED", "UNTESTED", "AUTH_REQUIRED", "UNAVAILABLE", "MISCONFIGURED"].index(r["display"])))
        return ranked[0] if ranked else None

    selected = []
    for name, tier in incumbent:
        definition = _definition_id(name, known)
        entry = {"capability": name, "tier": tier, "definition_id": definition}
        if definition is None:
            plan["rejected"].append(dict(entry, reason="MISSING_REFERENCE: not a registered capability"))
            continue
        if name in disabled or definition in disabled:
            plan["rejected"].append(dict(entry, reason="POLICY_DISABLED: disabled by the user's settings; applies in every mode"))
            continue
        inst = best_instance(definition)
        if inst is None:
            if definition.startswith("external:"):
                plan["deferred"].append(dict(entry, reason="external skill not observed as installed; its catalog fallback applies"))
                continue
            status, reason = (("unknown", "not observed in the host snapshot; health unknown") if definition.startswith("mcp:") else
                              ("guidance", "host-native file and terminal access, governed by the host's permission mode") if definition.startswith("native:") else
                              ("guidance", "bundled guidance"))
            plan["unknowns" if status == "unknown" else "selected"].append(dict(entry, instance_id=None, display="UNTESTED" if status == "unknown" else None, note=reason))
            if status != "unknown":
                selected.append(name)
            continue
        entry.update(instance_id=inst["instance_id"], display=inst["display"], qualifier=inst["qualifier"])
        if inst["policy"] != "enabled":
            plan["rejected"].append(dict(entry, reason="POLICY_" + inst["policy"].upper() + ": ineligible regardless of health, popularity or history"))
            continue
        if inst["display"] == "MISCONFIGURED":
            change = dict(entry, reason="MISCONFIGURED: configuration or compatibility error established")
            (plan["rejected"] if settings["health_routing"] == "on" else plan["proposed_changes"]).append(change)
            if settings["health_routing"] != "on":
                selected.append(name)
                plan["selected"].append(entry)
            continue
        if inst["display"] in ("UNTESTED", "AUTH_REQUIRED") and inst["kind"] in ("mcp_server", "api"):
            plan["unknowns"].append(dict(entry, note="conditional: " + inst["qualifier"] + "; handle the actual result"))
        selected.append(name)
        plan["selected"].append(entry)
        plan["evidence"].append({"instance_id": inst["instance_id"], "display": inst["display"], "reasons": inst.get("reasons", [])[:4]})
    # Operations: binding, equivalent fallback, or an explicit no-connection route.
    order = ["HEALTHY", "DEGRADED", "UNTESTED", "AUTH_REQUIRED", "UNAVAILABLE", "MISCONFIGURED"]
    for op in required_ops:
        binding, failed, usable = None, [], []
        for members in rows.values():
            for inst in members:
                for desc in inst.get("operations", []):
                    if _domain(desc.get("name", "")) != _domain(op["name"]) or desc.get("access") != op["access"]:
                        continue
                    plan["alternatives_considered"].append({"instance_id": inst["instance_id"], "name": inst["name"], "operation": desc["name"],
                                                            "environment": desc.get("environment"), "display": inst["display"]})
                    if not serves(desc, op):
                        plan["rejected"].append({"capability": inst["name"], "instance_id": inst["instance_id"], "reason": "not an equivalent fallback: "
                                                 + ("target environment not established" if desc.get("environment") in (None, "unknown") else "different target or resource")})
                        continue
                    status = (inst.get("operation_status") or {}).get(desc["name"]) or {}
                    if inst["policy"] != "enabled" or _plain(inst["definition_id"]) in disabled:
                        failed.append((inst, desc, "POLICY_" + inst["policy"].upper()))
                    elif (status.get("outcome") == "failure" and not status.get("historical")) or inst["display"] in ("UNAVAILABLE", "AUTH_REQUIRED", "MISCONFIGURED"):
                        failed.append((inst, desc, status.get("reason") or inst["display"]))
                    else:
                        usable.append((inst, desc))
        preferred = failed[0][1] if failed else None
        for inst, desc in sorted(usable, key=lambda pair: (order.index(pair[0]["display"]), pair[0]["instance_id"])):
            ok, why = equivalent(desc, preferred, op) if preferred is not None else (True, "preferred binding")
            if not ok:
                plan["rejected"].append({"capability": inst["name"], "instance_id": inst["instance_id"], "reason": "not an equivalent fallback: " + why})
                continue
            binding = (inst, desc, why)
            break
        item = {"operation": op, "binding": None, "status": None, "limits": [], "failed_preferred": [
            {"instance_id": i["instance_id"], "name": i["name"], "reason": r} for i, _, r in failed]}
        if binding is not None:
            inst, desc, why = binding
            item.update(binding=inst["instance_id"], status="ready" if inst["display"] == "HEALTHY" else "conditional",
                        via="fallback" if failed else "preferred", equivalence=why)
            if inst["display"] != "HEALTHY":
                item["limits"].append("connection untested for this operation; handle the actual result")
            if failed:
                item["limits"].append("preferred binding failed; the fallback covers the same operation and target")
        else:
            item.update(status="no_connection_route", binding="native:workspace",
                        limits=[f"{op['environment'] if op['environment'] != 'unknown' else 'target'} state remains unverified: "
                                "conclusions come from source, configuration and supplied material only",
                                "do not claim the target was inspected; a local CLI or saved credential is not established access"])
            plan["missing_prerequisites"].append({"operation": op["name"], "environment": op["environment"],
                                                  "next_step": "an authorized connection to the named target, established by the host"})
        if op["access"] == "write":
            item["limits"].append("mutating operation: normal authorization and the role's verification gates apply unchanged")
        plan["operations"].append(item)
    # Mandatory verification: carried through; a missing verification capability stays an explicit blocker.
    for check in checks:
        definition = _definition_id(check, known)
        inst = best_instance(definition) if definition else None
        if definition is None or check in disabled or (inst is not None and inst["policy"] != "enabled"):
            plan["gates"]["verification_blockers"].append({"check": check, "reason": "verification capability unavailable or disabled; completion cannot be claimed without it"})
    # Utility ranking: evaluated evidence only changes order, never eligibility, and only in `on` mode.
    if utility:
        plan["recommendation_provenance"] = "evaluated" if any(u.get("category") == "confirmed_within_scope" for u in utility.values()) else "observed"
        plan["utility"] = {k: {"category": v.get("category"), "scope": v.get("scope")} for k, v in utility.items()}
    # Rollout: shadow reports health-based changes without applying them.
    health_changes = [r for r in plan["rejected"] if not r["reason"].startswith(("POLICY_", "MISSING_REFERENCE"))]
    fallback_changes = [o for o in plan["operations"] if o.get("via") == "fallback" or o["status"] == "no_connection_route"]
    if settings["health_routing"] == "off":
        plan["operations"] = [dict(o, applied=False) for o in plan["operations"]]
        plan["proposed_changes"] = []
        plan["note"] = "health routing off: incumbent route; policy restrictions still enforced"
    elif settings["health_routing"] == "shadow":
        plan["proposed_changes"] += health_changes + [{"operation": o["operation"]["name"], "proposal": o["status"], "binding": o["binding"]} for o in fallback_changes]
        plan["note"] = "shadow: proposed changes recorded, incumbent route unchanged"
    else:
        plan["applied"] = True
    plan["selected_ids"] = sorted(set(selected))
    return plan


def compact(plan):
    """What the context inspector shows: a few lines, never the inventory. Details belong to `explain`."""
    return {"mode": plan["mode"], "snapshot": plan["snapshot"]["available"], "selected": len(plan["selected"]),
            "rejected": [{"capability": r["capability"], "reason": r["reason"].split(":")[0]} for r in plan["rejected"]][:6],
            "operations": [{"operation": o["operation"]["name"], "status": o["status"], "limits": o["limits"][:1]} for o in plan["operations"]][:4],
            "verification_blockers": [b["check"] for b in plan["gates"]["verification_blockers"]],
            "proposed_changes": len(plan["proposed_changes"]), "provenance": plan["recommendation_provenance"],
            "explain": "capability_resolver.py resolve --task ... --json"}


def ineligible(settings, snapshot=None):
    """Plain capability ids that no decision provider may reintroduce: disabled or policy-restricted in the current settings/snapshot."""
    out = set(settings.get("disabled", []))
    for row in (snapshot or {}).get("instances", []):
        if row["policy"] != "enabled":
            out.add(_plain(row["definition_id"]))
    return frozenset(out)


def context_layer(project, pack, task, role_id):
    """For context.py: None unless the user has a capability settings file (baseline packets stay byte-identical)."""
    health = _sibling("capability_health")
    location = health["settings_path"]()
    if not location.exists():
        return None
    settings = health["load_settings"](project=project)
    host = os.environ.get("AGENT_DISPATCHER_HOST")
    snapshot, notes = (load_snapshot(host, os.environ.get("AGENT_DISPATCHER_CONFIG_DIR"), session=os.environ.get("AGENT_DISPATCHER_SESSION"),
                                     settings=settings, catalog_fingerprint=health["catalog_digest"](pack))
                       if host in ("claude", "codex") else (None, ["host not identified (AGENT_DISPATCHER_HOST); health unknown"]))
    return compact(resolve(task, pack=pack, role=role_id, snapshot=snapshot, settings=settings, snapshot_notes=notes))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("resolve", "explain"))
    parser.add_argument("--task", required=True)
    parser.add_argument("--role")
    parser.add_argument("--operation", action="append", default=None, help="name[:read|write[:environment[:resource]]]; repeatable")
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--host", choices=("claude", "codex"))
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--session")
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        health = _sibling("capability_health")
        pack, _ = health["find_pack"](args.pack)
        settings = health["load_settings"](args.settings, project=args.project)
        snapshot, notes = load_snapshot(args.host, args.config_dir, session=args.session or os.environ.get("AGENT_DISPATCHER_SESSION"), settings=settings,
                                        catalog_fingerprint=health["catalog_digest"](pack)) if args.host else (None, ["no host selected; health unknown"])
        operations = [parse_operation(o) for o in args.operation] if args.operation else None
        plan = resolve(args.task[:4000], pack=pack, role=args.role, snapshot=snapshot, settings=settings, operations=operations, snapshot_notes=notes)
    except (ResolverError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"error": str(exc)[:300] if isinstance(exc, (ResolverError,)) or type(exc).__name__ in ("CapabilityError", "DoctorError")
                          else "Capability resolution failed: " + type(exc).__name__}), file=sys.stderr)
        return 2
    out = plan if args.command == "explain" or args.json else compact(plan)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
