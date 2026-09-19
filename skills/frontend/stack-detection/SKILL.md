---
name: stack-detection
description: Establish what a frontend project actually uses — framework, router, package manager, styling, component layer, TypeScript posture — from package.json, lockfiles, config files and the source itself, before loading framework-specific guidance or writing a line of code. Fires at the start of any frontend task in an unfamiliar or half-remembered repo, and whenever you are about to assume a convention. Not for choosing a stack for a new project, and not a substitute for reading the code you are about to change.
---

# Stack detection

Most wrong frontend edits are correct code for a stack the project does not use. Detection is
cheap; guessing is not.

## When this fires

Before the first edit in a frontend repo you have not already mapped in this session, and again
whenever you catch yourself about to say "this project probably uses". It does not fire for a repo
whose conventions you have already read this session.

## Procedure

1. **Find the right `package.json` first.** In a monorepo the root one describes the workspace,
   not the app. Locate the nearest `package.json` above the file you are changing, and note
   whether a root one also exists — dependencies can be hoisted, tooling config usually is.
2. **Read dependencies and scripts together.** `dependencies` and `devDependencies` say what is
   installed; `scripts` say what is actually run. The dev, build and test commands are the ones to
   use later — do not invent `npm run dev` if the project spells it differently.
3. **Get real versions from the lockfile, not the range.** `^15.0.0` in `package.json` is a
   constraint. The lockfile (`package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lock*`) holds
   the resolved version, and its filename is also the only reliable statement of which package
   manager to invoke. Two lockfiles present is a finding, not a choice.
4. **Read the config files that exist, and note the ones that do not.** Build/framework config,
   TypeScript config, lint and format config, test config. Their presence tells you the tool is
   wired in; their contents tell you path aliases, strictness, and what is excluded.
5. **Confirm the routing and rendering model from the directory layout**, not from the framework
   name. Which route directories exist, where the entry file is, whether routes are file-based or
   declared in code, and — for frameworks with a server/client split — which files carry the
   directives that mark the boundary.
6. **Identify the styling layer and its version.** A config file's existence does not pin a major
   version; check the lockfile and how the stylesheet imports the framework. Also check for a CSS
   modules / styled-in-JS / vanilla CSS layer coexisting with it — mixed styling is common and
   changes what you should write.
7. **Check for a vendored component layer.** `components.json` or an equivalent marker plus a UI
   directory means components were copied in and are now project source (see `shadcn-ui`).
8. **Open two or three real source files** in the area you will touch. Config says what is
   possible; the source says what this team actually does — import style, file naming, test
   colocation, state library usage.
9. **Write the stack down in one short block, with the file each claim came from, and a separate
   list of what you could not determine.** That list is part of the result.

## What a signal does and does not license

- A framework in `dependencies` → the framework is installed. It does **not** tell you which
  router, rendering mode or directory convention is in use. Read the layout.
- A config file exists → that tool runs. It does **not** tell you the major version, and majors
  move config between files. The lockfile decides.
- TypeScript installed → files are typed. It does **not** mean `strict` is on, that `any` is
  discouraged, or that generated types are current. Read `tsconfig` and one real file.
- A test framework installed → tests can run. It does **not** mean they pass, cover this area, or
  are run in CI. Running them is a separate act.
- A state or data library installed → it is available somewhere. It does **not** mean the module
  you are editing uses it. Grep the directory you are in.
- `components.json` present → a component CLI was used at some point. It does **not** mean the
  components are unmodified, current, or the only UI layer.
- A lockfile entry → what would install. `node_modules` is what actually runs; if behaviour
  contradicts the lockfile, the installed tree is the tiebreaker.

## Checklist

- [ ] The `package.json` read is the one governing the file being changed
- [ ] Package manager identified from the lockfile, not from habit
- [ ] Framework and styling **versions** taken from the lockfile
- [ ] Routing/rendering model confirmed from the directory layout
- [ ] Dev, build and test commands quoted from `scripts`
- [ ] At least two real source files read for convention
- [ ] Unknowns written down rather than filled in by assumption

## Failure handling

- **No lockfile** — versions are unknown. Say so; do not resolve the range in your head. Behaviour
  that depends on a major version has to be checked against the installed tree or the docs.
- **Conflicting signals** (two lockfiles, a config for a tool that is not installed, a framework
  version that contradicts the layout) — report the conflict. Picking one silently makes you the
  source of the next bug.
- **Vendored or patched dependencies** (`patches/`, resolutions/overrides, a checked-in fork) —
  upstream documentation may not describe what runs here. Read the patch.
- **Detection disagrees with the user** — say what you found and where, then follow the user.
  Do not quietly rewrite their description of their own project.

## Evidence to report

A short stack block — package manager, framework and version, router/rendering model, styling
layer and version, component layer, TypeScript posture, test setup, dev/build/test commands — with
the file each line came from, followed by an explicit "not determined" list. A stack summary with
no file references is a guess with formatting.
