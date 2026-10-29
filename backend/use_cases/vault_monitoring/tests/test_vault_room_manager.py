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
