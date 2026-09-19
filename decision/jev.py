"""The Jev Decision Engine — optional, and one implementation of `DecisionEngine` among others.

Jev is a System One model: it answers typed questions against a shared state and returns typed
answers with probabilities, rather than generating text that then has to be parsed. Three
question types exist — `choice` picks one option, `noul` estimates the probability that a
statement is true, `score` grades an ordered rubric — and every question in one request is
evaluated in parallel against the same state.

That shape maps onto this pack's decisions almost exactly:

    agent selection   one `choice` over the role roster        one owner, with a confidence
    skill selection   one `noul` per candidate skill           multi-select, independent scores
    tool relevance    one `noul` per registered server         multi-select, relevance only

So a full decision is **two requests, not thirty-two**: one for the agent, then one carrying
every skill and tool question together, because the skill candidate set is not known until the
role is. When the user forced a role there is only one request.

What the engine sends is the whole of what it sends: the scrubbed, capped task text, the names
of detected technologies, and the compact registry metadata that already distinguishes one
candidate from another. No repository source, no file contents, no environment, no conversation
history. `decision/redact.py` scrubs the task first, and `docs/jev.md` documents the limits of
that rather than implying it makes the request safe.
"""
from . import providers
from .engine import DecisionEngine
from .redact import task_state
from .types import AgentDecision, Selection, SkillDecision, ToolDecision

AGENT_Q = "agent"
SKILL_PREFIX = "skill::"
TOOL_PREFIX = "tool::"


def _confidence(answer):
    """The provider's own statistic when it gives one; otherwise the top probability, labelled.

    TypeSafe documents `confidence` as a statistic computed from the probability distribution
    the answer already carries. When a transport does not surface it, falling back to the top
    probability is a different statistic and is reported as such — it is never presented as
    the model's confidence.
    """
    value = answer.get("confidence")
    if isinstance(value, (int, float)):
        return float(value), ""
    probs = answer.get("probabilities") or {}
    if probs:
        top = max(probs.values())
        return float(top), ("provider returned no confidence statistic; the top probability "
                            "was used in its place")
    return None, "provider returned neither a confidence nor a probability distribution"


def _probabilities(answer):
    probs = answer.get("probabilities") or {}
    if not isinstance(probs, dict):
        return ()
    # 0..1 is also what rejects nan and inf: neither comparison holds for them, so one range
    # check covers malformed numbers and out-of-range scores together.
    clean = [(k, float(v)) for k, v in probs.items()
             if isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 <= v <= 1.0]
    return tuple(sorted(clean, key=lambda kv: (-kv[1], kv[0])))


def _noul(answer):
    value = answer.get("noul")
    return float(value) if isinstance(value, (int, float)) and 0.0 <= value <= 1.0 else None


