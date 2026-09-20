# Context instruction baseline

`instruction-baseline.json` records UTF-8 byte sizes from the clean revision named
in the file. Claude files came from its generated package; Codex files came from
exporting that revision with its own generator in a temporary checkout.

`test_codex.py` checks both hosts against these four reading paths:

| Scenario | Previous references | Current references |
| --- | --- | --- |
| Exact forced role | SKILL + ACTIVITY | SKILL + ACTIVITY |
| Ordinary routing | SKILL + ACTIVITY, plus ROLES on Codex | SKILL + ACTIVITY + ROLES |
| Default context inspection | SKILL + CONTEXT | SKILL + CONTEXT |
| Activation control | SKILL | SKILL + CONTROLS |

The old Claude entrypoint contained its full role catalog and both old entrypoints
contained their controls. The current packages load those references on demand.
Advanced context examples and optional decision-provider details are excluded from
default inspection; requesting them loads CONTEXT-REFERENCE too.

These measurements cover the dispatcher entry and reference scaffold only. Role
methods, selected skill guides, workspace evidence, host instructions, hook output,
and conversation history are not included. They demonstrate smaller instruction
files, not measured model token usage, task quality, or superiority to either host.

The separate `test_context.py` suite exercises bounded retrieval. Live comparisons
with stock Claude Code and Codex remain future work.
