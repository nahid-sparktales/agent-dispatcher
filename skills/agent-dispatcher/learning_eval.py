"""Procedural learning evaluation: three different questions, kept apart in code and in reports.

    Tier A  structural and security validity      learning_compose.validate_candidate (well-formed, not beneficial)
    Tier B  deterministic component evaluations   component_checks: applicability fixtures, composition invariants,
                                                  recipe gates, budget compliance, profile bounds, static latency
    Tier C  controlled agent evaluations          evaluate_candidate: paired outcomes of incumbent versus candidate on
                                                  matched tasks under a frozen specification and a registered runner

Only Tier C evidence from an authoritative runner, plus the other gates, can support the claim that a candidate
improves task completion or cost per success. The `fake_test_runner` exercises state transitions and is labeled
test-only: its reports are never authoritative and no flag makes them so. Missing model access is `not_run`.

Statistics are standard library only: family-level paired bootstrap for the success-rate difference, an exact sign
test and a Wald interval on discordant families, a percentile bootstrap for paired resource deltas, and a
family-block bootstrap for cross-repository claims. Conservative and documented, not powerful; a degenerate interval
(no discordant pairs, tiny samples) is `inconclusive`, never proof of zero risk.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import random
import statistics
import time

SCHEMA = 1
STATUSES = ("passed", "failed", "inconclusive", "invalid", "not_run")
OBJECTIVES = ("correctness", "efficiency")
RUNNERS = {
    "fake_test_runner": {"authoritative": False, "tier": "C", "label": "test_only", "version": 1,
                         "note": "Consumes supplied paired outcomes to test lifecycle transitions; can never support a production approval."},
    "end_to_end_batch": {"authoritative": True, "tier": "C", "label": "native_client_batch", "version": 1,
                         "note": "Pairs completed trials of an evals/end_to_end batch whose configuration fingerprint the frozen spec names."},
}
DATA_ROLES = ("discovery", "development", "admission_holdout", "final_test")


class EvaluationError(ValueError):
    """Bounded diagnostic; never echoes task text or hidden grader material."""


_SIBLINGS = {}


def _sibling(name):
    if name not in _SIBLINGS:
        path = Path(__file__).resolve().with_name(name + ".py")
        namespace = {"__name__": "_dispatcher_eval_" + name, "__file__": str(path)}
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
        _SIBLINGS[name] = namespace
    return _SIBLINGS[name]


def _digest(value):
    return _sibling("learning_compose")["digest"](value)


def _now():
    return int(time.time())


# ---------------------------------------------------------------- statistics


def z_value(confidence):
    """Two-sided normal quantile by bisection on math.erf; no numerical stack."""
    if not 0.5 < confidence < 1:
        raise EvaluationError("confidence must be between 0.5 and 1.")
    target = confidence
    low, high = 0.0, 10.0
    for _ in range(200):
        middle = (low + high) / 2
        if math.erf(middle / math.sqrt(2)) < target:
            low = middle
        else:
            high = middle
    return round((low + high) / 2, 6)


def percentile(values, share):
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, math.ceil(share * len(ordered)) - 1))
    return ordered[index]


def family_pairs(rows):
    """Collapse repetitions: one pair per task family, each arm's success rate over its repetitions; repetitions are variability, not coverage."""
    families = {}
    for row in rows:
        entry = families.setdefault(row["family"], {"family": row["family"], "block": row.get("block"), "candidate": [], "incumbent": [],
                                                     "candidate_cost": [], "incumbent_cost": []})
        entry["candidate"].append(bool(row["candidate"]))
        entry["incumbent"].append(bool(row["incumbent"]))
        for side in ("candidate", "incumbent"):
            cost = row.get(side + "_cost")
            if isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost):
                entry[side + "_cost"].append(float(cost))
    out = []
    for entry in families.values():
        out.append({"family": entry["family"], "block": entry["block"], "candidate_rate": statistics.fmean(entry["candidate"]),
                    "incumbent_rate": statistics.fmean(entry["incumbent"]), "repetitions": len(entry["candidate"]),
                    "candidate_cost": statistics.fmean(entry["candidate_cost"]) if entry["candidate_cost"] else None,
                    "incumbent_cost": statistics.fmean(entry["incumbent_cost"]) if entry["incumbent_cost"] else None})
    return out


