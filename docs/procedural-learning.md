# Procedural learning (optional, off by default)

Repository memory remembers **facts**: which files changed together, which commits touched a
symbol, which earlier task edited which paths. Procedural learning is about **procedures**: how
Dispatcher should work on this repository, and eventually on the user's other enrolled
repositories. It turns explicitly recorded task outcomes into reviewed, evaluated,
human-approved overlays on bundled guidance, and it can retire, correct and roll them back.

```text
explicit task observations and check receipts
  -> deterministic pattern review (or a host/provider-assisted proposal from a sanitized packet)
  -> immutable, scoped candidate revision
  -> Tier A structural/security validation
  -> Tier B component checks, Tier C paired evaluation against a frozen incumbent
  -> human approval bound to the exact candidate, evaluation, bundle and generation
  -> atomic publication of a new active generation
  -> bounded runtime composition; correction, retirement, rollback
```

Nothing here trains or fine-tunes a model. Nothing observes a session or reads a conversation.
A learned artifact is lower-priority guidance with **no authority**: it cannot change credential
redaction, path admission, permissions, required verification, provider settings, or this
admission policy, and the host's permission layer is exactly what it was. Owner-only files,
content hashes and approval records establish provenance and integrity; none of them establishes
that a sentence of prose is true or harmless, and none of them can sandbox a malicious process
running as the same user. The host must still enforce filesystem, execution, network and
secret-access permissions.

## Defaults, modes and switches

Settings live in the user's own file, `~/.config/agent-dispatcher/procedural-learning.json`
(or `AGENT_DISPATCHER_LEARNING_CONFIG`; an absolute `XDG_CONFIG_HOME` moves the default). A file
inside the inspected project is refused, and an environment override gets the same location
check. `learning configure` is the only writer.

| Setting | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Off: nothing is recorded, reviewed or composed; packets are byte-for-byte unchanged |
| `mode` | `shadow` | `shadow` reports eligible overlays and proposals without emitting anything; `active` composes admitted overlays |
| `observation.record` | `false` | Whether `learning observe` may store observations (opt-in, separate from experience recording) |
| `kinds` | all five | Which artifact kinds may be proposed and composed |
| `review` | 20 / 5 / 3 | Observations before a review is due; independent task families per pattern; candidates per review (operational defaults, not statistical claims) |
| `proposals.host_assisted` | `true` | Emit a sanitized review packet for the already authorized host session |
| `proposals.provider.enabled` | `false` | Purpose-specific provider calls with their own budgets; an LLM retrieval key never authorizes them |
| `budget` | 3 overlays, min(600 tokens, 10% of the packet) | Runtime ceilings for added guidance |
| `evaluation` | 30 families, 3 blocks, 0.05 threshold, no margin | Screening minimums and the practical threshold; an efficiency margin must be set explicitly |
| `approval.policy` | `human` | The only policy in this release; automatic promotion does not ship |
| `canary` | 20 tasks, 30 days | Ceilings for canary rollouts and experimental canaries |
| `profile` | `null` | The user-local profile whose admitted global overlays this repository may consume |

Canary is a per-revision rollout bound to a task count and expiry, never a mode. When learning is
enabled but no store or no applicable admitted overlay exists, packets are the baseline packets;
`learning explain` and `learning status` show the explicit empty state.

```bash
python3 -B learning.py configure --enable --mode shadow --record-observations on
python3 -B learning.py status --project . --json
python3 -B learning.py explain --task 'Fix the failing regression in validate_token' --role debugger --project .
```

The same commands are reachable as `repository_intelligence.py learning ...`, through
`/agent-learning` (Claude) and `$agent-dispatcher learning` (Codex), which read the shared
`LEARNING.md` guide.

## What is recorded, what stays unknown, what is never collected

Experience recording is unchanged: `repository_memory.py record` (or
`repository_intelligence.py experience record`) stores the bounded event and returns a
`record_id`. A learning **observation** is a separate, opt-in side record keyed to that event
(`learning observe --event RECORD_ID --observation-file -`). It carries, with strict unknown-field
rejection and size limits:

