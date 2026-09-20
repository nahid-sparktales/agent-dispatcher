# Architecture evidence report

Replace architecture.json with JSON containing exactly: schema_version (1),
entrypoint, features, edges, dependencies, test_command, and decision.
- entrypoint: value is the current public HTTP-style callable as module:symbol.
- features: one object per supported /tasks route, with id (list_tasks or
  create_task), value (METHOD /path), and evidence for its route branch.
- edges: all direct route-to-service and service-to-store calls for those
  features. Each object has from, to, evidence. The route symbol is handle_request;
  method symbols use Class.method. Do not add import-only or proposed edges.
- dependencies: value is the exact ordered array of declared project dependencies.
- test_command: value is the Makefile test target's command without indentation.
- decision: id is storage, value is the accepted backend (in-memory or sqlite),
  status is accepted, and evidence points to the accepted decision record.

entrypoint, dependencies, and test_command each have value and evidence only.
Every evidence object has path (relative POSIX), start_line/end_line (inclusive,
one-based, 1-12 lines), quote (the exact cited lines joined with newline, with no
trailing newline), and sha256 (the current whole file's hexadecimal SHA-256).
Cite source callsites for edges, pyproject.toml for dependencies, Makefile for tests,
and the accepted ADR for the decision. Use a supporting range, not an entire file
by default. The prototype and proposal are not the live request flow or accepted
architecture. This task is inspection/documentation only; preserve every other file.