def paired_success(pairs, confidence=0.95, rounds=2000, seed=0):
    """Family-level paired difference of success rates with a percentile bootstrap interval, plus exact sign test on discordant families."""
    n = len(pairs)
    if n == 0:
        return {"n": 0, "difference": None, "low": None, "high": None, "discordant": 0, "b": 0, "c": 0, "sign_p": None, "degenerate": True,
                "method": "family-level paired bootstrap of success-rate difference; exact sign test on discordant families"}
    deltas = [p["candidate_rate"] - p["incumbent_rate"] for p in pairs]
    b = sum(1 for d in deltas if d > 0)
    c = sum(1 for d in deltas if d < 0)
    rng, means = random.Random(seed), []
    for _ in range(rounds):
        sample = [deltas[rng.randrange(n)] for _ in range(n)]
        means.append(statistics.fmean(sample))
    alpha = (1 - confidence) / 2
    low, high = percentile(means, alpha), percentile(means, 1 - alpha)
    discordant = b + c
    sign_p = None
    if discordant:
        smaller = min(b, c)
        tail = sum(math.comb(discordant, k) for k in range(smaller + 1)) / 2 ** discordant
        sign_p = min(1.0, 2 * tail)
    wald = None
    if discordant:
        d = (b - c) / n
        se = math.sqrt(max(0.0, (b + c) - (b - c) ** 2 / n)) / n
        z = z_value(confidence)
        wald = {"difference": d, "low": d - z * se, "high": d + z * se}
    return {"n": n, "difference": statistics.fmean(deltas), "low": low, "high": high, "discordant": discordant, "b": b, "c": c, "sign_p": sign_p,
            "wald_discordant": wald, "degenerate": discordant == 0 or n < 5, "confidence": confidence, "rounds": rounds,
            "method": "family-level paired bootstrap of success-rate difference; exact sign test and Wald interval on discordant families"}


def paired_delta(values, confidence=0.95, rounds=2000, seed=0):
    """Percentile bootstrap of the mean paired resource delta (candidate minus incumbent); missing values are excluded and counted."""
    known = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)]
    missing = len(values) - len(known)
    if not known:
        return {"n": 0, "missing": missing, "mean": None, "low": None, "high": None, "degenerate": True}
    rng, means = random.Random(seed), []
    for _ in range(rounds):
        means.append(statistics.fmean(known[rng.randrange(len(known))] for _ in known))
    alpha = (1 - confidence) / 2
    return {"n": len(known), "missing": missing, "mean": statistics.fmean(known), "low": percentile(means, alpha), "high": percentile(means, 1 - alpha),
            "degenerate": len(known) < 5 or len(set(known)) == 1, "method": "percentile bootstrap of the mean paired delta"}


def block_bootstrap(pairs, key="block", confidence=0.95, rounds=2000, seed=0):
    """Resample blocks (repository families or chronological blocks) so correlated tasks do not pose as independent."""
    groups = {}
    for pair in pairs:
        groups.setdefault(pair.get(key), []).append(pair["candidate_rate"] - pair["incumbent_rate"])
    names = sorted(groups, key=str)
    if len(names) < 2:
        return {"blocks": len(names), "low": None, "high": None, "degenerate": True, "method": f"{key}-block bootstrap (needs 2+ blocks)"}
    rng, means = random.Random(seed), []
    for _ in range(rounds):
        sample = [d for _ in names for d in groups[rng.choice(names)]]
        means.append(statistics.fmean(sample))
    alpha = (1 - confidence) / 2
    return {"blocks": len(names), "low": percentile(means, alpha), "high": percentile(means, 1 - alpha), "degenerate": len(names) < 3,
            "method": f"{key}-block bootstrap of the paired success-rate difference"}


def retrieval_metrics(found, gold, k):
    """Recall@k, Hit@k and All-targets@k for one task; empty or unknown gold is undefined, never a perfect score."""
    if gold is None:
        return {"recall": None, "hit": None, "all": None, "defined": False, "reason": "gold targets unavailable"}
    targets = set(gold)
    if not targets:
        return {"recall": None, "hit": None, "all": None, "defined": False, "reason": "empty gold set"}
    top = set(list(found)[:k])
    overlap = targets & top
    return {"recall": len(overlap) / len(targets), "hit": 1.0 if overlap else 0.0, "all": 1.0 if targets <= top else 0.0, "defined": True}


