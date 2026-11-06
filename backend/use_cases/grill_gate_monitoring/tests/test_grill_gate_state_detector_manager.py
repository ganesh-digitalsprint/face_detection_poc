import time

import pytest

from grill_gate_monitoring.services.gate_state_detector_manager import DetectorCapacityError, GrillGateStateDetectorManager


class Subscription:
    def __init__(self):
        self.closed = False

    def get(self, timeout=None):
        time.sleep(min(timeout or 0, 0.01))
        return None

    def close(self):
        self.closed = True


class Workers:
    def __init__(self):
        self.subscriptions = []

    def subscribe(self, _camera_id, consumer_id):
        assert consumer_id == "gate-state"
        sub = Subscription()
        self.subscriptions.append(sub)
        return sub


def test_manager_is_idempotent_bounded_and_stops_consumers():
    workers = Workers()
    manager = GrillGateStateDetectorManager(max_workers=1, worker_manager=workers,
                                            config_loader_factory=lambda _: lambda: None)
    first = manager.start("camera-1", "assignment-1")
    assert first["state"] == "UNKNOWN"
    assert manager.start("camera-1", "assignment-1")["assignment_id"] == "assignment-1"
    with pytest.raises(DetectorCapacityError):
        manager.start("camera-2", "assignment-2")
    assert manager.status("assignment-1") is not None
    stopped = manager.stop("camera-1", "assignment-1")
    assert stopped["assignment_id"] == "assignment-1"
    assert workers.subscriptions[0].closed
    assert manager.status("assignment-1") is None


def test_manager_replaces_dead_detector_for_same_assignment():
    workers = Workers()
    manager = GrillGateStateDetectorManager(max_workers=1, worker_manager=workers,
                                            config_loader_factory=lambda _: lambda: None)
    manager.start("camera-1", "assignment-1")
    first = manager._detectors["camera-1"]
    first._stop.set()
    first._thread.join(2)
    assert not first._thread.is_alive()
    manager.start("camera-1", "assignment-1")
    assert len(workers.subscriptions) == 2
    manager.stop_all()
