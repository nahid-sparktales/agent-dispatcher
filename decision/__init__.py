"""A Decision Engine for agent-dispatcher: which bounded choice should shape the work.

    Agent        = responsibility
    Skill        = method / specialized knowledge
    MCP / Tool   = capability
    Permission   = authorization          <- not this package, ever
    Context      = task-relevant information
    Verification = evidence
    Decision     = selecting what happens next   <- this package

Two engines implement one contract. `DefaultDecisionEngine` is the behaviour that already
existed and needs no account, no key and no network. `JevDecisionEngine` is optional: a user
who supplies their own credentials gets fast typed decisions for agent, skill and tool
selection, and pays their own provider for them. With no credential configured, `auto` mode
uses the default engine and nothing about a clean install changes.

Nothing here authorizes anything. A decision says what is *relevant*; the runtime's permission
layer decides what is *allowed*, it is not consulted here, and it never reads this output.
"""
from .config import Config, load as load_config
from .default import DefaultDecisionEngine
from .engine import DecisionEngine, DecisionService, Diagnostics, plan
from .registry import Registry
from .types import (AgentDecision, AgentDecisionInput, Candidate, ContextRankingDecision,
                    ContextRankingInput, DecisionError, DecisionRecord, Selection, SkillDecision,
                    SkillDecisionInput, ToolDecision, ToolDecisionInput, VerificationDecision,
                    VerificationDecisionInput)

__all__ = ["Config", "load_config", "DecisionEngine", "DecisionService", "Diagnostics",
           "DefaultDecisionEngine", "Registry", "plan", "service",
           "Candidate", "Selection", "DecisionError", "DecisionRecord",
           "AgentDecisionInput", "AgentDecision", "SkillDecisionInput", "SkillDecision",
           "ToolDecisionInput", "ToolDecision", "ContextRankingInput", "ContextRankingDecision",
           "VerificationDecisionInput", "VerificationDecision"]

__version__ = "1.0.0"


def service(project_root=None, registry=None, provider_instance=None, **overrides):
    """The one call an integrator needs. Returns a `DecisionService` wired for this machine.

    `provider_instance` injects a transport (the mock, in tests); `provider=` in `overrides`
    names one by id in the configuration. The Jev engine is constructed only when configuration
    actually asks for it, so a clean installation never imports a provider module, never reads
    a credential variable and never opens a socket.
    """
    cfg = load_config(project_root=project_root, **overrides)
    reg = registry or Registry()
    default = DefaultDecisionEngine(reg)
    primary = None
    if cfg.mode != "off" and not cfg.offline and (cfg.has_credential()
                                                  or provider_instance is not None):
        from .jev import JevDecisionEngine
        primary = JevDecisionEngine(cfg, reg, provider=provider_instance)
    return DecisionService(cfg, reg, primary=primary, default=default)
