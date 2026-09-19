"""How the decision layer is configured, and where the credential is not.

Precedence, highest first:

    1. an explicit argument (a CLI flag, a per-task override)
    2. the environment
    3. the project's `.agent-dispatcher-decision.json`
    4. the defaults below

The credential is deliberately absent from this object. `Config` can say *whether* one is
configured and *which* variable would carry it; the value is read by the provider, at the
moment of the request, straight out of `os.environ`. Nothing that is rendered, logged,
serialised or handed to a model has ever held it.
"""
import json
import math
import os
import pathlib

MODES = ("off", "auto", "required")

# Every scope is OFF by default, and that is a finding rather than a fence-sit.
#
# The point of this package is that each decision can use whichever mechanism the evidence
# supports. `evals/decision` put three engines on identical fixtures — a keyword baseline, Jev,
# and Claude reading the dispatcher's own catalog and rules — and Claude matched or beat Jev
# everywhere:
#
#   agent routing      claude 158/162 top-1, 162/162 acceptable · jev 143/162, 154/162
#   skill selection    claude 0.74/0.90 precision/recall        · jev 0.68/0.71
#   tool relevance     claude 0.69/0.95                          · jev 0.65/0.97  (a tie)
#
# Both crush the loadout-and-keyword floor (0.31/0.56 and 0.15/0.23), which is what the first
# cut of these defaults was set against — the wrong comparison. Against the path that actually
# ships, Jev wins nothing on quality, and in production Claude's answer costs no extra call at
# all, because the dispatcher is already running when it decides.
#
# So Jev is installed inert. What it still offers is latency and cost: ~360ms and a fraction of
# a cent against a full model turn, which is a real trade for a high-volume automated path, a
# latency budget, or somewhere the dispatcher is not already in the loop. Turn on exactly the
# decisions you want it for:
#
#   AGENT_DISPATCHER_DECISION_SCOPES=skills,tools
#
# `context` (ranking retrieved files) and `verification` (judging evidence) are declared in the
# interface and unimplemented — designed for, not shipped.
#
# Re-derive all of this with `python3 evals/decision/run.py --engine all
# --routes evals/decision/routes-claude.json`, and change these defaults if it disagrees.
DEFAULT_SCOPES = {"agent": False, "skills": False, "tools": False,
                  "context": False, "verification": False}

# Calibrated against `evals/decision`, not guessed. Over 162 routing fixtures the observed
# top-1 accuracy per confidence band was 0.98 at >=0.90 (n=113) and 0.75 at 0.80-0.90 (n=12),
# then collapsed: 0.67 at 0.70-0.80 (n=15) and 0.38 at 0.50-0.70 (n=13). So the agent floor is
# 0.80 — above it the route was right 96% of the time; below it the model is worse than a coin
# and the default path is the safer answer. TypeSafe's own guidance puts the absolute floor at
# 0.50; this is stricter because routing a whole task is not a cheap action to get wrong.
#
# The relevance floors are the precision knee from the same run. Skills: 0.63/0.81
# precision/recall at 0.50, 0.70/0.77 at 0.60, and 0.70/0.62 at 0.70 — recall falls away past
# 0.60 for no precision. Tools: 0.66/0.97 at 0.60. Re-derive them with
# `AGENT_DISPATCHER_DECISION_THRESHOLDS=skill_relevance=0.7 python3 evals/decision/run.py
# --engine jev` whenever the registries change; docs/jev.md carries the table.
DEFAULT_THRESHOLDS = {"agent_confidence": 0.8, "skill_relevance": 0.6, "tool_relevance": 0.6}

PROVIDERS = {
    # TypeSafe's own HTTP API, and the only route they publish a REST contract for:
    # https://docs.typesafe.ai/api. A Python caller has no better option, and an unpublished
    # one is not an option at all for something that carries a credential.
    "typesafe": {"credential_env": "TYPESAFE_API_KEY",
                 "base_url_env": "TYPESAFE_BASE_URL",
                 "base_url": "https://api.typesafe.ai",
                 "model": "jev-latest",
                 "label": "TypeSafe (direct)"},
}

