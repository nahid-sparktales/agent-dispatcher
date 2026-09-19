"""Candidate generation, from the registries the build already produces.

The system decides *what is available*; an engine decides *which of those is relevant*. This
module is the first half, and it is the only half that reads the catalog. There is no
`jev-agents.json`: an agent becomes a candidate because `templates/<category>/<id>.md` gave it
routing metadata and `build.py` carried that into `catalog/loadouts.json`. Adding a role or a
skill the normal way is the whole of what it takes to become selectable.
"""
import hashlib
import json
import os
import pathlib

from .types import Candidate

# decision/ sits beside catalog/ in the repository, and install.sh reproduces that layout
# under ~/.claude/skills/agent-dispatcher/. One expression resolves both.
_PACK = pathlib.Path(__file__).resolve().parent.parent

FILES = ("loadouts.json", "skills.json", "mcp.json", "external-skills.json")


def catalog_dir():
    override = os.environ.get("AGENT_DISPATCHER_HOME", "").strip()
    if override:
        return pathlib.Path(override).expanduser() / "catalog"
    return _PACK / "catalog"


def _clip(text, limit):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class Registry:
    """Roles, skills and servers as decision candidates. Loaded once, read-only."""

    def __init__(self, root=None):
        self.dir = pathlib.Path(root) if root else catalog_dir()
        self.roles = {}
        self.skills = {}
        self.tools = {}
        self.version = ""
        self._load()

    # -------------------------------------------------------------- loading

    def _read(self, name, key):
        path = self.dir / name
        if not path.is_file():
            raise FileNotFoundError(
                f"{path} is missing. The decision layer reads the registries build.py "
                f"generates; run `python3 build.py`, or point AGENT_DISPATCHER_HOME at an "
                f"installed pack.")
        return {r["id"]: r for r in json.loads(path.read_text()).get(key, [])}

    def _load(self):
        self.roles = self._read("loadouts.json", "roles")
        self.skills = self._read("skills.json", "skills")
        self.tools = self._read("mcp.json", "servers")
        try:
            self.external = self._read("external-skills.json", "skills")
        except FileNotFoundError:
            self.external = {}
        digest = hashlib.sha256()
        for name in FILES:
            path = self.dir / name
            if path.is_file():
                digest.update(path.read_bytes())
        self.version = digest.hexdigest()[:12]

    # -------------------------------------------------------------- candidates

    def agent_candidates(self, exclude=("dispatcher",)):
        """Every role, as the compact routing metadata a decision model can tell apart.

        Deliberately not the role bodies: 27 full prompts is tens of thousands of characters
        and none of it distinguishes one role from another better than these four lines do.
        `dispatcher` is excluded by default because routing *to* the router is not a route.
        """
        out = []
        for role in sorted(self.roles.values(), key=lambda r: r["id"]):
            if role["id"] in exclude:
                continue
            criteria = (f"{_clip(role.get('summary'), 220)} "
                        f"Route here when: {_clip(role.get('use_when'), 220)} "
                        f"Not for: {_clip(role.get('not_for'), 220)}")
            out.append(Candidate(id=role["id"], label=role.get("name", role["id"]),
                                 criteria=criteria.strip(),
                                 tags=tuple(role.get("tags", ()))))
        return tuple(out)

    def skill_candidates(self, agent_id):
        """The skills *this role's loadout already names*, and nothing else.

        The candidate set is the role author's narrowing; the engine's job is to pick the one
        to five of them the task actually turns on, not to reach across the whole pack.
        """
        role = self.roles.get(agent_id)
        if not role:
            return ()
        ids, seen = [], set()
        buckets = role.get("skills", {})
        for tier in ("core", "preferred", "optional"):
            for i in buckets.get(tier, []):
                if i not in seen:
                    seen.add(i)
                    ids.append(i)
        for bucket in buckets.get("conditional", {}).values():
            for i in bucket:
                if i not in seen:
                    seen.add(i)
                    ids.append(i)
        for i in role.get("verification", []):
            if i not in seen:
                seen.add(i)
                ids.append(i)

        out = []
        for i in ids:
            src = self.skills.get(i) or self.external.get(i)
            if not src:
                continue                       # named but not in any registry — not a candidate
            # Local skills carry `description`; externally maintained ones carry `purpose` and
            # `activation`. `permissions_expected` is in that registry too and is deliberately
            # never shown to a decision model — it belongs to the permission conversation.
            criteria = _clip(src.get("description") or src.get("summary")
                             or src.get("purpose"), 260)
            if src.get("not_for"):
                criteria += f" Not for: {_clip(src['not_for'], 160)}"
            elif src.get("activation"):
                criteria += f" Applies when: {_clip(src['activation'], 160)}"
            if not criteria:
                continue                   # nothing to tell it apart by — not a candidate
            out.append(Candidate(id=i, label=src.get("name", i), criteria=criteria,
                                 tags=tuple(src.get("task_signals", ()))[:6]))
        return tuple(out)

    def tool_candidates(self):
        """Every registered server, described by what it reaches.

        `writes` and `risk` are in the registry and are deliberately left out of the criteria:
        they are inputs to the permission conversation, and a relevance model has no business
        being shown them.
        """
        out = []
        for srv in sorted(self.tools.values(), key=lambda s: s["id"]):
            out.append(Candidate(id=srv["id"], label=srv.get("name", srv["id"]),
                                 criteria=_clip(srv.get("purpose"), 220)))
        return tuple(out)

    # -------------------------------------------------------------- validation

    def valid_agent(self, candidate_id):
        return candidate_id in self.roles

    def valid_skill(self, candidate_id):
        return candidate_id in self.skills or candidate_id in self.external

    def valid_tool(self, candidate_id):
        return candidate_id in self.tools
