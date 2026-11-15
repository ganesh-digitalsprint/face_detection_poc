import asyncio
from types import SimpleNamespace

from app.services.door_controller import SimulatedDoorController
from app.services.vault_room_manager import VaultRoomManager


def short_config():
    return SimpleNamespace(entry_buffer_seconds=2, session_seconds=4,
        warn_before_expiry_seconds=1, expired_repeat_seconds=2)


def test_manager_grant_close_summary_and_subscriber_snapshot(monkeypatch):
    clock = [10.0]
    jobs = []
    door = SimulatedDoorController()
    manager = VaultRoomManager(clock=lambda:clock[0], door=door, writer=jobs.append, config=short_config())
    discarded = []
    class DualManager:
        def discard(self, session_id): discarded.append(session_id)
    import app.services.dual_control as dual_control
    monkeypatch.setattr(dual_control, "get_dual_control_session_manager", lambda:DualManager())
    async def scenario():
        q = manager.subscribe()
        snap = await q.get()
        assert snap["_snapshot"] is True
        manager.on_access_granted("dual-id", [{"slot":1,"employee_id":"E1","name":"One"}], 1, True)
        assert manager.is_session_active() is True
        info = manager.active_session_info()
        assert info.state == "ENTRY_BUFFER" and info.remaining_seconds is None
        assert info.entry_buffer_remaining_seconds == 2 and info.session_id
        assert manager.state()["door"] == "UNLOCKED"
        clock[0] = 12
        manager.tick()
        assert manager.state()["state"] == "ACTIVE"
        summary = manager.close_vault()
        assert summary["duration_seconds"] == 2
        assert manager.close_vault() == summary
        assert door.locked
        assert manager.is_session_active() is False
        assert manager.active_session_info() is None
        manager.unsubscribe(q)
    asyncio.run(scenario())
    manager._jobs.join()
    assert sum(1 for kind, _ in jobs if kind == "summary") == 1
    assert discarded == ["dual-id"]
    manager.stop()


def test_writer_failure_does_not_prevent_timer_or_close():
    clock = [0.0]
    def broken_writer(_job): raise RuntimeError("database unavailable")
    manager = VaultRoomManager(clock=lambda:clock[0], writer=broken_writer, config=short_config())
    manager.on_access_granted("dual-id", [], 2, False)
    clock[0] = 2
    manager.tick()
    assert manager.state()["state"] == "ACTIVE"
    summary = manager.close_vault()
    assert summary["state"] == "CLOSED"
    manager._jobs.join()
    manager.stop()


def test_access_and_camera_contexts_are_immutable_and_independent():
    manager = VaultRoomManager(config=short_config())
    manager._load_zone_snapshot = lambda: None
    branch = {"branch_id": "branch-1", "branch_name": "Koramangala",
        "camera_name": "Entrance Camera"}
    manager.on_access_attempt_started("access-1", 2, source_context=branch)
    branch["branch_name"] = "Changed after start"
    assert manager.access_session_context("access-1")["branch_name"] == "Koramangala"

    first = manager.bind_camera_source("camera-1", source_type="browser_webcam",
        camera_name="Vault Room Camera", source_context={"branch_id": "branch-1"})
    second = manager.bind_camera_source("camera-2", source_type="rtsp",
        camera_name="Rear RTSP", source_context={"branch_id": "branch-2"})
    first["branch_id"] = "changed"
    assert manager.camera_source_context("camera-1")["branch_id"] == "branch-1"
    assert manager.camera_source_context("camera-2") == second
    manager.release_camera_source("camera-1")
    assert manager.camera_source_context("camera-1") is None
    assert manager.camera_source_context("camera-2")["camera_name"] == "Rear RTSP"
    manager.stop()


def _queued_job(manager):
    job = manager._alert_worker._queue.get_nowait()
    manager._alert_worker._queue.task_done()
    return job


