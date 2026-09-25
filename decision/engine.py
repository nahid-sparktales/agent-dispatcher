"""The Decision Engine contract, and the policy that decides which one answers.

    DecisionEngine
      ├── DefaultDecisionEngine     the behaviour that already existed
      └── JevDecisionEngine         optional, user-supplied credentials

`DecisionService` is the only thing callers touch. It owns the off / auto / required policy,
validates every id an external engine returns against the canonical registry, records local
diagnostics, and falls back when that is the safe answer. Everything downstream — the context
plan, the context engine, `/agent-context` — sees the generic result types in `types.py` and
cannot tell which engine produced them.
"""
import abc
import json
import pathlib
import re
import time

from . import types
from .redact import task_state
from .types import (AgentDecision, AgentDecisionInput, DecisionError, DecisionRecord,
                    SkillDecision, SkillDecisionInput, ToolDecision, ToolDecisionInput)


class DecisionEngine(abc.ABC):
    """Five decisions. Three are answered in v1; two are declared so a later engine — a
    reranker, a verification judge — arrives without reshaping anything above it."""

    name = "engine"

    @abc.abstractmethod
    def choose_agent(self, inp):
        """-> AgentDecision"""

    @abc.abstractmethod
    def choose_skills(self, inp):
        """-> SkillDecision"""

    @abc.abstractmethod
    def choose_tools(self, inp):
        """-> ToolDecision"""

    def rank_context(self, inp):
        """-> ContextRankingDecision. Optional; None means "this engine does not rank"."""
        return None

    def evaluate_verification(self, inp):
        """-> VerificationDecision. Optional; None means "this engine does not judge evidence"."""
        return None


# ------------------------------------------------------------------ diagnostics

class Diagnostics:
    """Local only. Nothing here is transmitted anywhere, and a record never holds a credential:
    `DecisionRecord` has no field that could carry one, and the provider never hands one back."""

    def __init__(self, path=""):
        self.records = []
        self.path = path

    def record(self, rec):
        self.records.append(rec)
        if not self.path:
            return
        try:
            target = pathlib.Path(self.path).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a") as fh:
                fh.write(json.dumps(rec.as_dict()) + "\n")
        except OSError:
            pass                      # diagnostics must never be the thing that fails a task

    def as_list(self):
        return [r.as_dict() for r in self.records]

    @property
    def fell_back(self):
        return any(r.fallback for r in self.records)


# ------------------------------------------------------------------ service

_REQUIRED_HELP = (
    "The Jev Decision Engine is set to `required`, but {why}. Configure the documented "
    "provider credential ({env}), or set the decision mode to `auto` (use Jev when it is "
    "available, otherwise the default engine) or `off`.")


