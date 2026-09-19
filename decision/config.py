"""How the decision layer is configured, and where the credential is not.

Precedence, highest first:

    1. an explicit argument (a CLI flag, a per-task override)
    2. the project's `.agent-dispatcher-decision.json`
    3. the environment
    4. the defaults below

The credential is deliberately absent from this object. `Config` can say *whether* one is
configured and *which* variable would carry it; the value is read by the provider, at the
moment of the request, straight out of `os.environ`. Nothing that is rendered, logged,
serialised or handed to a model has ever held it.
"""
import json
import os
import pathlib

MODES = ("off", "auto", "required")

# Default scopes. Agent, skill and tool selection are bounded choice problems and are on;
# context ranking and the verification gate are designed for and left off until evidence
# from evals/decision says they help.
DEFAULT_SCOPES = {"agent": True, "skills": True, "tools": True,
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
    # Documented, language-agnostic HTTP API. The default, because this pack is Python and
    # TypeSafe publishes the REST contract; https://docs.typesafe.ai/api
    "typesafe": {"credential_env": "TYPESAFE_API_KEY",
                 "base_url_env": "TYPESAFE_BASE_URL",
                 "base_url": "https://api.typesafe.ai",
                 "model": "jev-latest",
                 "label": "TypeSafe (direct)"},
    # Vercel documents evaluation through the AI SDK only, so the raw endpoint below is
    # best-effort rather than a published REST contract. Offered for accounts that already
    # bill through the gateway; docs/jev.md says plainly that it is the less-supported route.
    "vercel": {"credential_env": "AI_GATEWAY_API_KEY",
               "base_url_env": "AI_GATEWAY_BASE_URL",
               "base_url": "https://ai-gateway.vercel.sh",
               "model": "typesafe-ai/jev",
               "label": "Vercel AI Gateway"},
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
        self.scopes = dict(DEFAULT_SCOPES, **(scopes or {}))
        self.thresholds = dict(DEFAULT_THRESHOLDS, **(thresholds or {}))
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
        """What `/agent-dispatcher jev` and `/agent-context` render. No secret, by construction."""
        spec = PROVIDERS[self.provider]
        if self.mode == "off":
            state = "disabled"
        elif self.offline:
            state = "unavailable — local-only mode"
        elif not self.has_credential():
            state = ("unavailable — no credential" if self.mode == "required"
                     else "not configured — default engine in use")
        else:
            state = "available"
        return {"mode": self.mode, "provider": spec["label"], "provider_id": self.provider,
                "model": self.model, "credentials": "configured" if self.has_credential()
                else "not configured", "credential_env": self.credential_env,
                "timeout_seconds": self.timeout_seconds, "status": state,
                "scopes": dict(self.scopes), "thresholds": dict(self.thresholds),
                "config_sources": list(self.sources) or ["defaults"]}


# ------------------------------------------------------------------ loading

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
    for key in ("mode", "provider", "model"):
        if isinstance(raw.get(key), str) and raw[key].strip():
            out[key] = raw[key].strip()
    if out.get("mode") not in MODES:
        out.pop("mode", None)
    if out.get("provider") not in PROVIDERS:
        out.pop("provider", None)
    for key in ("timeout_seconds", "max_task_chars"):
        if isinstance(raw.get(key), (int, float)):
            out[key] = raw[key]
    if isinstance(raw.get("scopes"), dict):
        out["scopes"] = {k: bool(v) for k, v in raw["scopes"].items() if k in DEFAULT_SCOPES}
    if isinstance(raw.get("thresholds"), dict):
        out["thresholds"] = {k: float(v) for k, v in raw["thresholds"].items()
                             if k in DEFAULT_THRESHOLDS and isinstance(v, (int, float))}
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
    return out


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
        except (json.JSONDecodeError, OSError) as exc:
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
