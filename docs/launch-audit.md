# Public launch audit — 2026-09-19

Audit baseline: `f6dc177`. The launch fixes and CI were published in `577262b`.
This was a targeted review of distribution, installation/removal, generated artifacts, decision
configuration, API transport, repository hygiene, and GitHub release controls. It does not prove
the quality of every role or reverify every third-party catalog entry.

## Findings addressed

| Area | Reproduction and consequence | Change and evidence |
| --- | --- | --- |
| Installer preflight | Valid JSON such as `[]` or an invalid `hooks` shape passed the old JSON-only check, then failed after installation changes. | Validate settings structure before mutations; regression checks existing files remain intact on both install and uninstall. |
| Installer ownership | The manifest could name any file, and uninstall also deleted unowned commands by matching their prose. Hooks were removed by substring. | Restrict manifest entries to owned command paths, reject symlinked targets, remove the prose fallback, and match exact hook commands. Tests preserve unrelated files and shared hook entries. |
| Hook registration | Double-quoted config paths allowed shell expansion, and switching quoting without migration would register an extra hook during updates. | Shell-quote paths and migrate the previous registration. The full lifecycle test executes the registered command with a shell-special config path and checks that no injected command ran. |
| Decision settings | `[]`, `null`, invalid text encoding, and non-finite task limits could fail; the string `"false"` enabled a scope. | Ignore invalid ambient input, require real booleans, and bound numeric values. Explicit invalid settings raise errors. |
| Provider endpoint | A URL shaped as `http://localhost:80@example.invalid` passed the old loopback test despite naming a remote host. The override comes from the user's environment, not a project file. | Parse scheme, hostname, credentials, and port; accept HTTP only for exact loopback hosts and reject ambiguous URLs before transport. |
| Transport diagnostics | An underlying URL error could quote a credential in its reason, contradicting the provider's error-safety guarantee. | Replace transport-supplied reasons with a fixed error and test with a synthetic credential. |
| Generated-file drift | Missing generated files were recreated without causing the comparison to fail. | Compare the before/after path sets and content, including absent artifacts. A regression deletes a command and a registry and requires validation to fail. |
| Documentation | Config precedence and the claimed overall response deadline disagreed with the code. | Document environment-over-project precedence and the actual timeout limitation. |

## CI delivered

- **CI:** pushes to `main`, version tags, pull requests, merge queues, and manual runs. Python
  3.10–3.14 on Ubuntu plus 3.14 on macOS; existing, release, and Codex suites; a clean
  checkout after generation; ShellCheck and actionlint. The stable aggregate check is `CI passed`.
- **Security:** the same change events plus a weekly scan. Gitleaks scans full fetched history
  and current files with redacted output. `Secret scan` works while the repository is private.
  CodeQL scans Python and GitHub Actions when the repository is public.
- **Dependency maintenance:** Dependabot opens weekly updates for commit-pinned Actions.
  Gitleaks/actionlint downloads have explicit version and SHA-256 pins, maintained together.
- **Permissions:** read-only checkout tokens without persisted credentials; CodeQL alone gets
  security-event write permission. No deployment credentials, API keys, or paid model calls.
  Workflows use `pull_request`, not privileged execution of contributor code.

The permission and pinning choices follow [GitHub's secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use).

## Validation

- Both original suites pass: 27 roles, 79 local skills, 31 external entries, 8 recipes, 19 MCP
  entries, 50 signals; 162 routing, 24 skill-selection, and 20 tool-selection fixtures.
- All 13 release regression tests pass, including a real install, legacy-registration update,
  installed decision CLI invocation, hook execution, and uninstall in temporary directories.
- ShellCheck 0.11.0, actionlint 1.7.12, Bash syntax checks, and Claude Code's plugin and
  marketplace manifest validators pass locally.
- Gitleaks 8.30.1 found no leaks in the available Git history or current files. This is a scan
  result, not a guarantee that every kind of sensitive information is absent.
- Local execution used macOS and Python 3.14.6. Hosted CI and Secret scan passed for `577262b`,
  including every Linux/Python and macOS job. CodeQL was skipped while the repository remained
  private. No live TypeSafe call was made.
- The subsequent Codex adapter adds offline packaging, installer, routing, and activation
  regressions. Native skill discovery passed against Codex CLI `0.155.0-alpha.2.6`; the runtime
  discovered one dispatcher and no supporting guides as separate skills. This is discovery
  validation, not a live model test or proof that a user has trusted the optional hook.

## Remaining launch steps and limits

1. **Publish the repository when ready.** The reviewed changes passed hosted checks; the repository was private at
   audit time. Its existing default Actions token is read-only and cannot approve PRs. Making
   it public is a separate publication decision; this audit does not change visibility.
2. **Protect `main` after the checks exist.** Require `CI passed` and `Secret scan`, prevent
   force pushes/deletion, and require review according to the maintainer's workflow. GitHub's
   rules API returned a plan/visibility restriction for this private repository, so protection
   could not be verified. Avoid requiring the conditionally skipped CodeQL job while private.
3. **Enable private vulnerability reporting at launch.** The reporting API returned 404 while
   private. Confirm the reporting form works after publication; `SECURITY.md` now includes a
   fallback that does not request public disclosure. See [GitHub's reporting setup](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).
4. **Review CodeQL alerts after its first public run.** Uploading analysis is not itself a
   guarantee of zero findings. Add a code-scanning merge rule if that is the intended policy.
5. **Run one authenticated Claude Code task from a fresh plugin install.** Manifest validation
   and direct hook execution passed; actual task routing, plugin updates, and uninstall through
   an authenticated Claude session were not exercised. Native Windows is outside the CI matrix.
6. **Keep the optional API limitations explicit.** Jev remains disabled by default. A project
   config with boolean scopes can opt into requests when a credential is present; inspect that
   file in unfamiliar repositories, or set `AGENT_DISPATCHER_OFFLINE=1`. Redaction is best-effort,
   and a slow response can outlive the socket timeout. Strict service deadlines need an outer
   process deadline. These limits are documented in the Jev guide.
7. **Confirm content provenance before announcing the license grant.** MIT metadata and the
   provenance notice are present and consistent. This audit did not independently reconstruct
   the source screenshots/template pack described in `NOTICE` or establish third-party rights.