def test_alert_submission_combines_access_branch_with_triggering_camera():
    manager = VaultRoomManager(config=short_config())
    manager._load_zone_snapshot = lambda: None
    manager._ensure_ticker = lambda: None
    manager.on_access_attempt_started("access-1", 2, source_context={
        "branch_id": "branch-1", "branch_name": "Koramangala",
        "camera_name": "Entrance Camera", "source_type": "entrance_camera"})
    manager.bind_camera_source("browser-1", source_type="browser_webcam",
        camera_name="Vault Room Camera", source_context={
            "branch_id": "branch-1", "branch_name": "Koramangala"})
    manager._session_identity = {"camera_id": "registry-camera-1",
        "assignment_id": "assignment-1", "location_id": "vault-location-1"}
    manager._video_source = "browser"
    manager._submit_alert_snapshot_locked(1)
    job = _queued_job(manager)

    assert job.source_metadata["branch_id"] == "branch-1"
    assert job.source_metadata["camera_name"] == "Vault Room Camera"
    assert job.source_metadata["source_id"] == "browser-1"
    assert job.source_metadata["source_type"] == "browser_webcam"
    assert job.source_metadata["registry_camera_id"] == "registry-camera-1"
    assert job.source_metadata["location_id"] == "vault-location-1"
    assert job.source_metadata["branch_id"] != job.source_metadata["location_id"]
    manager.release_camera_source("browser-1")
    manager._access_session_contexts.clear()
    assert job.source_metadata["branch_name"] == "Koramangala"
    manager.stop()


def test_camera_health_snapshots_keep_multiple_camera_attribution_separate():
    manager = VaultRoomManager(config=short_config())
    manager.bind_camera_source("browser-1", source_type="browser_webcam",
        camera_name="Browser camera", source_context={"branch_id": "branch-1"})
    manager.bind_camera_source("rtsp-1", source_type="rtsp",
        camera_name="Rear RTSP", source_context={"branch_id": "branch-2"})
    manager.release_camera_source("rtsp-1")
    manager._video_source = "rtsp"
    manager._submit_alert_snapshot_locked(None)
    rtsp_job = _queued_job(manager)

    manager.bind_camera_source("browser-1", source_type="browser_webcam",
        camera_name="Browser camera", source_context={"branch_id": "branch-1"})
    manager._video_source = "browser"
    manager._submit_alert_snapshot_locked(None)
    browser_job = _queued_job(manager)

    assert rtsp_job.source_metadata["branch_id"] == "branch-2"
    assert rtsp_job.source_metadata["camera_name"] == "Rear RTSP"
    assert rtsp_job.source_metadata["source_id"] == "rtsp-1"
    assert browser_job.source_metadata["branch_id"] == "branch-1"
    assert browser_job.source_metadata["camera_name"] == "Browser camera"
    assert browser_job.source_metadata["source_id"] == "browser-1"
    manager.stop()


def test_terminal_auth_failure_snapshots_access_camera_before_cleanup():
    manager = VaultRoomManager(config=short_config())
    manager._load_zone_snapshot = lambda: None
    manager._ensure_ticker = lambda: None
    manager.on_access_attempt_started("access-1", 2, source_context={
        "branch_id": "branch-1", "branch_name": "Koramangala",
        "camera_name": "Entrance Camera", "source_type": "entrance_camera"})
    manager.bind_camera_source("room-rtsp", source_type="rtsp", camera_name="Room RTSP",
        source_context={"branch_id": "branch-1"})
    manager.on_terminal_auth_failure("access-1", "FAILED")
    job = _queued_job(manager)

    assert job.source_metadata["branch_id"] == "branch-1"
    assert job.source_metadata["camera_name"] == "Entrance Camera"
    assert job.source_metadata["source_type"] == "entrance_camera"
    assert "source_id" not in job.source_metadata
    assert manager.access_session_context("access-1") is None
    manager.stop()