class JevDecisionEngine(DecisionEngine):
    name = "jev"
    supports_batch = True

    def __init__(self, config, registry, provider=None):
        self.config = config
        self.registry = registry
        self.provider = provider or providers.get(config)
        self._usage = {"input_tokens": 0, "output_tokens": 0}

    def _evaluate(self, state, questions):
        result = self.provider.evaluate(state, questions)
        usage = result.get("usage") or {}
        for key in ("input_tokens", "output_tokens"):
            self._usage[key] = self._usage.get(key, 0) + int(usage.get(key) or 0)
        return result

    # -------------------------------------------------------------- state

    def _state(self, task, stack=(), agent=None):
        state = {"task": task_state(task, self.config.max_task_chars)}
        if stack:
            state["detected_stack"] = list(stack)[:12]
        if agent:
            state["selected_role"] = agent
        return state

    # -------------------------------------------------------------- questions

    @staticmethod
    def _agent_question(candidates):
        return {AGENT_Q: {
            "type": "choice",
            "instructions": ("Exactly one specialist role should own this task. Which one? "
                             "Read each option's 'Not for' line as carefully as its "
                             "'Route here when' line."),
            "criteria": {c.id: c.criteria for c in candidates}}}

    @staticmethod
    def _skill_questions(candidates):
        return {f"{SKILL_PREFIX}{c.id}": {
            "type": "noul",
            "instructions": f"Does this task actually need the '{c.label}' method?",
            "criteria": {"true": c.criteria,
                         "false": "the task does not turn on this method, even if the topic "
                                  "is adjacent"}} for c in candidates}

    @staticmethod
    def _tool_questions(candidates):
        return {f"{TOOL_PREFIX}{c.id}": {
            "type": "noul",
            "instructions": (f"Is the capability '{c.label}' relevant to doing this task? "
                             f"Relevance only — this says nothing about being allowed to use it."),
            "criteria": {"true": c.criteria,
                         "false": "this capability is not needed to do the task"}}
            for c in candidates}

    # -------------------------------------------------------------- decisions

    def last_usage(self):
        """Token usage from the most recent request, for local cost reporting."""
        return dict(self._usage)

    def choose_agent(self, inp):
        if not inp.candidates:
            return AgentDecision(selected=None, engine=self.name,
                                 diagnostics=("no agent candidates were offered",))
        result = self._evaluate(self._state(inp.task, inp.stack),
                                self._agent_question(inp.candidates))
        answer = result["answers"].get(AGENT_Q)
        if not isinstance(answer, dict) or not isinstance(answer.get("choice"), str):
            return AgentDecision(selected=None, engine=self.name,
                                 diagnostics=("provider returned no usable agent answer",))
        confidence, note = _confidence(answer)
        notes = (note,) if note else ()
        return AgentDecision(
            selected=Selection(id=answer["choice"], confidence=confidence, selected_by="jev",
                               reason="structured choice over the role roster"),
            ranked=_probabilities(answer), engine=self.name, diagnostics=notes)

    def choose_skills(self, inp):
        decision, _ = self._batch(skills=inp, tools=None)
        return decision

    def choose_tools(self, inp):
        _, decision = self._batch(skills=None, tools=inp)
        return decision

    def choose_batch(self, skills, tools):
        """Skills and tools in one request. They share a state, so paying for two is waste."""
        return self._batch(skills=skills, tools=tools)

    def _batch(self, skills, tools):
        questions = {}
        if skills and skills.candidates:
            questions.update(self._skill_questions(skills.candidates))
        if tools and tools.candidates:
            questions.update(self._tool_questions(tools.candidates))
        if not questions:
            return (SkillDecision(engine=self.name), ToolDecision(engine=self.name))

        anchor = skills or tools
        result = self._evaluate(
            self._state(anchor.task, anchor.stack, agent=anchor.agent), questions)
        answers = result["answers"]

        skill_dec = self._collect(
            answers, SKILL_PREFIX, skills, SkillDecision,
            self.config.thresholds.get("skill_relevance", 0.5),
            limit=getattr(skills, "limit", 5) if skills else 5)
        # A ceiling, not a quota: past about six, a "relevant capability" list is noise
        # rather than context, and the registry's own fallback covers the rest.
        tool_dec = self._collect(
            answers, TOOL_PREFIX, tools, ToolDecision,
            self.config.thresholds.get("tool_relevance", 0.5), limit=6)
        return skill_dec, tool_dec

    def _collect(self, answers, prefix, inp, cls, threshold, limit):
        if inp is None:
            return cls(engine=self.name)
        scored, missing = [], []
        for cand in inp.candidates:
            answer = answers.get(f"{prefix}{cand.id}")
            value = _noul(answer) if isinstance(answer, dict) else None
            if value is None:
                missing.append(cand.id)
                continue
            scored.append((cand.id, value))
        scored.sort(key=lambda kv: (-kv[1], kv[0]))
        chosen = [i for i, v in scored if v >= threshold]
        if limit:
            chosen = chosen[:limit]
        notes = []
        if missing:
            notes.append(f"provider returned no usable answer for {len(missing)} candidate(s): "
                         + ", ".join(sorted(missing)[:6]))
        if not chosen and scored:
            notes.append(f"no candidate reached the relevance threshold of {threshold:.2f}")
        by_id = {i: v for i, v in scored}
        return cls(selected=tuple(Selection(id=i, confidence=by_id[i], selected_by="jev",
                                            reason="relevance to the task") for i in chosen),
                   ranked=tuple(scored), engine=self.name, diagnostics=tuple(notes))
