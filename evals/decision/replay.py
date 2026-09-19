"""Score decisions that were made somewhere else.

Claude is the production default path for agent routing, and it is not something `run.py` can
call: it is the model running the dispatcher, not a service with an endpoint. So the comparison
runs in two steps — route the fixtures with Claude however you can (a headless
`claude -p` loop, a subagent fan-out, a notebook), write the answers to a file, then score that
file here against the same fixtures Jev was scored on.

The file is a JSON object with a `routes` array, and optionally a `selections` array:

    {"routes": [{"id": "debugger-obvious-1", "role": "debugger", "confidence": 0.95,
                 "runner_up": "implementer", "why": "..."}],
     "selections": [{"id": "ui-03", "kind": "skills",
                     "selected": ["responsive-design", "browser-verification"]}]}

`confidence` and `runner_up` are optional. Only `id` and `role` are required on a route, and
`id`/`kind`/`selected` on a selection. An id that does not match a fixture is ignored rather
than guessed at, and a decision the file does not cover is reported as unanswered rather than
scored as an empty one — "not measured" and "selected nothing" are different results.
"""
import json
import pathlib

from decision.engine import DecisionEngine
from decision.types import AgentDecision, Selection, SkillDecision, ToolDecision


class ReplayDecisionEngine(DecisionEngine):
    """Serves pre-computed agent routes. Answers nothing it was not given."""

    name = "replay"

    def __init__(self, registry, path, label="replay"):
        self.registry = registry
        self.name = label
        raw = json.loads(pathlib.Path(path).read_text())
        rows = raw.get("routes", raw if isinstance(raw, list) else [])
        self.routes = {r["id"]: r for r in rows if isinstance(r, dict) and r.get("id")}
        picks = raw.get("selections", []) if isinstance(raw, dict) else []
        self.selections = {(p["id"], p.get("kind")): p for p in picks
                           if isinstance(p, dict) and p.get("id")}
        self.missing = []

    def covers(self, kind):
        """Whether this file answers a decision at all, as opposed to answering it emptily."""
        return any(k == kind for _, k in self.selections)

    def route_for(self, case_id):
        return self.routes.get(case_id)

    def choose_agent(self, inp):
        """`inp` carries no case id, so `run.py` sets `_case` on it before calling."""
        case = getattr(inp, "_case", None)
        row = self.routes.get(case) if case else None
        if not row:
            self.missing.append(case)
            return AgentDecision(selected=None, engine=self.name,
                                 diagnostics=(f"no recorded route for {case}",))
        role = str(row.get("role", "")).strip()
        offered = {c.id for c in inp.candidates}
        if role not in offered or not self.registry.valid_agent(role):
            # Same rule the runtime applies: an id that does not resolve is discarded, not
            # invented. Scoring it as a route would flatter whatever produced it.
            return AgentDecision(selected=None, engine=self.name,
                                 diagnostics=(f"recorded role '{role[:40]}' is not a candidate",))
        conf = row.get("confidence")
        conf = float(conf) if isinstance(conf, (int, float)) and 0.0 <= conf <= 1.0 else None
        ranked = [(role, conf if conf is not None else 1.0)]
        runner = str(row.get("runner_up", "")).strip()
        if runner in offered:
            ranked.append((runner, max(0.0, 1.0 - (conf if conf is not None else 1.0))))
        return AgentDecision(
            selected=Selection(id=role, confidence=conf, selected_by="default",
                               reason=str(row.get("why", ""))[:200]),
            ranked=tuple(ranked), engine=self.name)

    def choose_skills(self, inp):
        return self._replay(inp, "skills", SkillDecision)

    def choose_tools(self, inp):
        return self._replay(inp, "tools", ToolDecision)

    def _replay(self, inp, kind, cls):
        case = getattr(inp, "_case", None)
        row = self.selections.get((case, kind))
        if not row:
            return cls(engine=self.name,
                       diagnostics=(f"no recorded {kind} selection for {case}",))
        offered = {c.id for c in inp.candidates}
        kept, dropped = [], []
        for raw in row.get("selected", []):
            sid = str(raw).strip()
            # Same rule the runtime applies: an id that does not resolve is discarded, not
            # invented. Scoring it would flatter whatever produced it.
            (kept if sid in offered else dropped).append(sid)
        limit = getattr(inp, "limit", None)
        if limit:
            kept = kept[:limit]
        notes = ()
        if dropped:
            notes = (f"discarded {len(dropped)} id(s) not in the candidate set: "
                     + ", ".join(d[:40] for d in dropped[:5]),)
        return cls(selected=tuple(Selection(id=i, confidence=None, selected_by="default",
                                            reason=str(row.get("why", ""))[:200]) for i in kept),
                   ranked=tuple((i, 1.0) for i in kept), engine=self.name, diagnostics=notes)