# Deliberately absent from PROVIDERS: the mock transport. A test double that configuration can
# reach is a test double that can fabricate a plan and have it rendered as "Jev". Tests and the
# eval harness inject it through `service(provider_instance=...)`, which is a seam only code
# can use.

PROJECT_CONFIG = ".agent-dispatcher-decision.json"

_ENV = {"mode": "AGENT_DISPATCHER_DECISION_MODE",
        "provider": "AGENT_DISPATCHER_DECISION_PROVIDER",
        "model": "AGENT_DISPATCHER_DECISION_MODEL",
        "timeout_seconds": "AGENT_DISPATCHER_DECISION_TIMEOUT",
        "max_task_chars": "AGENT_DISPATCHER_DECISION_MAX_TASK_CHARS",
        "log": "AGENT_DISPATCHER_DECISION_LOG"}


class Config:
    def __init__(self, mode="auto", provider="typesafe", model=None, timeout_seconds=10.0,
                 scopes=None, thresholds=None, max_task_chars=2000, log="", offline=False,
                 sources=()):
        if mode not in MODES:
            raise ValueError(f"decision mode {mode!r} is not one of {MODES}")
        if provider not in PROVIDERS:
            raise ValueError(f"decision provider {provider!r} is not one of {sorted(PROVIDERS)}")
        self.mode = mode
        self.provider = provider
        self.model = model or PROVIDERS[provider]["model"]
        self.timeout_seconds = float(timeout_seconds)
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 300:
            raise ValueError("timeout_seconds must be finite and between 0 and 300 seconds")
        self.scopes = dict(DEFAULT_SCOPES, **(scopes or {}))
        self.thresholds = dict(DEFAULT_THRESHOLDS, **(thresholds or {}))
        if any(type(v) is not bool for v in self.scopes.values()):
            raise ValueError("decision scopes must be booleans")
        if any(not _number(v) or not 0 <= v <= 1 for v in self.thresholds.values()):
            raise ValueError("decision thresholds must be finite numbers between 0 and 1")
        if not _number(max_task_chars) or not 1 <= max_task_chars <= 100000:
            raise ValueError("max_task_chars must be between 1 and 100000")
        self.max_task_chars = int(max_task_chars)
        self.log = log
        self.offline = bool(offline)
        self.sources = tuple(sources)

    # -------------------------------------------------------------- credential

    @property
    def credential_env(self):
        """The variable name a user would set. Never the value."""
        return PROVIDERS[self.provider]["credential_env"]

    def has_credential(self):
        return bool(os.environ.get(self.credential_env, "").strip())

    def base_url(self):
        spec = PROVIDERS[self.provider]
        return os.environ.get(spec["base_url_env"], "").strip() or spec["base_url"]

    # -------------------------------------------------------------- posture

    def uses_jev(self, scope):
        """Whether Jev should be attempted for this decision. `off` short-circuits before any
        credential lookup, so an off installation makes no network call and needs no key."""
        if self.mode == "off" or not self.scopes.get(scope, False):
            return False
        if self.offline:
            return False
        return True

    def status(self):
        """What `/agent-decision` and `/agent-context` render. No secret, by construction."""
        spec = PROVIDERS[self.provider]
        if self.mode == "off":
            state = "disabled"
        elif self.offline:
            state = "unavailable — local-only mode"
        elif not self.has_credential():
            state = ("unavailable — no credential" if self.mode == "required"
                     else "not configured — default engine in use")
        elif not any(self.scopes.values()):
            state = "idle — credential configured, no decision scope enabled"
        else:
            state = "available"
        return {"mode": self.mode, "provider": spec["label"], "provider_id": self.provider,
                "model": self.model, "credentials": "configured" if self.has_credential()
                else "not configured", "credential_env": self.credential_env,
                "timeout_seconds": self.timeout_seconds, "status": state,
                "scopes": dict(self.scopes), "thresholds": dict(self.thresholds),
                "config_sources": list(self.sources) or ["defaults"]}


# ------------------------------------------------------------------ loading

