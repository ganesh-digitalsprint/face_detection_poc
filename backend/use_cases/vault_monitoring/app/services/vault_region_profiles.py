"""Vault-only camera profiles backed by the existing normalized ZoneFile format."""
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import threading
from uuid import uuid4
from app.core.zones.vault_room_zone import load_zones, save_zones, zone_from_dict

REGIONS = {
    "person_monitoring_roi": "Person Monitoring Area", "vault_area_roi": "Vault Area",
    "vault_door_roi": "Vault Door", "tray_area_roi": "Tray Area", "ornament_area_roi": "Ornament Area",
}
DEFAULTS = {"webcam": "Webcam", "cctv": "CCTV", "upload": "Uploaded video"}


class VaultRegionProfiles:
    def __init__(self, root=None):
        # The service can be launched from the repo root or its own directory.
        # Both must address the same existing Vault-only profile namespace.
        self.root = Path(root) if root is not None else Path(__file__).resolve().parents[2] / 'var/vault-room-region-profiles'
        self.lock = threading.RLock()

    def _path(self, profile_id):
        if not re.fullmatch(r"[a-z0-9_-]{1,64}", profile_id):
            raise ValueError("Invalid Vault Room profile identifier")
        return self.root / f"{profile_id}.json"

    def list(self):
        with self.lock:
            names = set(DEFAULTS)
            if self.root.exists():
                names.update(path.stem for path in self.root.glob("*.json"))
            return [{k: v for k, v in self.load(identifier).items() if k != "zones"} for identifier in sorted(names)]

    def load(self, profile_id):
        path = self._path(profile_id)
        with self.lock:
            if not path.exists():
                if profile_id not in DEFAULTS:
                    raise KeyError(profile_id)
                return dict(id=profile_id, name=DEFAULTS[profile_id], version=0, zones=[])
            raw = json.loads(path.read_text(encoding="utf-8"))
            durations = raw.get("confirmation_seconds", {})
            return dict(id=profile_id, name=raw["name"], version=raw["version"],
                zones=[{**zone.as_dict(), "confirmation_seconds": durations.get(zone.id, 1.0)} for zone in load_zones(path)])

    def create(self, name):
        if not name.strip() or len(name) > 80:
            raise ValueError("Use a profile name between 1 and 80 characters")
        with self.lock:
            if len(self.list()) >= 100:
                raise ValueError("At most 100 Vault Room profiles are supported")
            return self.save(uuid4().hex, [], 0, name=name.strip())

    def save(self, profile_id, rows, expected_version, *, name=None):
        if len(rows) > len(REGIONS) or len({row["id"] for row in rows}) != len(rows):
            raise ValueError("Configure each predefined Vault region at most once")
        zones = []
        for row in rows:
            if row["id"] not in REGIONS:
                raise ValueError("Unknown Vault monitoring region")
            duration = row.get("confirmation_seconds", 1.0)
            if not isinstance(duration, (float, int)) or not 0 <= duration <= 60:
                raise ValueError("Confirmation duration must be between 0 and 60 seconds")
            zones.append(zone_from_dict({**row, "name": row.get("name") or REGIONS[row["id"]]}))
        with self.lock:
            current = self.load(profile_id) if name is None else dict(name=name, version=0)
            if current["version"] != expected_version:
                raise RuntimeError("This profile changed. Reload it before saving again.")
            path = self._path(profile_id)
            staging = path.with_suffix(f".{uuid4().hex}.staging")
            try:
                save_zones(staging, zones)
                data = json.loads(staging.read_text(encoding="utf-8"))
                data.update(name=current["name"], version=current["version"] + 1,
                    confirmation_seconds={row["id"]: row.get("confirmation_seconds", 1.0) for row in rows})
                staging.write_text(json.dumps(data, indent=2), encoding="utf-8")
                os.replace(staging, path)
            finally:
                staging.unlink(missing_ok=True)
            return self.load(profile_id)


@lru_cache(maxsize=1)
def get_vault_region_profiles():
    return VaultRegionProfiles()