class DecisionService:
    """Applies the mode policy to a primary engine, with the default engine behind it."""

    def __init__(self, config, registry, primary=None, default=None, diagnostics=None):
        self.config = config
        self.registry = registry
        self.primary = primary
        self.default = default
        self.diag = diagnostics or Diagnostics(config.log)

    # -------------------------------------------------------------- policy

    def _unavailable_reason(self):
        cfg = self.config
        if cfg.mode == "off":
            return "the decision mode is `off`"
        if cfg.offline:
            return "this session is local-only"
        if self.primary is None:
            return "no external decision engine is configured"
        if not cfg.has_credential():
            return f"no credential is configured in {cfg.credential_env}"
        return ""

    def _guard(self, scope):
        """Returns the engine to try, or None to use the default. Raises in `required` mode."""
        cfg = self.config
        if cfg.mode == "required" and not cfg.scopes.get(scope, False):
            raise DecisionError(
                f"The Jev Decision Engine is set to `required`, but the `{scope}` decision "
                f"scope is switched off. Enable it, or set the mode to `auto`.")
        if not cfg.uses_jev(scope) or self.primary is None or not cfg.has_credential():
            why = self._unavailable_reason()
            if cfg.mode == "required":
                raise DecisionError(_REQUIRED_HELP.format(why=why, env=cfg.credential_env))
            return None
        return self.primary

    def _usage(self):
        """Whatever the primary engine reports, or zeroes. Local diagnostics only."""
        report = getattr(self.primary, "last_usage", None)
        return report() if callable(report) else {}

    def _attempt(self, scope, call, decision_kind, candidate_count):
        """Run the primary engine, or fall back. `required` mode never falls back."""
        engine = self._guard(scope)
        if engine is None:
            return None
        started = time.monotonic()
        try:
            result = call(engine)
        except Exception as exc:                                  # noqa: BLE001 - see below
            # Deliberately broad: a provider timeout, a DNS failure, a malformed body and a
            # rate limit are all the same event here — the optional optimisation did not
            # answer, and an optional optimisation must never take the agent system down.
            elapsed = int((time.monotonic() - started) * 1000)
            self.diag.record(DecisionRecord(
                decision=decision_kind, engine=getattr(engine, "name", "unknown"),
                provider=self.config.provider, model=self.config.model,
                candidates=candidate_count, latency_ms=elapsed, fallback=True,
                error=_safe_error(exc), registry_version=self.registry.version))
            if self.config.mode == "required":
                # `from None`: the scrubbed text is already in the message, and keeping the
                # chain would print the original exception — which is the one thing that might
                # quote a request header — in any traceback.
                raise DecisionError(
                    f"The Jev Decision Engine is set to `required` and the {decision_kind} "
                    f"decision failed: {_safe_error(exc)}. Fix the provider configuration, or "
                    f"set the mode to `auto` to fall back to the default engine.") from None
            return None
        return result

    # -------------------------------------------------------------- decisions

    def choose_agent(self, inp):
        result = self._attempt("agent", lambda e: e.choose_agent(inp), "agent-selection",
                               len(inp.candidates))
        result, notes = self._validate_agent(result, inp)
        if result is not None:
            return result
        fallback = self.default.choose_agent(inp) if self.default else AgentDecision(
            selected=None, engine="default",
            diagnostics=("no decision engine answered; routing stays with the default path",))
        # Why the fallback happened has to survive the fallback, or `/agent-context` shows a
        # default route with no explanation and a wrong rejection becomes invisible.
        return dataclass_replace(fallback,
                                 diagnostics=tuple(notes) + tuple(fallback.diagnostics))

    def choose_skills(self, inp):
        result = self._attempt("skills", lambda e: e.choose_skills(inp), "skill-selection",
                               len(inp.candidates))
        result, notes = self._validate_multi(result, inp, self.registry.valid_skill,
                                             SkillDecision, "skill")
        return self._or_default(result, notes, self.default.choose_skills if self.default
                                else None, inp, SkillDecision)

    def choose_tools(self, inp):
        result = self._attempt("tools", lambda e: e.choose_tools(inp), "tool-selection",
                               len(inp.candidates))
        result, notes = self._validate_multi(result, inp, self.registry.valid_tool,
                                             ToolDecision, "tool")
        return self._or_default(result, notes, self.default.choose_tools if self.default
                                else None, inp, ToolDecision)

    @staticmethod
    def _or_default(result, notes, fallback_call, inp, cls):
        if result is not None:
            return result
        out = fallback_call(inp) if fallback_call else cls(engine="default")
        return dataclass_replace(out, diagnostics=tuple(notes) + tuple(out.diagnostics))

    def choose_skills_and_tools(self, skill_input, tool_input):
        """One request when the engine can carry both, two when it cannot.

        Skills and tools share a state — same task, same role — so an engine whose API
        evaluates several typed questions against one state should be asked once. Nothing
        above this method knows or cares which happened.
        """
        engine = self._guard("skills") if self.config.scopes.get("skills") else None
        if engine is None or not getattr(engine, "supports_batch", False) \
                or not self.config.scopes.get("tools", False):
            return self.choose_skills(skill_input), self.choose_tools(tool_input)

        def call(e):
            return e.choose_batch(skill_input, tool_input)

        pair = self._attempt("skills", call, "skill+tool-selection",
                             len(skill_input.candidates) + len(tool_input.candidates))
        if pair is None:
            return (self.default.choose_skills(skill_input) if self.default
                    else SkillDecision(engine="default"),
                    self.default.choose_tools(tool_input) if self.default
                    else ToolDecision(engine="default"))
        skills, tools = pair
        skills, snotes = self._validate_multi(skills, skill_input, self.registry.valid_skill,
                                              SkillDecision, "skill")
        tools, tnotes = self._validate_multi(tools, tool_input, self.registry.valid_tool,
                                             ToolDecision, "tool")
        return (self._or_default(skills, snotes, self.default.choose_skills if self.default
                                 else None, skill_input, SkillDecision),
                self._or_default(tools, tnotes, self.default.choose_tools if self.default
                                 else None, tool_input, ToolDecision))

    # -------------------------------------------------------------- validation

    def _validate_agent(self, result, inp):
        """An external model's answer is untrusted input. An id that does not resolve against
        the registry is discarded — never dynamically invented into a role."""
        if result is None:
            return None, ()
        offered = {c.id for c in inp.candidates}
        # `ranked` is rendered by `/agent-context explain`, so it is as much a path into a user
        # surface as `selected` is. Filter it in one place, before any return.
        result = dataclass_replace(
            result, ranked=tuple((i, p) for i, p in result.ranked if i in offered))
        notes = list(result.diagnostics)
        sel = result.selected
        if sel is None:
            notes.append("decision engine returned no usable agent answer; routing fell back")
            self.diag.record(DecisionRecord(
                decision="agent-selection", engine=result.engine, provider=self.config.provider,
                model=self.config.model, candidates=len(inp.candidates), fallback=True,
                error="no-usable-answer", registry_version=self.registry.version))
            if self.config.mode == "required":
                raise DecisionError(
                    "The Jev Decision Engine is set to `required` and returned no usable agent "
                    "answer. Fix the provider response, or set the mode to `auto` to fall back "
                    "to the default engine.")
            return None, tuple(notes)
        if not self.registry.valid_agent(sel.id) or sel.id not in offered:
            notes.append(f"decision engine returned agent '{_safe_id(sel.id)}', which is not a "
                         f"candidate in this registry — discarded, and routing fell back")
            self.diag.record(DecisionRecord(
                decision="agent-selection", engine=result.engine, provider=self.config.provider,
                model=self.config.model, candidates=len(inp.candidates), fallback=True,
                error="unknown-candidate", registry_version=self.registry.version))
            if self.config.mode == "required":
                raise DecisionError(
                    f"The Jev Decision Engine is set to `required` and returned an agent id "
                    f"('{_safe_id(sel.id)}') that no registered role matches.")
            return None, tuple(notes)
        floor = self.config.thresholds.get("agent_confidence", 0.8)
        if sel.confidence is not None and sel.confidence < floor:
            notes.append(f"agent confidence {sel.confidence:.2f} is below the configured floor "
                         f"of {floor:.2f}; the default route was used instead")
            self.diag.record(DecisionRecord(
                decision="agent-selection", engine=result.engine, provider=self.config.provider,
                model=self.config.model, candidates=len(inp.candidates),
                selected=sel.id, confidence=sel.confidence, fallback=True,
                error="below-confidence-floor", registry_version=self.registry.version))
            if self.config.mode == "required":
                # `required` means "tell me when Jev could not answer", and a route the policy
                # rejects is exactly that. Returning it anyway while the record says `fallback`
                # would make the two disagree, and a controlled evaluation would be measuring
                # a route the product would never take.
                raise DecisionError(
                    f"The Jev Decision Engine is set to `required` and returned an agent below "
                    f"the configured confidence floor ({sel.confidence:.2f} < {floor:.2f}). "
                    f"Lower `thresholds.agent_confidence`, or set the mode to `auto` to fall "
                    f"back to the default engine.")
            return None, tuple(notes)
        self.diag.record(DecisionRecord(
            decision="agent-selection", engine=result.engine, provider=self.config.provider,
            model=self.config.model, candidates=len(inp.candidates), selected=sel.id,
            confidence=sel.confidence, registry_version=self.registry.version,
            **self._usage()))
        return dataclass_replace(result, diagnostics=tuple(notes)), ()

    def _validate_multi(self, result, inp, is_valid, cls, label):
        if result is None:
            return None, ()
        offered = {c.id for c in inp.candidates}
        notes, kept = list(result.diagnostics), []
        for sel in result.selected:
            if sel.id in offered and is_valid(sel.id):
                kept.append(sel)
            else:
                notes.append(f"decision engine returned {label} '{_safe_id(sel.id)}', which is "
                             f"not a candidate in this registry — discarded")
        ranked = tuple((i, s) for i, s in result.ranked if i in offered)
        # "Nothing was relevant" and "the provider answered nothing" look identical from here,
        # and only one of them is an answer. If it selected nothing AND ranked nothing over a
        # non-empty candidate set, it did not answer.
        answered_nothing = not kept and not ranked and bool(inp.candidates)
        if answered_nothing or (not kept and result.selected):
            self.diag.record(DecisionRecord(
                decision=f"{label}-selection", engine=result.engine,
                provider=self.config.provider, model=self.config.model,
                candidates=len(inp.candidates), fallback=True, error="unknown-candidate",
                registry_version=self.registry.version))
            if self.config.mode == "required":
                raise DecisionError(
                    f"The Jev Decision Engine is set to `required` and returned no {label} id "
                    f"that matches this registry.")
            return None, tuple(notes)
        self.diag.record(DecisionRecord(
            decision=f"{label}-selection", engine=result.engine, provider=self.config.provider,
            model=self.config.model, candidates=len(inp.candidates),
            selected=",".join(s.id for s in kept), registry_version=self.registry.version,
            **self._usage()))
        return cls(selected=tuple(kept), ranked=ranked, engine=result.engine,
                   diagnostics=tuple(notes)), ()


