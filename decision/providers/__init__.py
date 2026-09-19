"""Transports for the Jev engine.

`JevDecisionEngine` knows about decisions; a provider knows about one wire format. The split
exists so a second route — or a direct SDK, if this pack ever grows dependencies — arrives
without touching the engine or anything above it.

Every provider takes the credential out of `os.environ` at send time. None of them accepts one
as an argument, stores one on `self`, or puts one anywhere an exception, a log line or a
serialised record could reach.
"""
from .typesafe import TypeSafeProvider
from .vercel import VercelGatewayProvider

# The mock transport is intentionally not here. It is importable from `decision.providers.mock`
# by code that wants it, and unreachable from configuration — see the note in config.py.
PROVIDERS = {"typesafe": TypeSafeProvider, "vercel": VercelGatewayProvider}


def get(config, **kw):
    cls = PROVIDERS.get(config.provider)
    if cls is None:
        raise ValueError(f"unknown decision provider {config.provider!r}")
    return cls(config, **kw)


__all__ = ["get", "PROVIDERS", "TypeSafeProvider", "VercelGatewayProvider"]
