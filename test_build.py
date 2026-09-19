#!/usr/bin/env python3
"""Consistency check for the generated pack. Run after build.py; install.sh runs it for you."""
import pathlib
import re

import build

ROOT = pathlib.Path(__file__).parent


def main():
    roles = build.main()
    ids = {r["id"] for r in roles}
    slugs = [r["slug"] for r in roles]

    assert len(slugs) == len(set(slugs)), "duplicate slug"
    assert len(ids) == len(roles), "duplicate id"

    for r in roles:
        assert (build.ROLES / f"{r['id']}.md").exists(), f"missing role file for {r['id']}"
        for field in ("name", "summary", "use_when", "not_for"):
            assert r[field].strip(), f"{r['id']}: empty {field}"
            assert '"' not in r[field], f"{r['id']}: quote inside frontmatter {field}"
        assert r["tags"], f"{r['id']}: no tags"

    skill = (build.SKILL / "SKILL.md").read_text()
    assert "{{" not in skill, "unreplaced placeholder in SKILL.md"
    assert set(re.findall(r"^### `([a-z0-9-]+)`", skill, re.M)) == ids, "SKILL.md catalog != role files"

    cmds = sorted(build.CMDS.glob("agent-*.md"))
    assert len(cmds) == len(roles), f"{len(cmds)} commands for {len(roles)} roles"
    for c in cmds:
        body = c.read_text()
        m = re.search(r"roles/([a-z0-9-]+)\.md", body)
        assert m and m.group(1) in ids, f"{c.name} points at a role that does not exist"
        assert c.stem == f"agent-{next(r['slug'] for r in roles if r['id'] == m.group(1))}"

    hook = (build.HOOKS / "agent-dispatcher-activate.sh").read_text()
    assert set(re.findall(r"^- `([a-z0-9-]+)`", hook, re.M)) == ids, "hook index != role files"

    readme = (ROOT / "README.md").read_text()
    assert readme.count("<!-- roles:start -->") == 1 and readme.count("<!-- roles:end -->") == 1
    table = readme.split("<!-- roles:start -->")[1].split("<!-- roles:end -->")[0]
    assert set(re.findall(r"`/agent-([a-z0-9-]+)`", table)) == set(slugs), "README table != commands"

    assert str(len(roles)) in readme.split("<!-- roles:start -->")[0], (
        f"README prose does not mention the real role count ({len(roles)})")
    for stale in re.findall(r"one of (\d+) specialist|The (\d+) roles", readme):
        n = next(v for v in stale if v)
        assert int(n) == len(roles), f"README says {n} roles, there are {len(roles)}"

    print(f"ok — {len(roles)} roles, {len(cmds)} commands, hook and README all agree")


if __name__ == "__main__":
    main()
