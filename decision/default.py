"""The default engine — the behaviour that already existed, expressed in the abstraction.

It does **not** route. Routing has always been the model's job, guided by `SKILL.md`, and
putting a second heuristic router in front of that would be a regression dressed as a feature.
So it answers the agent question with "no decision — the existing path owns this", and answers
the skill and tool questions with exactly what the role's loadout already declares. Nothing
about a clean installation changes.

The measurement baseline the evaluation harness compares against is deliberately *not* here:
it lives in `evals/decision/baseline.py`, because it is a test instrument and has no business
being installed alongside the two engines that actually run.
"""
from .engine import DecisionEngine
from .types import AgentDecision, Selection, SkillDecision, ToolDecision

class DefaultDecisionEngine(DecisionEngine):
    """No network, no model call, no behaviour change. The loadout, as written."""

    name = "default"

    def __init__(self, registry):
        self.registry = registry

    def choose_agent(self, inp):
        # Deliberately empty. `SKILL.md` routes; this records that nothing overrode it.
        return AgentDecision(
            selected=None, ranked=(), engine=self.name,
            diagnostics=("agent routing left to the dispatcher's own method, as before",))

    def choose_skills(self, inp):
        """Core plus preferred — the tiers the loadout already says load before any condition."""
        role = self.registry.roles.get(inp.agent, {})
        buckets = role.get("skills", {})
        offered = {c.id for c in inp.candidates}
        chosen = []
        for tier in ("core", "preferred"):
            for skill_id in buckets.get(tier, []):
                if skill_id in offered and skill_id not in {s.id for s in chosen}:
                    chosen.append(Selection(id=skill_id, confidence=None, selected_by="default",
                                            reason=f"{tier} tier of the {inp.agent} loadout"))
        return SkillDecision(selected=tuple(chosen[: inp.limit]), ranked=(), engine=self.name,
                             diagnostics=())

    def choose_tools(self, inp):
        role = self.registry.roles.get(inp.agent, {})
        offered = {c.id for c in inp.candidates}
        chosen = [Selection(id=t, confidence=None, selected_by="default",
                            reason=f"recommended by the {inp.agent} loadout")
                  for t in role.get("mcps", {}).get("recommended", []) if t in offered]
        return ToolDecision(selected=tuple(chosen), ranked=(), engine=self.name, diagnostics=())