def dataclass_replace(obj, **kw):
    import dataclasses
    return dataclasses.replace(obj, **kw)


_ID_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_id(value):
    """An id we are about to reject is still a string an external service chose."""
    return _ID_SAFE.sub("", str(value))[:40] or "(empty)"


def _safe_error(exc):
    """A short, actionable description. Message text only from exceptions we constructed.

    A `ProviderError` is ours: every raise site uses a fixed string or something the provider
    module itself produced, so its message is safe to keep (and is scrubbed anyway, as a second
    line rather than the first). Anything else came from below our own code and could quote the
    request — headers included — so only the class name survives. Redaction should never be the
    thing standing between a credential and a log file when refusing to produce the text at all
    is available.
    """
    from .providers.typesafe import ProviderError
    from .redact import scrub
    if isinstance(exc, (ProviderError, DecisionError)):
        text = scrub(str(exc))[:200].rstrip(". ")
        return f"{exc.__class__.__name__}: {text}" if text else exc.__class__.__name__
    return exc.__class__.__name__


# Proof, in code, that a decision cannot carry authorization. Imported by the test suite.
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_WORDY = re.compile(r"[^a-z0-9]+")


def assert_no_authorization(payload):
    """Raise if anything in a decision payload is permission-shaped.

    Matching is on tokens, not suffixes: `permissionGranted`, `permission-granted` and
    `granted_permissions` all normalise to the same words, and a suffix test would miss two of
    the three. A payload that is not a mapping or a sequence is a programming error here rather
    than a pass, so it raises instead of quietly succeeding.
    """
    def tokens(text):
        # camelCase first, then everything else — `permissionGranted`, `permission-granted`
        # and `granted_permissions` must all reduce to the same two words.
        split = _CAMEL.sub("_", str(text))
        return set(_WORDY.sub("_", split.lower()).strip("_").split("_"))

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                if tokens(k) & set(types.PERMISSION_WORDS):
                    raise AssertionError(
                        f"decision payload carries a permission-shaped field at {path}{k!r}. "
                        f"Relevance and authorization are separate layers; the runtime owns "
                        f"the second one and never consults this.")
                walk(v, f"{path}{k}.")
        elif isinstance(node, (list, tuple)):
            for i, v in enumerate(node):
                walk(v, f"{path}{i}.")

    if not isinstance(payload, (dict, list, tuple)):
        raise TypeError(f"assert_no_authorization needs a decision payload, got "
                        f"{type(payload).__name__}")
    walk(payload)
    return True