- task and family identity (a harness-supplied `task_family`, else a fingerprint of the request's
  strongest terms, so repeated trials and paraphrases do not count twice);
- baseline and final snapshot fingerprints (head, dirty state, tree digest) when the host has them;
- the package digest, effective-guidance digest, active generation and available revisions;
- per-revision exposure: `eligible`, `selected`, `emitted`, `host_confirmed_read`,
  `reported_applied` or `unknown`; these are never equated;
- observed workflow steps, registered check ids and bounded retrieval decisions
  (`history_expansion: used | unavailable | not_applicable | unknown`);
- failure categories from a fixed vocabulary, the experience outcome and its receipt summary,
  user acceptance kept apart from checks, test-change and correction flags;
- resources as `{value, provenance}` where provenance is `measured`, `estimated` or
  `unavailable`; an unknown value is `null`, never `0`;
- a `feedback_class`: `user_host`, `development_evaluation`, `synthetic_fixture` or
  `hidden_grader`. Synthetic fixture evidence can never support a production candidate, and
  hidden-grader feedback is labeled oracle-adjacent wherever it is counted.

Never collected: raw transcripts, hidden reasoning, unrestricted terminal logs, task prose beyond
the experience event's scrubbed 240-character summary, receipts' raw output, credentials.

## Artifact kinds and their slots

All five kinds share one lifecycle. Composition never edits bundled text: it appends one labeled
derived block anchored to a declared section, and removing that block restores the base bytes
(checked on every composition).

| Kind | Target | Evolvable slot(s) | Fixed |
| --- | --- | --- | --- |
| `skill_overlay` | a bundled skill | `repository_procedure`, `failure_branch`, `applicability_note`, `retrieval_hint` | identity, checklist, evidence to report, references |
| `role_method_overlay` | a role | `method_advice` (after WORKING METHOD) | ROLE, WHEN TO USE, DELIVERABLE, DEFINITION OF DONE, ROLE BOUNDARIES, tool posture: byte-identical or the composition fails closed |
| `recipe_overlay` | a recipe with a workflow sidecar | `workflow`: up to four optional steps inserted after declared anchors | every base step, its order, every gate and mandatory step |
| `retrieval_profile` | `retrieval` | an approved deterministic strategy and allowlisted parameters inside trusted ranges | providers, reranking, role summaries, explorer, caller caps, admission |
| `verification_hint` | `verification` | `order_first` and `add_checks` naming registered verification capabilities, plus a note | acceptance criteria; prose is never turned into a command |

The debug recipe has the first sidecar, `recipes/debug-application.workflow.json`: seven stable
step ids, three gates and the mandatory set `reproduce`, `fix`, `regression-test`,
`reproduce-again`. `build.py` validates the sidecar against the canonical Markdown (one step per
numbered step, each title quoted from it, one gate per bullet) so the two cannot drift silently.
The intended learned improvement sits between `gather-evidence` and `isolate`: an optional
"expand evidence with eligible commit history" branch with a condition and a documented fallback,
never a removed reproduction or a weakened gate.

Composition order is `bundled base + admitted global overlay + admitted repository specialization`.
A repository overlay records the global revision it was evaluated against; if the active global
revision differs, the specialization is omitted with `stale_base`. Two admitted overlays of one
scope on one slot are a `conflict` and both are omitted. A changed base artifact, a changed
package or a changed learning policy is `stale_base`. Contradictions are never blended at runtime.

## Runtime: what a packet gains

With `mode: active`, `context.py --compact` composes eligible overlays onto the guidance it already
read from the package. A composed role or guide body has `source: "derived"`, keeps
`base_sha256`, and lists its `layers`. Recipe additions and verification hints arrive under
`guidance.derived`. Retrieval profiles adjust the engine's settings before retrieval, within the
caller's own caps and never enabling a provider. `learning.overlays` explains every admitted
overlay with one of:

`disabled`, `shadow`, `not_applicable`, `not_approved`, `insufficient_evidence`, `stale_base`,
`revoked`, `conflict`, `budget_omitted`, `capability_unavailable`, `active`.

Added guidance has its own budget: at most three textual overlays and the smaller of 600 estimated
tokens or 10% of the packet target, accounted from the actual serialized packet including the
explanation itself. Overlays leave whole, lowest priority first; a packet that still cannot hold
protected content plus learned text drops every overlay before it fails. `learning.exposure` is
an ephemeral descriptor to copy into the observation; nothing is persisted by a read.

Runtime reads open the stores read-only, migrate nothing, write no counters and create no
directories (tested: the SQLite file's bytes and mtime are unchanged and no journal appears).
Context reuse keys include the active generation, emitted revisions, policy and package digests,
so evidence delivered under a revoked overlay set is a new delivery.

## Lifecycle

```text
proposed -> validated -> evaluating -> evaluation_passed -> awaiting_approval
         -> approved -> active | canary -> deprecated
proposed/validated/evaluating -> rejected | invalid | inconclusive | evaluation_failed
any live revision -> quarantined | revoked ; active -> rolled_back (atomic generation change)
validated + component checks passed -> awaiting_experiment_authorization -> experimental_canary -> evaluating
```

The state machine is controller-owned: a candidate document that carries `state`, `approved` or an
evaluation is rejected as a whole (unknown field). Revisions are immutable and content-addressed;
editing any material field is a new revision and invalidates earlier approvals and evaluations.

- **Review** (`learning review [--apply] [--packet]`): deterministic patterns over admitted
  evidence, failures included and deduplicated by task family; hypotheses need `min_support_families`
  independent families and list contradicting families; `no_change` and `insufficient_evidence` are
  first-class results. A severe failure (`security_concern`, `verification_bypass`) produces a
  warning immediately and quarantines an overlay that was emitted in that task; it never authorizes a
  replacement. `--packet` emits the sanitized host-assisted packet (counts, roles, event ids; no
  prose, paths, receipts, holdout answers or approval material).
- **Propose** (`learning propose --from-file -` or `--provider`): the document is untrusted data
  validated by `learning_compose.validate_candidate` (Tier A). Provider-assisted proposals reuse the
  existing provider boundary with explicit enablement, one budgeted call and no silent fallback.
- **Component checks** (`learning component-check`): Tier B, deterministic, never authoritative.
- **Evaluate** (`learning evaluate REVISION --spec SPEC.json --runner end_to_end_batch --batch DIR`):
  see below. `fake_test_runner` is test-only and its reports can never support a production approval.
- **Approve** (`learning approve REVISION --evaluation EVAL --authorize-as NAME --expected-generation GEN`):
  binds the exact candidate, a `passed` authoritative evaluation for that candidate, the composed
  bundle digest recomputed now, the policy digest, the incumbent generation and the rollout
  (`active` or `canary` with bounds). Dispatcher cannot authenticate a person: the record carries
  the label the user gave, the uid and login of the process, and relies on the host to decide who may
  run the command. A boolean, a repository file, a tool result or a model sentence is not approval.
- **Promote** (`learning promote REVISION --expected-generation GEN`): rechecks hashes, evaluation
  validity, policy, base compatibility, privacy classification and support withdrawal, then publishes
  a new generation with compare-and-swap in one transaction; a stale approval fails visibly.
- **Rollback** (`learning rollback --target-generation GEN|base --expected-generation GEN --authorize-as NAME`):
  restores a complete compatible generation, refusing one that contains revoked members or was
  published under another policy or base; `base` is the pristine bundled guidance.
- **Deprecate / revoke**: deprecation stops new selection and keeps history; revocation blocks new
  consumption immediately, takes provenance descendants with it (refine, merge, split, generalize,
  export and import all record inheritance) and republishes without them. Emitted instructions
  cannot be removed from a model's context; the host is told to reassess affected work.
- **Prune** (`--dry-run` default, `--apply`): retention-eligible inactive revisions past the age,
  ranked by state, observed use and age; payloads are deleted and a non-content tombstone remains.
- **Forget** (`--event ID` or `--revision ID`): removes observations or revisions and their
  descendants, suspends live dependents, and re-checks support. Experience corrections and
  forgetting are consulted, not copied: `learning sync` (and every review, promotion and runtime
  read) treats a forgotten or superseded supporting event as withdrawn support.

All deletion is logical deletion in a local SQLite file. Backups, provider copies and SQLite free
pages are outside these operations; no secure physical erasure is promised.

## Evaluation: three questions, three tiers

**Tier A** (structural/security) says the artifact is well-formed under the tested controls.
**Tier B** (component checks) says applicability fixtures, composition determinism, base
preservation, recipe gates, budget compliance and profile bounds hold. Neither says anything about
benefit. **Tier C** pairs incumbent and candidate on matched tasks under a frozen specification.

A specification is frozen before anything runs and bound to the candidate revision, the incumbent
generation, both composed-bundle digests, the policy and package digests, the runner and its
version, a fixed environment (model, effort, auth mode, CLI version, seed), disjoint data roles
(`discovery`, `development`, `admission_holdout`, `final_test`), arms, stopping rule and safety
gates. Discovery families that reappear in holdout or final-test roles make the evaluation
`invalid`.

Statistics are standard library only and deliberately conservative: repetitions collapse to one
pair per task family (they measure variability, not coverage); the primary interval is a
family-level paired bootstrap of the success-rate difference; an exact sign test and a Wald
interval on discordant families are reported beside it; paired resource deltas use a percentile
bootstrap; cross-family claims add a block bootstrap over repository or chronological blocks.
Every evaluation ends `passed`, `failed`, `inconclusive`, `invalid` or `not_run` with
machine-readable reasons. Minimum counts (30 families, 3 blocks by default) are only a screen: the
interval and coverage gates decide, no discordant pairs is `inconclusive`, and no flag turns an
inconclusive result into a win.

Two objectives: **correctness** passes when the lower confidence bound of the success difference
exceeds the practical threshold with no safety or verification regression; **efficiency** needs an
owner-chosen non-inferiority margin (reported in every result) plus a cost interval below zero.
Missing cost stays unknown. Missing model access is `not_run`, never a fabricated pass.

`end_to_end_batch` is the authoritative runner: it pairs completed trials of an
`evals/end_to_end` batch whose configuration fingerprint the spec names. No live agent evaluation
was run for this change; the harness support, the offline tests and the fixture demo are complete,
and no measured benefit is claimed.

## Global scope and transfer

Global means this user's private, explicitly enrolled multi-repository profile, never a shared
library and never the upstream package. `learning profile enroll --profile NAME [--consent-aggregate]`
records the repository's namespace (its private state directory id: resolved path, device and
inode, never a URL) in the profile store; `unenroll` stops new use of that repository's evidence
immediately and suspends global revisions that rested on it. Clones and forks are separate
namespaces but not independent evidence: `generalize` needs at least three independent enrolled
repository families with consent, refuses an aggregate one repository dominates, intersects
applicability, and rejects wording that names paths, URLs, long identifiers or any identifier from
the source repositories' private lexicons. `never_global` revisions are never generalized. Secret
redaction alone never makes repository text global.