def aggregate_retrieval(rows):
    """Macro (mean over tasks) and micro (pooled targets) averages, labeled; undefined rows are excluded and counted."""
    defined = [r for r in rows if r.get("defined")]
    if not defined:
        return {"tasks": len(rows), "defined": 0, "macro": None, "micro": None}
    return {"tasks": len(rows), "defined": len(defined),
            "macro": {name: statistics.fmean(r[name] for r in defined) for name in ("recall", "hit", "all")},
            "micro": {"recall": sum(r["recall"] * r["gold_size"] for r in defined if "gold_size" in r) / sum(r["gold_size"] for r in defined if "gold_size" in r)
                      if all("gold_size" in r for r in defined) and sum(r["gold_size"] for r in defined) else None},
            "note": "macro averages tasks equally; micro pools targets and needs gold_size per row"}


# ---------------------------------------------------------------- specification and verdicts


def freeze_spec(document, *, candidate_revision_id, incumbent_generation_id, candidate_bundle_digest, incumbent_bundle_digest, policy_digest, package_digest, settings):
    """Bind a supplied evaluation specification to exact digests before anything runs; the frozen spec is content-addressed."""
    if not isinstance(document, dict):
        raise EvaluationError("Specification must be a JSON object.")
    allowed = {"schema_version", "objective", "endpoint", "practical_threshold", "noninferiority_margin", "min_paired_families", "min_blocks",
               "max_infrastructure_share", "runner", "environment", "data", "arms", "stopping_rule", "safety_gates", "protected_files", "evaluator_digest", "note"}
    unknown = set(document) - allowed
    if unknown:
        raise EvaluationError("Specification carries an unknown field.")
    if document.get("schema_version") != SCHEMA:
        raise EvaluationError("Unsupported specification schema version.")
    objective = document.get("objective", "correctness")
    if objective not in OBJECTIVES:
        raise EvaluationError("objective must be correctness or efficiency.")
    runner = document.get("runner")
    if runner not in RUNNERS:
        raise EvaluationError("Specification names an unregistered runner.")
    threshold = document.get("practical_threshold", settings["evaluation"]["practical_threshold"])
    margin = document.get("noninferiority_margin", settings["evaluation"]["noninferiority_margin"])
    for name, value in (("practical_threshold", threshold),):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < 1:
            raise EvaluationError(f"{name} must be a number in (0, 1).")
    if objective == "efficiency":
        if margin is None or isinstance(margin, bool) or not isinstance(margin, (int, float)) or not 0 <= margin <= 0.5:
            raise EvaluationError("An efficiency objective needs an explicit noninferiority_margin chosen by the owner; correctness is never traded silently.")
    environment = document.get("environment") or {}
    if not isinstance(environment, dict):
        raise EvaluationError("environment must be an object.")
    for key in ("model", "effort", "auth_mode", "cli_version", "seed"):
        if key not in environment:
            raise EvaluationError(f"environment.{key} must be fixed before evaluation (use null only when the runner is not_run).")
    data = document.get("data") or {}
    if not isinstance(data, dict) or set(data) - set(DATA_ROLES):
        raise EvaluationError("data must map discovery, development, admission_holdout and final_test roles to family lists or manifest digests.")
    roles = {}
    for role in DATA_ROLES:
        value = data.get(role) or {"families": [], "manifest_digest": None}
        if not isinstance(value, dict) or set(value) - {"families", "manifest_digest", "repository_families", "chronological_cutoff"}:
            raise EvaluationError(f"data.{role} must be {{families, manifest_digest, repository_families, chronological_cutoff}}.")
        families = value.get("families") or []
        if not isinstance(families, list) or len(families) > 5000 or any(not isinstance(f, str) or len(f) > 120 for f in families):
            raise EvaluationError(f"data.{role}.families must be a bounded list of family ids.")
        roles[role] = {"families": sorted(set(families)), "manifest_digest": value.get("manifest_digest"), "repository_families": sorted(set(value.get("repository_families") or [])),
                       "chronological_cutoff": value.get("chronological_cutoff")}
    for first in DATA_ROLES:
        for second in DATA_ROLES:
            if first < second and set(roles[first]["families"]) & set(roles[second]["families"]):
                raise EvaluationError(f"data roles {first} and {second} overlap; each family belongs to one role.")
    arms = document.get("arms") or {"candidate": "candidate", "incumbent": "incumbent"}
    if not isinstance(arms, dict) or set(arms) != {"candidate", "incumbent"} or any(not isinstance(v, str) for v in arms.values()):
        raise EvaluationError("arms must name a candidate and an incumbent condition.")
    spec = {"schema_version": SCHEMA, "objective": objective, "endpoint": document.get("endpoint", "task_success"),
            "practical_threshold": threshold, "noninferiority_margin": margin,
            "min_paired_families": document.get("min_paired_families", settings["evaluation"]["min_paired_families"]),
            "min_blocks": document.get("min_blocks", settings["evaluation"]["min_blocks"]),
            "max_infrastructure_share": document.get("max_infrastructure_share", 0.2), "runner": runner, "runner_version": RUNNERS[runner]["version"],
            "environment": environment, "data": roles, "arms": arms, "stopping_rule": document.get("stopping_rule", "fixed sample; no peeking"),
            "safety_gates": document.get("safety_gates", ["no safety violation", "no required-verification regression"]),
            "protected_files": document.get("protected_files") or [], "evaluator_digest": document.get("evaluator_digest"), "note": document.get("note"),
            "candidate_revision_id": candidate_revision_id, "incumbent_generation_id": incumbent_generation_id,
            "candidate_bundle_digest": candidate_bundle_digest, "incumbent_bundle_digest": incumbent_bundle_digest,
            "policy_digest": policy_digest, "package_digest": package_digest, "confidence": settings["evaluation"]["confidence"], "frozen": _now()}
    for key in ("min_paired_families", "min_blocks"):
        if type(spec[key]) is not int or spec[key] < 1:
            raise EvaluationError(f"{key} must be a positive integer.")
    spec["spec_id"] = _digest({k: v for k, v in spec.items() if k != "frozen"})
    return spec


