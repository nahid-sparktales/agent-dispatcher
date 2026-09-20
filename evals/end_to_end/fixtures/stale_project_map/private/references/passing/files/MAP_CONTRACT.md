# Project-map contract

Refresh only docs/PROJECT_MAP.json from the current project. The old map and archive
are hints, not authority. Source files may have changed, moved, or been removed.
Return JSON with schema_version=1 and entries, containing exactly these ids:
- entrypoint: the current public worker callable, as module:symbol.
- max_attempts: the current integer total attempt budget used by that worker.
- retry_exception: the exception class name actually retried.
- test_command: the exact command in the Makefile test target, without indentation.

Each entry has id, value, and evidence. Evidence has path (project-relative POSIX),
start_line and end_line (inclusive, one-based, at most 12 lines), quote (exact lines
joined with newline, without a final newline), and sha256 (the current whole file's
hexadecimal SHA-256). Cite current implementing code or Makefile, not the old map
or archived notes. Select a range that directly supports the value. Each id occurs
once. No external services or dependencies are needed. Preserve all other files.