# ------------------------------------------------------------------ the whole decision

def plan(service, task, forced_agent=None, stack=(), skill_limit=5, ineligible=frozenset()):
    """Every decision the engine is allowed to make for one task, as one generic result.

    Order matters and so does what is *not* asked. When the user named a role
    (`/agent-debugger`), agent selection does not happen at all — the owner is already chosen,
    asking again would waste a call and could contradict an explicit instruction. Skill and
    tool relevance still run, because "which debugging skills" is a question the user did not
    answer by naming the role.

    The result is deliberately engine-agnostic: `selected_by` distinguishes forced, default and
    jev, and everything downstream reads that rather than knowing what Jev is.

    `ineligible` holds capability ids a deterministic gate already refused (disabled, blocked,
    quarantined, retired). They are removed from the candidate sets before any provider sees them,
    and because validation only keeps offered ids, no answer can reintroduce them afterwards. Only
    the ids leave this function's inputs; health details and account state never reach a provider.
    """
    registry = service.registry
    # The scrubbed form, not the raw one. This dict is rendered, serialised with `--json` and,
    # per the command doc, shown by an agent — every surface the provider payload is careful
    # about. Echoing the unscrubbed original here would undo that care one line later.
    out = {"task": task_state(task, service.config.max_task_chars),
           "registry_version": registry.version,
           "engine": "default", "diagnostics": [], "agent": None, "skills": [], "tools": []}

    # ---- agent
    if forced_agent:
        if not registry.valid_agent(forced_agent):
            raise DecisionError(f"'{forced_agent}' is not a registered role.")
        out["agent"] = {"id": forced_agent, "selected_by": "forced", "confidence": None,
                        "reason": "the user named the role"}
        out["diagnostics"].append("agent selection skipped — the user named the role")
    else:
        candidates = registry.agent_candidates()
        decision = service.choose_agent(AgentDecisionInput(task=task, candidates=candidates,
                                                           stack=tuple(stack)))
        out["diagnostics"].extend(decision.diagnostics)
        if decision.selected:
            out["agent"] = {"id": decision.selected.id,
                            "selected_by": decision.selected.selected_by,
                            "confidence": decision.selected.confidence,
                            "reason": decision.selected.reason}
            out["engine"] = decision.engine
        out["agent_ranked"] = [{"id": i, "probability": p} for i, p in decision.ranked[:8]]

    agent_id = (out["agent"] or {}).get("id")
    if not agent_id:
        # Nothing selected an owner, which is the default engine's correct answer: the
        # dispatcher's own method routes, exactly as it did before this package existed.
        # The fallback still has to be visible here — this is the exact path a timeout or a
        # rejected credential takes, and a silent default is how a broken configuration hides.
        return _stamp(out, service)

    # ---- skills and tools, in one request where the engine supports it
    blocked = frozenset(ineligible)
    skill_candidates = tuple(c for c in registry.skill_candidates(agent_id) if c.id not in blocked)
    tool_candidates = tuple(c for c in registry.tool_candidates() if c.id not in blocked)
    withheld = (len(registry.skill_candidates(agent_id)) - len(skill_candidates)
                + len(registry.tool_candidates()) - len(tool_candidates))
    if withheld:
        out["diagnostics"].append(f"{withheld} candidate(s) withheld by capability policy before selection")
    skill_in = SkillDecisionInput(task=task, agent=agent_id, stack=tuple(stack),
                                  candidates=skill_candidates, limit=skill_limit)
    tool_in = ToolDecisionInput(task=task, agent=agent_id, stack=tuple(stack),
                                candidates=tool_candidates)
    skills, tools = service.choose_skills_and_tools(skill_in, tool_in)

    out["skills"] = [{"id": s.id, "selected_by": s.selected_by, "confidence": s.confidence,
                      "reason": s.reason} for s in skills.selected if s.id not in blocked]
    out["tools"] = [{"id": s.id, "selected_by": s.selected_by, "confidence": s.confidence,
                     "reason": s.reason} for s in tools.selected if s.id not in blocked]
    out["skill_ranked"] = [{"id": i, "relevance": v} for i, v in skills.ranked[:12]]
    out["tool_ranked"] = [{"id": i, "relevance": v} for i, v in tools.ranked[:12]]
    out["diagnostics"].extend(skills.diagnostics)
    out["diagnostics"].extend(tools.diagnostics)
    if skills.engine != "default" or tools.engine != "default":
        out["engine"] = skills.engine if skills.engine != "default" else tools.engine
    return _stamp(out, service)


def _stamp(out, service):
    """Record which engine answered and whether anything was attempted and fell back."""
    if service.diag.fell_back:
        out["fallback"] = True
        errors = sorted({r.error for r in service.diag.records if r.fallback and r.error})
        if errors:
            out["fallback_reason"] = "; ".join(errors)
    if service.primary is not None:
        out["attempted"] = getattr(service.primary, "name", "")
        out["provider"] = service.config.provider
        out["model"] = service.config.model
    return out
