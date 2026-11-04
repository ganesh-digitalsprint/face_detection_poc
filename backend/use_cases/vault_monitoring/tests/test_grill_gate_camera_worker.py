from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from app.services.grill_gate_camera_worker import (
    CaptureSource,
    GrillGateCameraWorker,
    GrillGateCameraWorkerManager,
    GrillGateWorkerCapacityError,
    GrillGateWorkerConflictError,
)


class FakeCapture:
    def __init__(self, *, fail_after: int | None = None, block: bool = False):
        self.fail_after = fail_after
        self.block = block
        self.read_count = 0
        self.released = threading.Event()
        self.opened = True

    def isOpened(self):
        return self.opened

    def set(self, *_args):
        return True

    def read(self):
        if self.block:
            self.released.wait(2)
            return True, np.full((3, 4, 3), 42, dtype=np.uint8)
        time.sleep(0.004)
        self.read_count += 1
        if self.fail_after is not None and self.read_count > self.fail_after:
            return False, None
        return True, np.full((3, 4, 3), self.read_count % 255, dtype=np.uint8)

    def release(self):
        self.opened = False
        self.released.set()


def wait_for(predicate, timeout=1.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def source():
    return CaptureSource("rtsp", "rtsp", "rtsp://user:secret@example.invalid/live")


def test_frame_delivery_is_read_only_and_independent_per_consumer():
    capture = FakeCapture()
    worker = GrillGateCameraWorker("cam-1", "asg-1", source(), capture_opener=lambda *_: capture)
    first = worker.subscribe("gate")
    second = worker.subscribe("mesh")
    worker.start()
    try:
        a = first.get(timeout=1)
        b = second.get(timeout=1)
        assert a is not None and b is not None
        assert (a.width, a.height, a.sequence_number) == (4, 3, b.sequence_number)
        assert a.frame.flags.writeable is False
        with pytest.raises(ValueError):
            a.frame[0, 0, 0] = 255
        a.frame.setflags(write=True)
        a.frame[0, 0, 0] = 255
        assert b.frame[0, 0, 0] != 255
        assert worker.status()["status"] == "connected"
    finally:
        worker.stop()
    assert capture.released.is_set()
    assert worker.status()["status"] == "stopped"


def test_stale_worker_clears_frames_and_only_recovers_on_fresh_frame():
    class StallCapture(FakeCapture):
        def __init__(self):
            super().__init__()
            self.first = True

        def read(self):
            if self.first:
                self.first = False
                return True, np.ones((3, 4, 3), dtype=np.uint8)
            self.released.wait(2)
            return True, np.full((3, 4, 3), 42, dtype=np.uint8)

    capture = StallCapture()
    worker = GrillGateCameraWorker(
        "cam-2", "asg-2", source(), capture_opener=lambda *_: capture,
        reconnect_attempts=2, reconnect_delay_seconds=0.01, stale_after_seconds=0.04,
    )
    sub = worker.subscribe("consumer")
    worker.start()
    try:
        assert sub.get(timeout=1) is not None
        assert wait_for(lambda: worker.status()["status"] == "stale")
        assert worker.latest() is None
        assert sub.get(timeout=0.05) is None
        capture.release()
        assert wait_for(lambda: worker.status()["status"] == "connected")
        packet = worker.latest()
        assert packet is not None
        assert packet.sequence_number >= 2
    finally:
        worker.stop()


def test_reconnect_preserves_sequence_and_releases_old_capture():
    captures = [FakeCapture(fail_after=2), FakeCapture()]
    opened = []

    def opener(*_args):
        capture = captures[min(len(opened), 1)]
        opened.append(capture)
        return capture

    worker = GrillGateCameraWorker("cam-3", "asg-3", source(), capture_opener=opener,
        reconnect_attempts=2, reconnect_delay_seconds=0.01)
    worker.start()
    try:
        assert wait_for(lambda: len(opened) >= 2 and worker.status()["sequence_number"] > 2)
        assert opened[0].released.is_set()
        assert worker.status()["status"] == "connected"
        assert worker.status()["sequence_number"] > 2
    finally:
        worker.stop()


def test_manager_is_idempotent_per_camera_and_enforces_atomic_capacity():
    entered = threading.Event()
    captures = []

    def opener(*_args):
        cap = FakeCapture(block=True)
        captures.append(cap)
        entered.set()
        return cap

    manager = GrillGateCameraWorkerManager(max_workers=1, capture_opener=opener,
                                            shutdown_timeout_seconds=0.1)
    results = []
    barrier = threading.Barrier(3)

    def connect_same():
        barrier.wait()
        results.append(manager.connect("same-camera", "same-assignment", source()))

    threads = [threading.Thread(target=connect_same) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert len(captures) == 1
    assert sorted(created for _status, created in results) == [False, True]
    assert entered.wait(1)
    with pytest.raises(GrillGateWorkerCapacityError):
        manager.connect("other-camera", "other-assignment", source())
    with pytest.raises(GrillGateWorkerConflictError):
        manager.connect("same-camera", "different-assignment", source())
    manager.disconnect("same-camera", "same-assignment")
    assert captures[0].released.is_set()


def test_disconnect_is_idempotent_and_consumer_mailboxes_are_bounded():
    cap = FakeCapture()
    manager = GrillGateCameraWorkerManager(max_workers=2, capture_opener=lambda *_: cap)
    status, created = manager.connect("cam-x", "asg-x", source())
    assert created is True
    assert manager.connect("cam-x", "asg-x", source())[1] is False
    assert wait_for(lambda: manager.latest("cam-x") is not None)
    sub = manager.subscribe("cam-x", "slow")
    time.sleep(0.03)
    packet = sub.get(timeout=0.1)
    assert packet is not None
    assert packet.sequence_number > 1
    assert manager.disconnect("cam-x", "asg-x")["status"] == "stopped"
    assert manager.disconnect("cam-x", "asg-x")["status"] == "stopped"
    assert manager.statuses()[0]["status"] == "stopped"


def test_manager_runs_independent_workers_for_multiple_cameras():
    captures = {}

    def opener(_source, _kind, _timeout):
        cap = FakeCapture()
        captures[len(captures)] = cap
        return cap

    manager = GrillGateCameraWorkerManager(max_workers=2, capture_opener=opener)
    manager.connect("camera-a", "assignment-a", source())
    manager.connect("camera-b", "assignment-b", source())
    assert wait_for(lambda: all(status["sequence_number"] > 0 for status in manager.statuses()))
    statuses = {status["camera_id"]: status for status in manager.statuses()}
    assert set(statuses) == {"camera-a", "camera-b"}
    assert statuses["camera-a"]["sequence_number"] > 0
    assert statuses["camera-b"]["sequence_number"] > 0
    manager.stop_all()
    assert all(cap.released.is_set() for cap in captures.values())


def test_capture_exceptions_are_not_returned_or_logged(caplog):
    worker = GrillGateCameraWorker(
        "camera-secret-safe", "assignment-safe", source(),
        capture_opener=lambda *_args: (_ for _ in ()).throw(RuntimeError("password=private-value")),
        reconnect_attempts=0,
    )
    worker.start()
    assert wait_for(lambda: worker.status()["status"] == "failed")
    worker.join()
    assert "private-value" not in str(worker.status())
    assert "private-value" not in caplog.text
