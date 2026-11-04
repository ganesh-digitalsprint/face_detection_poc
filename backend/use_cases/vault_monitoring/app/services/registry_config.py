"""Use-case and zone-type metadata loaded from the deployed YAML config."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "use_cases"


@lru_cache(maxsize=1)
def _manifest() -> tuple[dict, ...]:
    path = CONFIG_DIR / "registry.yaml"
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"Cannot load use-case registry configuration: {path}") from exc
    items = value.get("use_cases") if isinstance(value, dict) else None
    if not isinstance(items, list) or not items:
        raise RuntimeError("use_cases/registry.yaml must define a non-empty use_cases list")
    ids = [item.get("id") for item in items if isinstance(item, dict)]
    if len(ids) != len(items) or len(ids) != len(set(ids)):
        raise RuntimeError("Use-case ids must be present and unique")
    return tuple(items)


def clear_use_case_config_cache() -> None:
    _manifest.cache_clear()


def get_use_case(use_case: str) -> dict | None:
    return next((dict(item) for item in _manifest() if item["id"] == use_case), None)


def list_use_cases() -> list[dict]:
    result = []
    for item in _manifest():
        zone_types = load_zone_types(item["id"])
        result.append({"id": item["id"], "frontend_id": item["frontend_id"],
                       "label": item["label"], "zone_types": zone_types})
    return result


@lru_cache(maxsize=16)
def load_zone_types(use_case: str) -> tuple[dict, ...]:
    item = get_use_case(use_case)
    if item is None:
        raise KeyError(use_case)
    relative = Path(item["zone_types_file"])
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"Invalid zone_types_file for use case {use_case}")
    path = (CONFIG_DIR / relative).resolve()
    if CONFIG_DIR.resolve() not in path.parents:
        raise RuntimeError(f"Invalid zone_types_file for use case {use_case}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"Cannot load zone type configuration for use case {use_case}") from exc
    types = data.get("zone_types") if isinstance(data, dict) else None
    if not isinstance(types, list):
        raise RuntimeError(f"{path} must contain a zone_types list")
    keys = [entry.get("key") for entry in types if isinstance(entry, dict)]
    if len(keys) != len(types) or len(keys) != len(set(keys)):
        raise RuntimeError(f"Zone type keys must be present and unique for {use_case}")
    for entry in types:
        if set(entry) - {"key", "label", "description"} or not all(isinstance(entry.get(k), str) for k in ("key", "label", "description")):
            raise RuntimeError(f"Invalid zone type entry for {use_case}")
    return tuple(dict(entry) for entry in types)


def annotate_zone_type(use_case: str, zone_type: str | None) -> dict:
    known = {item["key"] for item in load_zone_types(use_case)}
    return {"zone_type": zone_type, "type_unknown": bool(zone_type and zone_type not in known)}
