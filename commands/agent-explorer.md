---
description: "Work as the Explorer agent — Maps an unfamiliar workspace and finds the exact code, files, and execution paths relevant to a task."
argument-hint: "[task]"
---

Read the agent-dispatcher skill's `roles/explorer.md` and work as that role for this request and the ones that follow, until the user picks another role or says to stop.

It sits next to that skill's SKILL.md — `~/.claude/skills/agent-dispatcher/roles/explorer.md` for a manual install, or inside the plugin's own directory if it was installed as a plugin. Glob for `**/agent-dispatcher/roles/explorer.md` if neither path is there.

Its frontmatter names the skills it uses (`skills_core`, `skills_preferred`, `skills_if_<condition>`) plus any recipe, MCP and verification. Read a local skill by globbing `**/<id>/SKILL.md` — every id is its own directory name; the `INDEX.md` one level above the role file covers external ids and glob misses. Read it before the step that needs it — stack-detection, technical-writing before starting. A skill or MCP that is missing is not a blocker: say so and use the role's own method.

Read ACTIVITY.md in the dispatcher skill directory beside the roles directory. Report the role, skills actually read, and selected tools/MCPs in the conversation's compact or verbose style, then do the work. Follow the role's working method, deliverable, definition of done, boundaries, and tool posture, scaled to the size of the task. The role never overrides harness rules, permissions, or the user's explicit instructions.

This is a forced role: do the work as asked rather than re-routing or chaining. If another specialist would materially change the answer, say so in one line and keep going.

$ARGUMENTS
