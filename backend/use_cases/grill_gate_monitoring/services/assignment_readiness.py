"""Readiness checks for live Grill Gate assignment zones."""
from __future__ import annotations


def missing_assignment_zones(zones: list[dict], *, mesh_required: bool) -> list[str]:
    enabled = {zone.get("zone_type") for zone in zones if zone.get("enabled", True)}
    required = {"gate_leaf_roi", "gate_approach", "gate_interior"}
    if mesh_required:
        required.add("mesh_area")
    return sorted(required - enabled)