Held-out transfer: `learning export-generation --output FILE` freezes the library;
`learning import-generation --from FILE --experiment ID --authorize-as NAME` installs it into an
isolated arm as an explicitly authorized experimental canary. The held-out repository contributes
no learning input, both arms index the same current source, and only the frozen library differs.
`learning export --output FILE` writes a sanitized review patch against canonical sources for
ordinary human code review; it modifies no installed file, publishes nothing, and an import
elsewhere starts as an untrusted candidate.

## Longitudinal experiments

The end-to-end runner keeps its default conditions and gains learned arms mapped onto the
conceptual ladder:

| Arm | Condition | Definition |
| --- | --- | --- |
| D0 | `baseline` | stock native client |
| D1 | `dispatcher` | static Dispatcher |
| D2 | `indexed` | plus the deep index (experience recorded, never used) |
| D3 | `warm_experience` | plus the repository-memory treatment its own earlier steps recorded |
| D4 | `learned_skills` | D3 plus repository skill overlays from a frozen, authorized library |
| D5 | `learned_recipes` | D4 plus recipe overlays |
| D6 | `learned_global` | D5 plus frozen user-global overlays |
| D7 | `learned_full` | the full bundle including role-method, retrieval-profile and verification-hint kinds |

Each learned arm has its own cache home, learning store, settings file (`active`, the arm's
`kinds`) and experience; the library is imported before a sequence's first step under the
configuration's `experiment_authorization`, and observations are recorded after each trial with
`feedback_class: hidden_grader` (oracle-adjacent, stated in the report). The ladder estimates
incremental bundle effects in that order; leave-one-component-out ablations are separate
configurations. See [evals/end_to_end/README.md](../evals/end_to_end/README.md).

