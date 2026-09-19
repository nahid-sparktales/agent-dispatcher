"""Transports for the Jev engine.

`JevDecisionEngine` knows about decisions; a provider knows about one wire format. The split
exists so a second route — a direct SDK, another gateway — arrives without touching the engine
or anything above it.

One transport ships: TypeSafe's own HTTP API, which is the only route they publish a REST
contract for. A Vercel AI Gateway transport lived here briefly and was removed: Vercel
documents evaluation as available through their TypeScript SDK only, so it targeted an
undocumented endpoint, and it could never be verified against a live account. Carrying an
unverifiable integration for a feature that is off by default was the wrong trade. The seam it
used is still here for whoever needs it next.

The transport takes the credential out of `os.environ` at send time. It does not accept one as
an argument, store one on `self`, or put one anywhere an exception, a log line or a serialised
record could reach.
"""
from .typesafe import TypeSafeProvider

# The mock transport is intentionally not here. It is importable from `decision.providers.mock`
# by code that wants it, and unreachable from configuration — see the note in config.py.
PROVIDERS = {"typesafe": TypeSafeProvider}


def get(config, **kw):
    cls = PROVIDERS.get(config.provider)
    if cls is None:
        raise ValueError(f"unknown decision provider {config.provider!r}")
    return cls(config, **kw)


__all__ = ["get", "PROVIDERS", "TypeSafeProvider"]