def verdict(spec, outcomes):
    """passed | failed | inconclusive | invalid with machine-readable reasons. Minimum counts screen; intervals decide."""
    reasons = []
    pairs = outcomes["pairs"]
    success = outcomes["success"]
    attempts = outcomes["attempts"]
    if attempts and outcomes["infrastructure_errors"] / attempts > spec["max_infrastructure_share"]:
        return "invalid", ["infrastructure error share exceeds the specification's limit; results are not attributable to the candidate"]
    if outcomes.get("contamination"):
        return "invalid", ["final-test or admission-holdout families overlap the candidate's discovery evidence"]
    if outcomes["safety_violations"]:
        return "failed", ["safety gate: a safety violation was observed under the candidate"]
    if outcomes["verification_regressions"]:
        return "failed", ["safety gate: required verification regressed under the candidate"]
    if success["n"] == 0:
        return "not_run", ["no comparable paired outcomes"]
    if success["n"] < spec["min_paired_families"]:
        reasons.append(f"coverage: {success['n']} paired families < {spec['min_paired_families']} minimum")
    blocks = outcomes["blocks"]["blocks"]
    if blocks < spec["min_blocks"]:
        reasons.append(f"coverage: {blocks} blocks < {spec['min_blocks']} minimum")
    if success["degenerate"]:
        reasons.append("degenerate outcome distribution (no discordant families or very small sample); no interval is trusted")
    if reasons:
        return "inconclusive", reasons
    low, high = success["low"], success["high"]
    if spec["objective"] == "correctness":
        if low > spec["practical_threshold"]:
            return "passed", [f"lower {int(spec['confidence'] * 100)}% bound {low:+.3f} exceeds practical threshold {spec['practical_threshold']:.3f}"]
        if high < 0:
            return "failed", [f"upper bound {high:+.3f} is below zero: the candidate is worse"]
        return "inconclusive", [f"interval [{low:+.3f}, {high:+.3f}] does not clear the practical threshold {spec['practical_threshold']:.3f}"]
    margin = spec["noninferiority_margin"]
    cost = outcomes["cost_delta"]
    if low <= -margin:
        return "failed", [f"success lower bound {low:+.3f} breaches the non-inferiority margin -{margin:.3f}"]
    if cost["n"] == 0:
        return "inconclusive", ["no paired cost measurements; efficiency cannot be judged (unknown stays unknown)"]
    if cost["degenerate"]:
        return "inconclusive", ["cost deltas are too few or identical for an interval"]
    if cost["high"] < 0 and low > -margin:
        return "passed", [f"non-inferior (lower bound {low:+.3f} > -{margin:.3f}) and cost upper bound {cost['high']:+.3f} < 0 (margin {margin:.3f} reported)"]
    return "inconclusive", [f"non-inferiority margin {margin:.3f}: success bound {low:+.3f}; cost interval [{cost['low']:+.3f}, {cost['high']:+.3f}] does not show savings"]