## Offline demonstration

```bash
python3 -B evals/learning/demo.py
python3 -B -m tests.test_learning
python3 -B -m tests.test_learning_security
```

The demo runs the whole path on four synthetic repository families (three enrolled, one held out)
with real storage, validation, composition and lifecycle code in an isolated cache home: record
marked observations, review a recurring failure, import a repository proposal, reject a candidate
that removes verification, evaluate an admissible candidate with the labeled fake runner in a test
namespace, approve and promote there, show effective guidance changing only for matching tasks,
invalidate a dependency, roll back, generalize across independent families, prepare the held-out
transfer experiment, and forget a support event with descendant invalidation. Its negative
examples (do nothing, history irrelevant, cheaper but less correct recipe, duplicate families,
a global rule that harms the held-out family) are deliberate: the fixture is not engineered so
every change wins, and its synthetic marker keeps it out of any production library.

## Security matrix (what the tests cover)

Instruction poisoning in tasks, files, commit messages or imported documents is untrusted evidence:
executable or fetchable material and authority claims are refused at validation, and nothing in
observed content can approve, promote or configure. Inherited poisoning: descendants of a revoked
or quarantined parent cannot be proposed, and revoking a parent revokes its descendants.
Filesystem attacks go through repo_store's hardened opener (owner-only, regular 0600 file,
no-follow, bounded reads, unknown schema declined without repair). Forgery: candidate-supplied
approval or state fields are unknown fields; a tampered revision fails its digest; a stale base,
policy or generation fails approval and promotion; test-only reports are never authoritative.
Scope escapes: a repository overlay lives in its own namespace, an unenrolled repository cannot
feed a global candidate, a same-named artifact cannot impersonate a bundled skill (targets resolve
by registered id only), and no candidate can change a role, model, tool or provider. Budget and
availability failures fall back to the base without widening anything. Read-only commands leave
workspace and private state unchanged.

## Honest limits

- Prose lint is a filter, not a proof. Text that passes it is still only guidance under human
  approval and the host's permission layer.
- Success while an overlay was loaded is not causal benefit; observational patterns prioritize
  hypotheses, only paired controlled comparisons estimate utility, and only an authoritative Tier C
  evaluation can support a promotion.
- The deterministic review can synthesize verification hints and the history-expansion recipe branch
  from templates; other wording is requested from the host or a human rather than invented by rules.
- Hidden-grader outcomes are oracle-adjacent training feedback and are labeled as such.
- Dispatcher cannot authenticate the approving person; the host controls who runs the commands.
- No live agent evaluation has run for this feature, so no measured improvement is claimed.
