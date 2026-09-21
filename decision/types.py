"""The vocabulary every decision engine speaks.

Nothing here mentions Jev, a provider, or HTTP. The context engine consumes these types and
stays unable to tell which engine produced them — that boundary is the point of the package.

One rule holds across every type in this file: **a decision expresses relevance, never
authorization.** There is deliberately no field for a permission, a grant, a scope or an
approval, and `tests/test_decision.py` fails the build if one appears.
"""
import dataclasses
import typing

# Who made a selection. Recorded on every decision so a route can be explained after the fact.
PROVENANCE = ("forced", "recipe", "default", "jev")

@dataclasses.dataclass(frozen=True)
class Candidate:
    """One option the system decided was available. A decision picks among these and never
    invents a new one — candidate generation belongs to the registry, selection to the engine."""
    id: str
    label: str
    criteria: str          # the compact text a decision model reads to tell this one apart
    tags: tuple = ()

    def __post_init__(self):
        if not self.id or not self.criteria:
            raise ValueError(f"candidate {self.id!r}: id and criteria are both required")


@dataclasses.dataclass(frozen=True)
class Selection:
    """One chosen candidate, with how sure the engine was and who chose it."""
    id: str
    confidence: typing.Optional[float] = None   # None when the engine does not produce one
    selected_by: str = "default"
    reason: str = ""

    def __post_init__(self):
        if self.selected_by not in PROVENANCE:
            raise ValueError(f"selected_by {self.selected_by!r} not one of {PROVENANCE}")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence {self.confidence!r} outside 0..1")


# ---------------------------------------------------------------- inputs

@dataclasses.dataclass(frozen=True)
class AgentDecisionInput:
    """Task plus the roster. No repository source, no conversation, no environment."""
    task: str
    candidates: tuple
    stack: tuple = ()


@dataclasses.dataclass(frozen=True)
class SkillDecisionInput:
    task: str
    agent: str
    candidates: tuple
    stack: tuple = ()
    limit: int = 5


@dataclasses.dataclass(frozen=True)
class ToolDecisionInput:
    task: str
    agent: str
    candidates: tuple
    stack: tuple = ()


@dataclasses.dataclass(frozen=True)
class ContextRankingInput:
    """Designed for, not required in v1. Kept so a reranker can arrive without a redesign."""
    task: str
    agent: str
    candidates: tuple


@dataclasses.dataclass(frozen=True)
class VerificationDecisionInput:
    """Designed for, not required in v1."""
    task: str
    acceptance: tuple
    evidence: tuple


# ---------------------------------------------------------------- outputs

@dataclasses.dataclass(frozen=True)
class AgentDecision:
    """One owner, or none. `ranked` carries the whole distribution for diagnostics and evals —
    it is not for the execution prompt."""
    selected: typing.Optional[Selection]
    ranked: tuple = ()                 # ((candidate_id, score), ...) best first
    engine: str = "default"
    diagnostics: tuple = ()


@dataclasses.dataclass(frozen=True)
class SkillDecision:
    """Skill routing is multi-select: several methods can be relevant to one task."""
    selected: tuple = ()               # (Selection, ...) best first
    ranked: tuple = ()
    engine: str = "default"
    diagnostics: tuple = ()


@dataclasses.dataclass(frozen=True)
class ToolDecision:
    """Relevance only. A tool being relevant says nothing about being allowed — the runtime's
    permission layer is the only thing that answers that, and it never consults this."""
    selected: tuple = ()
    ranked: tuple = ()
    engine: str = "default"
    diagnostics: tuple = ()


@dataclasses.dataclass(frozen=True)
class ContextRankingDecision:
    ranked: tuple = ()
    engine: str = "default"
    diagnostics: tuple = ()


@dataclasses.dataclass(frozen=True)
class VerificationDecision:
    outcome: str = "done"              # done | retry | independent-review
    confidence: typing.Optional[float] = None
    engine: str = "default"
    diagnostics: tuple = ()


@dataclasses.dataclass(frozen=True)
class DecisionRecord:
    """One local diagnostic row. Never leaves the machine; never carries a credential."""
    decision: str
    engine: str
    provider: str = ""
    model: str = ""
    candidates: int = 0
    selected: str = ""
    confidence: typing.Optional[float] = None
    latency_ms: int = 0
    fallback: bool = False
    error: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    registry_version: str = ""

    def as_dict(self):
        return dataclasses.asdict(self)


class DecisionError(Exception):
    """Raised in `required` mode when a decision could not be made. Carries no secret."""


# The vocabulary `assert_no_authorization` refuses. Tokens, not substrings: a field is
# permission-shaped if any word in its name is one of these once camelCase, dashes and
# underscores are normalised away. Deliberately includes the credential words too — a decision
# has no business carrying one of those either.
PERMISSION_WORDS = ("permission", "permissions", "grant", "grants", "granted", "allow",
                    "allowed", "authorize", "authorized", "authorization", "authz", "auth",
                    "approve", "approved", "privilege", "privileges", "sudo", "elevate",
                    "credential", "credentials", "token", "key", "apikey", "secret")
