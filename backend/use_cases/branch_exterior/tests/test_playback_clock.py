from datetime import datetime, timezone
import json
from types import SimpleNamespace

from app.services.analytics.after_hours import AfterHoursEngine
from app.services.analytics.loitering import LoiteringEngine
from app.services import camera_manager
from app.services.detection.base import Detection
from app.services.detection.bytetrack import ByteTracker
from app.services.detection.tracker import CentroidTracker


def test_paused_wall_time_does_not_inflate_video_dwell(monkeypatch):
    now = datetime.now(timezone.utc)
    zone = SimpleNamespace(id="gate", name="Gate", restricted=True)
    track = SimpleNamespace(history=[])
    tracks = {1: track}
    zones = {1: zone}
    thresholds = SimpleNamespace(loiter_seconds_after_hours=30,
                                 loiter_seconds_business_hours=30,
                                 after_hours_min_dwell_seconds=5,
                                 after_hours_grace_minutes=0)
    loitering = LoiteringEngine()
    after_hours = AfterHoursEngine()
    assert loitering.evaluate(tracks, zones, thresholds, {}, now, now_ts=100) == []
    assert after_hours.evaluate(tracks, zones, thresholds, {}, now, now_ts=100) == []
    monkeypatch.setattr("time.time", lambda: 130)  # 30 seconds passed while the file was paused
    assert loitering.evaluate(tracks, zones, thresholds, {}, now, now_ts=101) == []
    assert after_hours.evaluate(tracks, zones, thresholds, {}, now, now_ts=101) == []


def test_track_history_uses_video_time_even_when_wall_clock_differs(monkeypatch):
    monkeypatch.setattr('time.time', lambda: 1_000_000)
    for tracker in (ByteTracker(), CentroidTracker()):
        first = Detection(10, 10, 60, 110, 'person', 0.9)
        second = Detection(20, 10, 70, 110, 'person', 0.9)
        tracker.update([first], 200, 200, now=100.0)
        tracks = tracker.update([second], 200, 200, now=100.5)
        person = next(iter(tracks.values()))
        assert person.history[-1][0] == 100.5
        assert person.speed_mps() > 0


def test_saved_position_is_visible_after_manager_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(camera_manager, "STORAGE_DIR", tmp_path)
    path = tmp_path / "playback_state" / "branch_exterior" / "camera.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"can_resume": True, "frame_index": 60, "frames_total": 240,
                                "source_fps": 24.0}), encoding="utf-8")
    status = camera_manager.CameraManager().status("camera")
    assert status.status == "STOPPED" and status.can_resume
    assert (status.frames_read, status.percent, status.position_seconds, status.total_seconds) == (60, 25.0, 2.5, 10.0)