def summarize(spec, rows, *, attempts, invalid_trials, infrastructure_errors, safety_violations=0, verification_regressions=0, contamination=()):
    pairs = family_pairs(rows)
    success = paired_success(pairs, spec["confidence"])
    cost = paired_delta([p["candidate_cost"] - p["incumbent_cost"] for p in pairs if p["candidate_cost"] is not None and p["incumbent_cost"] is not None]
                        + [None] * sum(1 for p in pairs if p["candidate_cost"] is None or p["incumbent_cost"] is None), spec["confidence"])
    blocks = block_bootstrap(pairs, "block", spec["confidence"])
    return {"pairs": pairs, "success": success, "cost_delta": cost, "blocks": blocks, "attempts": attempts, "invalid_trials": invalid_trials,
            "infrastructure_errors": infrastructure_errors, "safety_violations": safety_violations, "verification_regressions": verification_regressions,
            "contamination": sorted(contamination), "repetitions": sum(p["repetitions"] for p in pairs)}


def build_report(spec, runner, outcomes, *, costs=None, diagnostics=()):
    status, reasons = verdict(spec, outcomes)
    if runner == "fake_test_runner":
        reasons = ["test-only runner: report exercises the lifecycle and can never support a production approval"] + reasons
    report = {"schema_version": SCHEMA, "tier": "C", "spec_id": spec["spec_id"], "spec": spec, "candidate_revision_id": spec["candidate_revision_id"],
              "incumbent_generation_id": spec["incumbent_generation_id"], "candidate_bundle_digest": spec["candidate_bundle_digest"],
              "incumbent_bundle_digest": spec["incumbent_bundle_digest"], "policy_digest": spec["policy_digest"], "package_digest": spec["package_digest"],
              "evaluator": {"id": runner, **RUNNERS[runner]}, "environment": spec["environment"], "status": status, "reasons": reasons,
              "outcomes": {k: v for k, v in outcomes.items() if k != "pairs"}, "families": len(outcomes["pairs"]),
              "costs": costs or {"evaluation_cost_usd": None, "note": "unknown stays unknown"}, "diagnostics": list(diagnostics),
              "uncertainty": {"success": {k: outcomes["success"].get(k) for k in ("difference", "low", "high", "sign_p", "degenerate", "method", "confidence")},
                              "cost": {k: outcomes["cost_delta"].get(k) for k in ("mean", "low", "high", "degenerate", "missing")},
                              "blocks": outcomes["blocks"]},
              "created": _now()}
    report["evaluation_id"] = _digest({k: v for k, v in report.items() if k != "created"})
    return report


# ---------------------------------------------------------------- runners


def _pairs_from_fixture(document):
    if not isinstance(document, dict) or not isinstance(document.get("pairs"), list):
        raise EvaluationError("Fixture results must be {pairs: [...]} (test only).")
    rows = []
    for item in document["pairs"]:
        if not isinstance(item, dict) or not isinstance(item.get("family"), str) or type(item.get("candidate")) is not bool or type(item.get("incumbent")) is not bool:
            raise EvaluationError("Each fixture pair needs family, candidate and incumbent booleans.")
        rows.append({"family": item["family"], "block": item.get("block"), "candidate": item["candidate"], "incumbent": item["incumbent"],
                     "candidate_cost": item.get("candidate_cost"), "incumbent_cost": item.get("incumbent_cost")})
    return rows, {"attempts": int(document.get("attempts", 2 * len(rows))), "invalid": int(document.get("invalid_trials", 0)),
                  "infrastructure": int(document.get("infrastructure_errors", 0)), "safety": int(document.get("safety_violations", 0)),
                  "verification": int(document.get("verification_regressions", 0))}


