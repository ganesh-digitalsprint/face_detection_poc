"""Vault-room zone definition, geometry and occupancy tracking."""

from app.core.zones.vault_room_zone import (
    DEFAULT_ZONES_FILE,
    REFERENCES,
    Zone,
    ZoneConfigError,
    ZoneEvent,
    ZoneFile,
    ZoneMonitor,
    load_zones,
    point_in_polygon,
    reference_point,
    save_zones,
    validate_polygon,
    zone_from_dict,
)

__all__ = [
    "DEFAULT_ZONES_FILE",
    "REFERENCES",
    "Zone",
    "ZoneConfigError",
    "ZoneEvent",
    "ZoneFile",
    "ZoneMonitor",
    "load_zones",
    "point_in_polygon",
    "reference_point",
    "save_zones",
    "validate_polygon",
    "zone_from_dict",
]
