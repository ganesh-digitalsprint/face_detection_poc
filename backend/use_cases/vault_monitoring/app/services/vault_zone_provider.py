"""Use-case-specific Vault zone storage; session code consumes immutable snapshots."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from app.core.ml_config import get_vault_room_config
from app.core.zones.vault_room_zone import DEFAULT_ZONES_FILE, Zone, ZoneConfigError, ZoneFile, load_zones
from app.db.database import session_scope
from app.db.models.camera_registry import CameraUseCaseAssignment, RegistryCamera, RegistryLocation, RegistryZone

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ZoneSnapshot:
    zones: tuple[Zone, ...]
    assignment_id: str | None
    location_id: str | None
    camera_id: str | None
    use_case: str = "vault_room"

    def identity(self) -> dict | None:
        if not self.assignment_id:
            return None
        return {"use_case": self.use_case, "location_id": self.location_id,
                "camera_id": self.camera_id, "assignment_id": self.assignment_id}


class VaultRoomZoneProvider:
    """Loads Vault zones only when asked at session start, never from process_frame."""

    def __init__(self, zone_file: ZoneFile | None = None):
        self.zone_file = zone_file or ZoneFile()
        self.active_identity: dict | None = None
        self.last_source = "file"

    @staticmethod
    def _resolve_assignment(db):
        config = get_vault_room_config()
        configured = config.active_assignment
        stmt = select(CameraUseCaseAssignment, RegistryCamera, RegistryLocation).join(
            RegistryCamera, RegistryCamera.id == CameraUseCaseAssignment.camera_id
        ).join(RegistryLocation, RegistryLocation.id == RegistryCamera.location_id).where(
            CameraUseCaseAssignment.use_case == "vault_room",
            CameraUseCaseAssignment.is_active.is_(True), RegistryCamera.is_active.is_(True),
            RegistryLocation.is_active.is_(True))
        rows = db.execute(stmt).all()
        if configured:
            matching = [(assignment, camera, location) for assignment, camera, location in rows
                        if location.code == configured.location_code and camera.code == configured.camera_code]
            if len(matching) != 1:
                raise RuntimeError("vault_room.active_assignment does not resolve to one active Vault Room assignment")
            return matching[0]
        if config.zones_source == "database":
            raise RuntimeError("vault_room.active_assignment is required when zones_source is database")
        if len(rows) > 1:
            raise RuntimeError("Set vault_room.active_assignment when more than one Vault Room assignment exists")
        return rows[0] if rows else None

    def _load_db(self, assignment_id: str) -> list[Zone]:
        with session_scope() as db:
            rows = db.scalars(select(RegistryZone).where(
                RegistryZone.assignment_id == assignment_id, RegistryZone.enabled.is_(True)
            ).order_by(RegistryZone.created_at)).all()
            if any(row.coordinate_system != "normalized_raw" for row in rows):
                raise RuntimeError("Vault Room database zones must use normalized_raw coordinates")
            return [Zone(row.zone_key, row.name, tuple((float(p[0]), float(p[1])) for p in row.polygon),
                         row.reference or "bottom_center") for row in rows]

    def load(self) -> tuple[Zone, ...] | None:
        """Return zones or None on invalid/unavailable source; None means keep same-assignment snapshot."""
        config = get_vault_room_config()
        self.last_source = config.zones_source
        self.active_identity = None
        try:
            with session_scope() as db:
                resolved = self._resolve_assignment(db)
                self.active_identity = ({"use_case": "vault_room", "assignment_id": str(resolved[0].id),
                    "camera_id": str(resolved[1].id), "location_id": str(resolved[2].id)} if resolved else None)
                assignment_id = self.active_identity["assignment_id"] if self.active_identity else None
            if config.zones_source == "database":
                if assignment_id is None:
                    raise RuntimeError("No active Vault Room assignment is configured")
                return tuple(self._load_db(assignment_id))
            return tuple(zone for zone in load_zones(self.zone_file.path) if zone.enabled)
        except (OSError, ZoneConfigError, RuntimeError, ValueError) as exc:
            logger.error("Vault zone snapshot load failed source=%s error=%s", config.zones_source, type(exc).__name__)
            return None


def active_vault_assignment(db, *, required: bool = True):
    """Resolve the explicit Vault assignment for management endpoints."""
    try:
        resolved = VaultRoomZoneProvider._resolve_assignment(db)
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc
    if resolved is None and required:
        raise ValueError("Create a Vault Room location, camera, source and assignment before managing Vault zones")
    return resolved


