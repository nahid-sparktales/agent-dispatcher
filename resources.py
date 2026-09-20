"""Read trusted package resource locations; never import code from the project."""
import json
from pathlib import Path, PurePosixPath


def _read(path):
    with path.open("rb") as handle:
        raw = handle.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Package metadata exceeds its limit.")
    return json.loads(raw)


def resolve_resources(pack, role):
    """Return locations and candidate metadata, never selections or authorization."""
    base = Path(pack).resolve()
    catalog = base / "catalog"
    if (base / "scripts/runtime/catalog").is_dir():
        catalog = base / "scripts/runtime/catalog"
    result = {"source": "dispatcher_package", "role": None, "guides": [], "conditions": {},
              "diagnostics": []}
    if role is None:
        return result
    try:
        manifest = _read(catalog / "resource-paths.json")
        if manifest.get("schema_version") != 1:
            raise ValueError()
        roles = _read(catalog / "loadouts.json")["roles"]
        selected = next(r for r in roles if role in (r["id"], r.get("slug")))
        signals = _read(catalog / "signals.json")["signals"]
        if isinstance(signals, list):
            signals = {s["id"]: s for s in signals}

        def location(kind, ident):
            relative = manifest[kind].get(ident)
            if not isinstance(relative, str):
                return None
            path = PurePosixPath(relative)
            if path.is_absolute() or ".." in path.parts or "\\" in relative:
                raise ValueError()
            target = (base / relative).resolve()
            if not target.is_relative_to(base) or not target.is_file():
                return None
            return str(target)

        result["role"] = {"id": selected["id"], "path": location("roles", selected["id"])}
        candidates = {}
        for tier in ("core", "preferred", "optional"):
            for ident in selected["skills"][tier]:
                candidates.setdefault(ident, {"id": ident, "tiers": [], "conditions": []})["tiers"].append(tier)
        for condition, ids in selected["skills"]["conditional"].items():
            result["conditions"][condition] = signals[condition]["summary"]
            for ident in ids:
                candidates.setdefault(ident, {"id": ident, "tiers": [], "conditions": []})["conditions"].append(condition)
        for ident in selected["verification"]:
            candidates.setdefault(ident, {"id": ident, "tiers": [], "conditions": []})["tiers"].append("verification")
        for ident, item in candidates.items():
            local = ident in manifest["guides"]
            item.update(path=location("guides", ident) if local else None,
                        status="bundled" if local else "external_availability_unknown")
            if local and item["path"] is None:
                item["status"] = "unavailable"
            result["guides"].append(item)
        if result["role"]["path"] is None:
            result["diagnostics"].append("Selected role file is unavailable; repair the package.")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, StopIteration, RecursionError):
        return dict(result, role=None, guides=[], conditions={}, diagnostics=[
            "Package resource metadata unavailable; use the selected role's documented fallback."])
    return result
