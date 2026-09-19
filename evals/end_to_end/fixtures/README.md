# Starter task fixtures

These 12 small, deterministic tasks validate the runner. Their results alone do not
establish benefit on real projects. The smoke subset is `greeting` plus
`merge_intervals`; both conditions on both clients produce eight attempts. The full
suite with two repetitions produces 96 attempts.

Only each fixture's `source/` directory and manifest `prompt` are supplied to the
agent. `private/` holds independent evaluators, reference artifacts, and example
human ratings. Never copy a whole fixture directory into a trial workspace. The
loader rejects private evaluators or references within `source_dir`.

## Manifest version 1

`manifest.json` contains `schema_version: 1` and a `fixtures` array. The accompanying
`manifest.schema.json` describes its wire format. Each entry contains:

| Field | Meaning |
| --- | --- |
| `id` | Unique lowercase task ID using letters, digits, underscores, and hyphens |
| `category` | Task family used when interpreting coverage |
| `prompt` | Complete user task, identical across conditions apart from dispatcher invocation |
| `source_dir` | Relative path to files supplied to the agent |
| `timeout_seconds` | Positive integer, default 600; maximum 3600 |
| `smoke` | Include this fixture in the smoke subset |
| `human_required` | Completion remains pending until subjective grading is imported |
| `acceptance` | Explicit observable requirements for the grader and reviewer |
| `rubric` | Five boolean grading dimensions, described below |
| `checks` | One or more independent objective checks |
| `references_dir` | Optional private passing/failing examples; never supplied to the agent |

All manifest paths are relative to the manifest directory, must stay within it,
and must not contain symlinks or `..`. The loader returns absolute paths plus source
and fixture SHA-256 digests. Fixture digests cover the task specification, starting
files, and independent Python evaluator contents.

Supported objective checks:

```json
[
  {"kind": "python", "name": "behavior", "script": "my_task/private/evaluator.py"},
  {"kind": "unchanged", "name": "preserve_contract", "paths": ["CONTRACT.md"], "no_extra_files": true},
  {"kind": "required_files", "name": "deliverable_exists", "paths": ["report.md"]}
]
```

`unchanged.paths` and `required_files.paths` are relative to `source_dir`/the final
artifact, not the manifest. `no_extra_files` rejects files added outside the starting
file inventory, while permitting edits to starting files not listed in `paths`.
Python scripts are trusted evaluator code. Each defines
`checks(root: Path, answer: str)` and returns a list of `(name, zero_argument_callable)`
pairs. A callable succeeds by returning normally and fails by raising an exception.
The evaluator imports generated code only in a bounded child process, with a small
environment and a disposable copy of frozen artifacts. It must exercise product
behavior directly; it must not rely on generated tests as correctness evidence.

The grader is process isolation, **not a security sandbox** for malicious code.
Only trusted fixture/evaluator authors should add manifests. Runtime code from the
evaluated agent is executed to validate behavior. No authentication environment
variables are forwarded to the grader. Size limits are 10 MiB per artifact file and
50 MiB total, plus bounded child output and a ten-second grading timeout.

## Human review

Every fixture includes descriptions for `correctness`, `completeness`, `scope`,
`unsupported_claims`, and `unnecessary_intervention`. The first three use `true` for
pass; the last two use `true` to flag an issue. A fully passing reference uses
`true, true, true, false, false`. An unanswered review stays pending in the runner.
Subjective claims are never scored by keyword or regular-expression matching.

The six subjective fixtures have objective checks for file preservation or the
exact requested documentation edit. Passing these checks means only that the
objective constraints passed. Semantic quality still needs a human review.

Each `private/references/{passing,failing}/` directory contains `files/`,
`final_answer.txt`, and `ratings.json`. Failing examples deliberately violate an
objective constraint as well as the human rubric. Offline tests verify both sides
of every fixture and separately verify that incorrect prose is not accepted as a
completed subjective success merely because files are unchanged.

## Adding real tasks

Create a new task directory and add an entry to the manifest. Put only starting
project files in `source/`; put graders and example outcomes in `private/`. State
all tested contracts in the prompt or supplied files. Include a known passing
artifact and a deliberately wrong artifact that fails for a meaningful reason.
Use `human_required: true` whenever automated checks cannot establish the requested
outcome. Keep fixtures offline and pin any external project snapshot before use.
Avoid shipping secrets, personal configuration, or third-party account access.

Run `python3 -m unittest test_e2e_fixtures -v` for the shipped suite's offline checks.
