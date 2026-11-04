from dataclasses import dataclass

import numpy as np

from app.core.zones.vault_room_zone import Zone
from app.services.person_tracker import PersonTracker
from app.services.vault_room_counter import StableCounter
from app.services.vault_room_manager import VaultRoomManager


@dataclass
class SnapshotProvider:
    zones: tuple
    loads: int = 0
    active_identity: dict | None = None
    last_source: str = "file"

    def load(self):
        self.loads += 1
        return self.zones


class EmptyDetector:
    status = {"status": "ready"}

    def detect(self, _frame):
        return []


def _zone(zone_id):
    return Zone(zone_id, zone_id, ((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)))


def test_vault_zone_snapshot_is_stable_for_session_and_reloads_next_session():
    from app.core.ml_config import get_vault_room_config

    provider = SnapshotProvider((_zone("original"),))
    config = get_vault_room_config()
    counting = config.counting
    manager = VaultRoomManager(config=config, zone_provider=provider, detector=EmptyDetector(),
        tracker=PersonTracker(counting), counter=StableCounter(window_seconds=counting.count_stable_seconds,
            min_samples=counting.stable_min_samples, majority_ratio=counting.stable_majority_ratio,
            stale_seconds=counting.frame_stale_seconds), writer=lambda _job: None)
    try:
        manager.on_access_attempt_started("session-1", 1)
        assert provider.loads == 1
        assert [z["id"] for z in manager._zone_monitor.snapshot()] == ["original"]

        # A saved edit cannot affect the active monitor; frame processing must not reload storage.
        provider.zones = (_zone("edited"),)
        frame_result = manager.process_frame(np.zeros((32, 32, 3), dtype=np.uint8))
        assert provider.loads == 1
        assert [z["id"] for z in frame_result["zones"]] == ["original"]

        manager.on_access_attempt_started("session-2", 1)
        assert provider.loads == 2
        assert [z["id"] for z in manager._zone_monitor.snapshot()] == ["edited"]
    finally:
        manager.stop()