def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _coerce(raw):
    """Take only the keys we know, and only values that are already valid.

    A project config file travels with a repository, so it is not the user's own input in the
    way an environment variable is. Two consequences:

    * A bad value is dropped, not passed on to raise later. "A broken project file must not
      take the dispatcher down with it" has to hold for a wrong *value*, not only wrong JSON.
    * `log` is not accepted here at all. It is a filesystem path that gets created and appended
      to, and a cloned repository should not be able to choose one. Set it in the environment.
    """
    out = {}
    if not isinstance(raw, dict):
        return out
    for key in ("mode", "provider", "model"):
        if isinstance(raw.get(key), str) and raw[key].strip():
            out[key] = raw[key].strip()
    if out.get("mode") not in MODES:
        out.pop("mode", None)
    if out.get("provider") not in PROVIDERS:
        out.pop("provider", None)
    if _number(raw.get("timeout_seconds")) and 0 < raw["timeout_seconds"] <= 300:
        out["timeout_seconds"] = raw["timeout_seconds"]
    if _number(raw.get("max_task_chars")) and 1 <= raw["max_task_chars"] <= 100000:
        out["max_task_chars"] = raw["max_task_chars"]
    if isinstance(raw.get("scopes"), dict):
        out["scopes"] = {k: v for k, v in raw["scopes"].items()
                         if k in DEFAULT_SCOPES and type(v) is bool}
    if isinstance(raw.get("thresholds"), dict):
        out["thresholds"] = {k: float(v) for k, v in raw["thresholds"].items()
                             if k in DEFAULT_THRESHOLDS and _number(v) and 0 <= v <= 1}
    return out


def _from_env():
    """Ambient, so a bad value is dropped with the rest of the environment's opinions."""
    out = {}
    for key, var in _ENV.items():
        val = os.environ.get(var, "").strip()
        if not val:
            continue
        if key in ("timeout_seconds", "max_task_chars"):
            try:
                out[key] = float(val)
            except ValueError:
                continue
        else:
            out[key] = val
    if out.get("mode") not in MODES:
        out.pop("mode", None)
    if out.get("provider") not in PROVIDERS:
        out.pop("provider", None)
    raw_thresholds = os.environ.get("AGENT_DISPATCHER_DECISION_THRESHOLDS", "").strip()
    if raw_thresholds:
        # "agent_confidence=0.8,skill_relevance=0.6" — the form evals/decision sweeps with.
        got = {}
        for pair in raw_thresholds.split(","):
            name, _, value = pair.partition("=")
            if name.strip() in DEFAULT_THRESHOLDS:
                try:
                    got[name.strip()] = float(value)
                except ValueError:
                    continue
        if got:
            out["thresholds"] = got
    raw_scopes = os.environ.get("AGENT_DISPATCHER_DECISION_SCOPES", "").strip()
    if raw_scopes:
        named = {s.strip() for s in raw_scopes.split(",") if s.strip()}
        out["scopes"] = {k: (k in named) for k in DEFAULT_SCOPES}
    clean = _coerce(out)
    if "log" in out:
        clean["log"] = out["log"]  # Only the user's environment can choose a log path.
    return clean


def _offline():
    return os.environ.get("AGENT_DISPATCHER_OFFLINE", "").strip().lower() in (
        "1", "true", "yes", "on")


def load(project_root=None, **overrides):
    """Build the effective config. `overrides` is the per-task layer — a CLI flag, or the user
    saying "don't use external APIs for this one" — and it wins over everything."""
    sources = []
    values = {}

    root = pathlib.Path(project_root or os.getcwd())
    path = root / PROJECT_CONFIG
    if path.is_file():
        try:
            values.update(_coerce(json.loads(path.read_text())))
            sources.append(str(path))
        except (ValueError, OSError) as exc:
            # A broken project file must not take the dispatcher down with it.
            sources.append(f"{path} (ignored: {exc.__class__.__name__})")

    env = _from_env()
    if env:
        sources.append("environment")
    values.update(env)

    explicit = {k: v for k, v in overrides.items() if v is not None}
    if explicit:
        sources.append("explicit")
    values.update(explicit)

    values.setdefault("offline", _offline())
    # An explicit argument still raises: argparse already constrains the CLI, so a bad one here
    # is a programming error and silently ignoring it would hide it. Ambient configuration — a
    # project file, an environment variable — has already been filtered to valid values above,
    # because neither is the user typing right now and neither should be able to stop a task.
    return Config(sources=sources, **values)
