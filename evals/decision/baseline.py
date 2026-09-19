"""A measurement floor for `run.py`. Not part of the shipped runtime.

This lives beside the fixtures rather than inside `decision/` on purpose. It is an evaluation
baseline, it is never wired into the dispatcher, and shipping it into `~/.claude` would put a
third "engine" in front of users that none of them should ever select.

What the *production* default engine does is defer agent routing to the model — which no
offline harness can score. That is why a baseline has to exist at all, and why every report
says a number above it is not automatically a number above production.
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from decision.engine import DecisionEngine                            # noqa: E402
from decision.types import AgentDecision, Selection, SkillDecision, ToolDecision  # noqa: E402

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset("""a an the and or but if then this that these those it its is are was were be
been being to of in on at for with from by as not no do does did can could should would will
my our your their i we you they he she them us me need needs want wants please help make made
work works working use uses using get gets got when where why how what which who whom whose
after before during while into over under again more most some any all each every other than
too very just now new old same so such only own here there about up down out off""".split())


def _tokens(text):
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 2}


class LexicalDecisionEngine(DecisionEngine):
    """An offline measurement baseline. Not the dispatcher's default path — see the module note.

    Scoring is additive, transparent and inverse-document-weighted: a term that appears in one
    candidate's metadata discriminates, a term that appears in twenty does not. That is enough
    to be a fair floor rather than a straw man, and it is the same posture the context engine
    already takes for workspace ranking — the number orders candidates and nothing more.

    It reports **no confidence**. The score is ordinal, and dressing an ordinal up as a
    probability is precisely the mistake this package warns about everywhere else, so
    `Selection.confidence` stays `None` and only `ranked` carries the numbers.
    """

    name = "lexical-baseline"

    def __init__(self, registry):
        self.registry = registry

    @staticmethod
    def _weights(candidates):
        """Inverse document frequency over the candidate set itself."""
        import math
        docs = [_tokens(c.criteria) | {t.lower() for t in c.tags} | _tokens(c.label)
                for c in candidates]
        n = len(docs) or 1
        freq = {}
        for doc in docs:
            for term in doc:
                freq[term] = freq.get(term, 0) + 1
        return {t: math.log(1.0 + n / f) for t, f in freq.items()}

    def _rank(self, task, candidates):
        toks = _tokens(task)
        if not candidates:
            return ()
        idf = self._weights(candidates)
        scored = []
        for cand in candidates:
            head, _, tail = cand.criteria.partition("Not for:")
            positive = _tokens(head) | {t.lower() for t in cand.tags} | _tokens(cand.label)
            negative = _tokens(tail)
            score = sum(idf.get(t, 0.0) for t in toks & positive)
            score += 1.5 * sum(idf.get(t, 0.0) for t in toks & {t.lower() for t in cand.tags})
            score -= 0.75 * sum(idf.get(t, 0.0) for t in toks & negative)
            scored.append((cand.id, max(score, 0.0)))
        total = sum(s for _, s in scored) or 1.0
        return tuple(sorted(((i, round(s / total, 4)) for i, s in scored),
                            key=lambda kv: (-kv[1], kv[0])))

    def choose_agent(self, inp):
        ranked = self._rank(inp.task, inp.candidates)
        if not ranked or ranked[0][1] <= 0:
            return AgentDecision(selected=None, ranked=ranked, engine=self.name,
                                 diagnostics=("no lexical overlap with any role",))
        return AgentDecision(
            selected=Selection(id=ranked[0][0], confidence=None, selected_by="default",
                               reason="highest inverse-frequency term overlap"),
            ranked=ranked, engine=self.name)

    def choose_skills(self, inp):
        ranked = self._rank(inp.task, inp.candidates)
        keep = [i for i, s in ranked if s > 0][: inp.limit]
        return SkillDecision(
            selected=tuple(Selection(id=i, confidence=None, selected_by="default",
                                     reason="lexical overlap") for i in keep),
            ranked=ranked, engine=self.name)

    def choose_tools(self, inp):
        ranked = self._rank(inp.task, inp.candidates)
        keep = [i for i, s in ranked if s > 0][:4]
        return ToolDecision(
            selected=tuple(Selection(id=i, confidence=None, selected_by="default",
                                     reason="lexical overlap") for i in keep),
            ranked=ranked, engine=self.name)