def _pairs_from_batch(spec, batch_dir):
    """Completed trials of one evals/end_to_end batch, paired by fixture and repetition across the spec's two arms."""
    batch_dir = Path(batch_dir)
    batch = json.loads((batch_dir / "batch.json").read_text(encoding="utf-8"))
    results = json.loads((batch_dir / "results.json").read_text(encoding="utf-8"))
    fingerprint = batch.get("provenance", {}).get("config_fingerprint") or batch.get("config_fingerprint")
    expected = spec["environment"].get("batch_fingerprint")
    if expected is not None and fingerprint != expected:
        raise EvaluationError("Batch configuration fingerprint does not match the frozen specification; the runs are not the runs the spec froze.")
    trials = results.get("trials", [])
    candidate, incumbent = spec["arms"]["candidate"], spec["arms"]["incumbent"]
    pairs = {}
    invalid = infrastructure = 0
    for trial in trials:
        if trial.get("condition") not in (candidate, incumbent):
            continue
        status = trial.get("status")
        if status in ("invalid_configuration", "authentication_failure"):
            invalid += 1
            continue
        if status == "infrastructure_error":
            infrastructure += 1
            continue
        key = (trial.get("client"), trial.get("fixture_id"), trial.get("repetition"))
        pairs.setdefault(key, {})[trial["condition"]] = trial
    rows = []
    for (client, fixture, repetition), pair in sorted(pairs.items(), key=lambda kv: str(kv[0])):
        if candidate not in pair or incumbent not in pair:
            continue
        left, right = pair[candidate], pair[incumbent]
        if type(left.get("task_success")) is not bool or type(right.get("task_success")) is not bool:
            continue
        rows.append({"family": f"{client}:{fixture}", "block": left.get("category") or fixture, "candidate": left["task_success"], "incumbent": right["task_success"],
                     "candidate_cost": (left.get("usage") or {}).get("cost_usd"), "incumbent_cost": (right.get("usage") or {}).get("cost_usd")})
    return rows, {"attempts": len([t for t in trials if t.get("condition") in (candidate, incumbent)]), "invalid": invalid, "infrastructure": infrastructure,
                  "safety": 0, "verification": 0}, {"batch_fingerprint": fingerprint, "suite": batch.get("suite"), "seed": batch.get("seed")}


def evaluate_candidate(store, experience, revision_id, spec_document, settings, *, pack, runner=None, batch=None, fixture_results=None):
    """Freeze the spec against the current store, run the registered runner, store the report, move the lifecycle."""
    learning = _sibling("learning")
    revision = store.revision(revision_id)
    if revision is None:
        raise EvaluationError("Unknown candidate revision.")
    if revision["state"] not in ("validated", "experimental_canary", "evaluation_failed", "inconclusive", "evaluation_passed", "awaiting_approval", "expired"):
        raise EvaluationError(f"Candidate is {revision['state']}; it cannot be evaluated in this state.")
    if not _sibling("learning_compose")["revision_digest_matches"](revision):
        raise EvaluationError("Stored revision does not match its id.")
    runner = runner or (spec_document.get("runner") if isinstance(spec_document, dict) else None)
    if runner not in RUNNERS:
        raise EvaluationError("Unknown or unregistered runner; only registered evaluator paths produce promotion evidence.")
    spec_document = dict(spec_document, runner=runner)
    active = store.active_generation()
    incumbent_ids = list((active or {}).get("revision_ids", []))
    policy = learning["policy_digest"](settings)
    package = learning["package_digest"](pack)
    candidate_bundle = learning["bundle_digest"](store, pack, incumbent_ids + [revision_id], settings)
    incumbent_bundle = learning["bundle_digest"](store, pack, incumbent_ids, settings)
    try:
        spec = freeze_spec(spec_document, candidate_revision_id=revision_id, incumbent_generation_id=(active or {}).get("generation_id"),
                           candidate_bundle_digest=candidate_bundle, incumbent_bundle_digest=incumbent_bundle, policy_digest=policy, package_digest=package, settings=settings)
    except EvaluationError as exc:
        raise EvaluationError(str(exc)) from None
    # Discovery evidence may not reappear as admission or final-test material.
    discovery = set(revision.get("task_families") or [])
    contamination = discovery & (set(spec["data"]["final_test"]["families"]) | set(spec["data"]["admission_holdout"]["families"]))
    diagnostics, costs = [], {"evaluation_cost_usd": None, "note": "unknown stays unknown"}
    with store.transaction():
        if revision["state"] != "evaluating":
            store.transition(revision_id, "evaluating", f"evaluation {spec['spec_id'][:12]} started with runner {runner}")
    try:
        if runner == "fake_test_runner":
            if fixture_results is None:
                raise EvaluationError("fake_test_runner needs --fixture-results (test only).")
            document = fixture_results if isinstance(fixture_results, dict) else _sibling("learning_compose")["parse_document"](Path(fixture_results).read_bytes())
            rows, counts = _pairs_from_fixture(document)
            diagnostics.append("test-only runner; outcomes were supplied, not observed")
        else:
            if batch is None:
                rows, counts = [], {"attempts": 0, "invalid": 0, "infrastructure": 0, "safety": 0, "verification": 0}
                diagnostics.append("no batch supplied: the native-client evaluation was not run")
            else:
                rows, counts, provenance = _pairs_from_batch(spec, batch)
                spec["environment"] = dict(spec["environment"], batch=provenance)
        outcomes = summarize(spec, rows, attempts=counts["attempts"], invalid_trials=counts["invalid"], infrastructure_errors=counts["infrastructure"],
                             safety_violations=counts["safety"], verification_regressions=counts["verification"], contamination=contamination)
        report = build_report(spec, runner, outcomes, costs=costs, diagnostics=diagnostics)
    except (EvaluationError, OSError, ValueError, KeyError, TypeError) as exc:
        # Runner input that could not be used says nothing about the candidate: it stays re-evaluable, and the attempt is on record.
        with store.transaction():
            store.transition(revision_id, "inconclusive", "evaluation could not run: " + (str(exc) if isinstance(exc, EvaluationError) else type(exc).__name__)[:200])
        raise EvaluationError("Evaluation invalid: " + (str(exc) if isinstance(exc, EvaluationError) else "runner input could not be read.")) from None
    # An invalid or unrun *evaluation* leaves the candidate re-evaluable; the lifecycle's own `invalid` is reserved for a candidate
    # whose bytes or validation no longer hold.
    state = {"passed": "evaluation_passed", "failed": "evaluation_failed", "inconclusive": "inconclusive", "invalid": "inconclusive", "not_run": "inconclusive"}[report["status"]]
    with store.transaction():
        store.add_evaluation(report)
        store.transition(revision_id, state, f"evaluation {report['evaluation_id'][:12]}: {report['status']}", {"evaluation_id": report["evaluation_id"], "authoritative": report["evaluator"]["authoritative"]})
    return {k: v for k, v in report.items() if k != "spec"} | {"spec_id": spec["spec_id"], "lifecycle_state": state}


