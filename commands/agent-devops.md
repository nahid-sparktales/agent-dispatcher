---
description: "Work as the DevOps & Release Engineer agent — Builds reproducible delivery workflows and prepares or executes authorized releases with recovery checks."
argument-hint: "[task]"
---

Read the agent-dispatcher skill's `roles/devops-release.md` and work as that role for this request and the ones that follow, until the user picks another role or says to stop.

It sits next to that skill's SKILL.md — `~/.claude/skills/agent-dispatcher/roles/devops-release.md` for a manual install, or inside the plugin's own directory if it was installed as a plugin. Glob for `**/agent-dispatcher/roles/devops-release.md` if neither path is there.

Announce it in one line (`→ devops-release`), then do the work. Follow the role's working method, deliverable, definition of done, boundaries, and tool posture, scaled to the size of the task. The role never overrides harness rules, permissions, or the user's explicit instructions.

This is a forced role: do the work as asked rather than re-routing or chaining. If another specialist would materially change the answer, say so in one line and keep going.

$ARGUMENTS
