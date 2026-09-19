---
name: docker
description: Build container images that are reproducible, small, and safe to run — layer order and what actually caches, multi-stage builds, and what belongs in an image versus what must never be baked into one. Use when writing or reviewing a Dockerfile, when an image build is slow, bloated, or non-deterministic, or when deciding how configuration and secrets reach a container. Not for orchestration, cluster or compose topology, not for CI workflow authoring (github-actions), and not for pipeline stage design (ci-cd).
---

# Docker images

An image is a build artifact with a filesystem attached. Most of what goes wrong with one is
decided by the order of a dozen lines: what got cached, what got copied in that should not have
been, and what the container is running as when it starts.

A built image is not a running service. "The build succeeded" says the layers assembled, nothing
about whether the thing inside starts, serves, or shuts down.

## When this fires

A Dockerfile is being written, changed, or reviewed; a build is slow or gives different results on
different machines; an image is unexpectedly large; or config and credentials need a route into the
container. It does not fire for scheduling, networking between services, or a bug in the
application code that happens to be containerized.

## Procedure

1. **Read what exists first** — the Dockerfile, `.dockerignore`, and how the image is actually
   built (locally, in CI, with what build args). Most "write me a Dockerfile" tasks are really a
   fix to the one already there, and a second parallel Dockerfile is how two images drift.
2. **Choose the base deliberately and pin it.** Prefer the language's official image or a slim
   variant; pin to a digest when reproducibility matters, because a tag moves under you. Alpine
   and other musl-based images are smaller but are a different libc: native extensions, DNS
   behaviour, and timezone handling can all differ from what you tested on. Take the smaller base
   only when you have run the app on it.
3. **Write `.dockerignore` before you build.** Without one, the build context carries `.git`,
   `node_modules`, local env files, and build output to the daemon on every build — slow, and the
   direct cause of a credential ending up inside an image after a broad copy.
4. **Order instructions by rate of change**, slowest first: system packages, then dependency
   manifests plus the install, then application source last. Copy the manifest and lockfile alone
   before the source, so a source edit does not invalidate the dependency layer. Any instruction
   invalidates every layer after it — this ordering is the whole of build caching.
5. **Use a multi-stage build** so compilers, dev dependencies, and test tooling never reach the
   runtime image. Build in one stage, copy only the produced artifact into a clean runtime stage.
   This is usually the single largest size reduction available, and it shrinks the attack surface
   at the same time.
6. **Keep secrets out of the image entirely.** A build argument or environment variable set at
   build time is recorded in image metadata. Copying a secret in and deleting it later does not
   remove it — the earlier layer still holds it. Use BuildKit's build-time secret mounts, or fetch
   the credential at runtime. If a secret was ever baked into an image that has been pushed
   anywhere, that is a leaked credential: stop, say so plainly, and treat rotation as the fix.
7. **Install packages in one layer and clean up in the same instruction.** Splitting the index
   update from the install lets a stale cached index install stale packages; leaving package
   manager caches behind inflates the layer permanently, because deleting them later only adds
   another layer. Use a build cache mount for package caches you want to reuse across builds.
8. **Run as a non-root user.** Create the user, give it ownership of only the paths it must write,
   and set `USER` before the entrypoint. Containers run as root by default and almost nothing needs
   it. If the process must bind a low port, change the port rather than keeping root.
9. **Get PID 1 right.** Use the exec form of the entrypoint and command so your process is PID 1
   and receives signals directly. In shell form the shell is PID 1, `SIGTERM` is not forwarded, and
   the container is killed hard after the grace period — no graceful shutdown, no connection
   draining, and it looks fine locally. Add a minimal init process when the app spawns children it
   does not reap.
10. **Take configuration at run time, not build time.** An image that bakes in an environment's
    URLs or feature flags is one image per environment, which breaks build-once-promote: what you
    tested is not what you ship. Bake only what is genuinely invariant.
11. **Build it, then look at it.** Build clean, then build again unchanged and confirm the cache
    behaves as the ordering predicts. Inspect the layer sizes and the final size against the
    previous one. Then **run it**: confirm it starts, serves a real request, exits within a second
    or two on `SIGTERM`, and does so as the non-root user.
12. **Scan before it goes anywhere**, and stop there. Pushing to a registry, moving a shared tag
    such as `latest`, and pruning images or volumes on a machine you do not own are all outward or
    destructive: prepare them, say exactly what would be pushed or removed, and ask.

## Checklist

- [ ] `.dockerignore` exists and excludes VCS, local dependencies, env files, and build output
- [ ] Base image pinned; its libc is one the application has actually run on
- [ ] Dependency install sits above the source copy, and a source edit reuses it
- [ ] Build tooling exists only in a build stage, not in the runtime image
- [ ] No secret in a build arg, an env var, or any layer — checked, not assumed
- [ ] Explicit non-root `USER`, with ownership of the paths it writes
- [ ] Exec-form entrypoint; container observed exiting promptly on `SIGTERM`
- [ ] Environment-specific config supplied at run time
- [ ] Image built, run, and exercised — not just built

## Failure handling

- **The cache never hits.** Something high in the file changes every build: a broad `COPY` above
  the dependency install, a timestamp or commit SHA in an early build arg, or a missing
  `.dockerignore` letting the context differ each time. Find the first layer that rebuilds; the
  cause is at or above it.
- **It works locally and fails in CI.** Suspect, in order: an unpinned base tag that moved, a file
  present locally but ignored or absent in the CI context, a different architecture, and build args
  supplied in one place only. Compare the two build contexts before changing the Dockerfile.
- **The image is still huge after a multi-stage build.** Layer size, not final content, is what
  counts: a file added and removed in a later instruction is still carried. Look at per-layer sizes
  and find the fat one rather than guessing.
- **The container exits immediately.** Read its logs before editing anything. A foreground process
  that backgrounds itself, a missing runtime dependency dropped between stages, and a permission
  error after adding `USER` all present the same way.
- **No way to build or run here.** Say the image was written but never built, and never describe it
  as working. A Dockerfile that has not been built is a draft.

## Evidence to report

The final image size and how it compares to before. The result of the second, unchanged build —
which layers were cached. What the container did when run: startup, one real request served, and
the observed shutdown on `SIGTERM`. The user id the process runs as. Scanner findings, with
severities, or a statement that no scan was run. And what was not checked — other architectures,
other environments, and registry push, if the push has not happened.