# ---------------------------------------------------------------- Tier B component checks


def component_checks(store, revision_id, settings, *, pack, extra_tasks=()):
    """Deterministic component evaluations: applicability fixtures, composition invariants, recipe gates, budget, profile bounds, static latency."""
    learning, compose, engine = _sibling("learning"), _sibling("learning_compose"), _sibling("retrieval")
    revision = store.revision(revision_id)
    if revision is None:
        raise EvaluationError("Unknown candidate revision.")
    checks, started = [], time.perf_counter()

    def check(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    catalog = learning["package_catalog"](pack)
    check("revision_digest", compose["revision_digest_matches"](revision), "stored bytes recompute to the revision id")
    check("policy_binding", revision["policy_digest"] == learning["policy_digest"](settings), "validated under the current learning policy")
    check("package_binding", revision["base_package_digest"] == learning["package_digest"](pack), "bound to the installed package")
    want = revision["applicability"]
    positive = " ".join(want["task_terms"][: max(1, want["min_term_matches"])] or ["placeholder"]) + " task"
    positive_query = engine["analyze_query"](positive)
    ok, _, _ = compose["applicable"](revision, role=(want["roles"] or [None])[0], recipes=want["recipes"], terms=set(positive_query["terms"]))
    check("applicability_positive", ok, "the overlay applies to a request carrying its own role/recipe/terms")
    unrelated = engine["analyze_query"]("rewrite the marketing landing page copy for the spring launch")
    role_other = "content-copywriter" if "content-copywriter" not in want["roles"] else "database-engineer"
    ok_unrelated, _, _ = compose["applicable"](revision, role=role_other, recipes=(), terms=set(unrelated["terms"]))
    check("applicability_negative", not ok_unrelated, "the overlay does not fire for an unrelated role and request")
    for task in extra_tasks:
        query = engine["analyze_query"](task["task"])
        ok_extra, why, _ = compose["applicable"](revision, role=task.get("role"), recipes=task.get("recipes", ()), terms=set(query["terms"]))
        check("applicability_fixture:" + task["id"], ok_extra == task["expected"], why)
    kind = revision["artifact_kind"]
    if kind in ("skill_overlay", "role_method_overlay", "recipe_overlay"):
        base = learning["base_body"](pack, kind, revision["artifact_id"])
        check("base_binding", base["sha256"] == revision["base_artifact_digest"], "base artifact unchanged since validation")
        workflow = compose["workflow_view"](catalog["workflows"][revision["artifact_id"]]) if kind == "recipe_overlay" and revision["artifact_id"] in catalog["workflows"] else None
        layer = learning["_layer"](revision)
        first = compose["compose"](kind, base["content"], [layer], workflow)
        second = compose["compose"](kind, base["content"], [layer], workflow)
        check("composition_deterministic", first == second and first["state"] == "active", first["reason"])
        check("base_preserved", compose["_strip_derived"](first["content"]) == base["content"], "removing the derived block restores the base bytes")
        added = compose["added_tokens"](base["content"], first["content"])
        check("budget_compliance", added <= settings["budget"]["max_added_tokens"], f"adds about {added} estimated tokens (limit {settings['budget']['max_added_tokens']})")
        if kind == "recipe_overlay" and workflow is not None:
            composed = compose["compose_workflow"](catalog["workflows"][revision["artifact_id"]], revision["typed_payload"]["insert"])
            base_ids = [s["id"] for s in catalog["workflows"][revision["artifact_id"]]["steps"]]
            kept = [s["id"] for s in composed["steps"] if not s.get("derived")]
            check("recipe_gates_preserved", kept == base_ids and composed["gates"] == catalog["workflows"][revision["artifact_id"]]["gates"], "base steps, order and gates unchanged; inserted steps are optional branches")
        if kind == "role_method_overlay":
            check("protected_role_sections", all(compose["_protected"](base["content"], name) == compose["_protected"](first["content"], name) for name in compose["PROTECTED_ROLE_SECTIONS"]),
                  "identity, deliverable, definition of done, boundaries and tool posture are byte-identical")
    elif kind == "retrieval_profile":
        profile, state = compose["effective_profile"]([revision], None)
        overrides = profile["overrides"] if profile else {}
        try:
            configured = engine["configure"](profile["strategy"] or "full", overrides)
            check("profile_configures", True, f"strategy {configured['name']} accepts the bounded overrides")
            check("profile_no_provider", not configured["llm_rerank"]["enabled"] and "role_summary" not in configured["retrievers"], "profile enables no model-assisted retriever")
        except (ValueError, KeyError, TypeError) as exc:
            check("profile_configures", False, type(exc).__name__)
    elif kind == "skill_selection":
        base = learning["base_body"](pack, kind, revision["artifact_id"])
        payload = revision["typed_payload"]
        check("catalog_binding", base["sha256"] == revision["base_artifact_digest"], "capability catalogs unchanged since validation")
        check("selection_pinned", bool(payload["content_digest"]) and payload["target_scope"] == revision["scope"],
              "the selection binds one exact package digest and its own scope")
    else:
        named = set(revision["typed_payload"].get("order_first", [])) | {c["check"] for c in revision["typed_payload"].get("add_checks", [])}
        check("hint_checks_registered", named <= catalog["checks"], "every named check is a registered verification capability; no command text")
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    check("static_latency", elapsed < 2000, f"component checks took {elapsed} ms")
    passed = all(c["passed"] for c in checks)
    report = {"schema_version": SCHEMA, "tier": "B", "candidate_revision_id": revision_id, "status": "passed" if passed else "failed", "checks": checks,
              "evaluator": {"id": "component_checks", "authoritative": False, "tier": "B", "label": "deterministic_component_checks", "version": 1},
              "incumbent_generation_id": (store.active_generation() or {}).get("generation_id"), "policy_digest": learning["policy_digest"](settings),
              "candidate_bundle_digest": None, "incumbent_bundle_digest": None, "package_digest": learning["package_digest"](pack),
              "reasons": ["component checks are filters: passing them establishes structure and budget, not benefit"], "created": _now(), "elapsed_ms": elapsed}
    report["evaluation_id"] = _digest({k: v for k, v in report.items() if k not in ("created", "elapsed_ms")})
    with store.transaction():
        store.add_evaluation(report)
    return report
