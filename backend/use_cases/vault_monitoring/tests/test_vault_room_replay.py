import time

import cv2
from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
import pytest

from app.api.routes import vault_room_replay as routes
from app.core.ml_config import get_vault_room_config
from app.services.person_detector import Detection
from app.services.vault_room_manager import VaultRoomManager
from app.services.vault_room_replay import VaultRoomReplayManager


class Detector:
    status = {"status": "ready"}
    def detect(self, image):
        height, width = image.shape[:2]
        return [Detection(width * .2, height * .1, width * .7, height * .9, .99)]


def wait_for(predicate, seconds=6):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError("Replay did not reach the expected state")


@pytest.fixture
def replay(tmp_path, monkeypatch):
    cfg = get_vault_room_config()
    counting = cfg.counting.model_copy(update={"stable_min_samples": 2, "count_stable_seconds": .2,
        "recommended_fps": 10, "tracker": cfg.counting.tracker.model_copy(update={"minimum_consecutive_frames": 1})})
    cfg = cfg.model_copy(update={"counting": counting})
    monkeypatch.setattr("app.services.vault_room_replay.get_vault_room_config", lambda: cfg)
    jobs = []
    live = VaultRoomManager(config=cfg, detector=Detector(), writer=jobs.append)
    manager = VaultRoomReplayManager(room_factory=lambda: live, root=tmp_path / "replays")
    monkeypatch.setattr(routes, "get_vault_room_replay_manager", lambda: manager)
    monkeypatch.setattr(routes.require_vault_room_key.__globals__["settings"], "VAULT_ROOM_API_KEY", "replay-key")
    app = FastAPI(); app.include_router(routes.router)
    client = TestClient(app, headers={"X-API-Key": "replay-key"})
    path = tmp_path / "sample.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (160, 120))
    assert writer.isOpened()
    for index in range(20):
        writer.write(np.full((120, 160, 3), index * 5, dtype=np.uint8))
    writer.release()
    yield manager, live, jobs, client, path.read_bytes()
    manager.shutdown(); live.stop()


def upload(client, data):
    response = client.post("/api/v1/vault-room/video-sessions", files={"file": ("sample.avi", data, "video/x-msvideo")})
    assert response.status_code == 201, response.text
    return response.json()


def test_complete_replay_reuses_pipeline_and_isolates_live_alerts_evidence_and_state(replay):
    manager, live, jobs, client, data = replay
    before = live.state()
    uploaded = upload(client, data)
    sid = uploaded["session_id"]; root = f"/api/v1/vault-room/video-sessions/{sid}"
    assert uploaded["metadata"] == dict(fps=10, width=160, height=120, frame_count=20, duration=2, size_bytes=len(data))
    # Explicit opt-out exercises the legacy unverified security/evidence path.
    assert client.post(root + "/start", json={"required_persons": 2, "simulated_authorization": False}).status_code == 200
    wait_for(lambda: manager.get(sid).status == "completed")
    status = client.get(root).json()
    assert status["error"] is None
    assert status["progress"] == 1
    assert status["processed_frames"] == 20
    assert status["state"]["stable_count"] == 1
    assert status["state"]["tracks"][0]["track_id"] > 0
    assert status["events"]
    assert {item["type"] for item in status["alerts"]} >= {"COUNT_MISMATCH", "UNAUTHORIZED_ENTRY"}
    evidence = next(item for item in status["alerts"] if item["evidence_url"])
    assert client.get(evidence["evidence_url"]).headers["content-type"] == "image/jpeg"
    frame = client.get(root + "/frame")
    image = cv2.imdecode(np.frombuffer(frame.content, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image.shape[:2] == (120, 160)
    assert image[12:108, 32:112, 1].max() > 150  # Existing annotation service drew the tracking box.
    assert live.state() == before
    assert all(kind == 'activity' for kind, _data in jobs)  # Replay operational history only; no live alerts/audits.
    assert status['state']['session_id'] == sid
    assert status['events'] and all(event['session_id'] == sid for event in status['events'])
    assert not manager.get(sid).source.exists()
    directory = manager.get(sid).directory
    assert client.delete(root).status_code == 200
    assert not directory.exists()
    assert client.get(root).status_code == 404


def test_debug_frame_uses_atomic_snapshot_and_never_mutates_clean_output(replay, monkeypatch):
    from app.services import vault_pose_debug
    manager, live, jobs, client, data = replay
    uploaded=upload(client,data);sid=uploaded['session_id'];session=manager.get(sid)
    session.jpeg=cv2.imencode('.jpg',np.zeros((120,160,3),dtype=np.uint8))[1].tobytes()
    session.frame_sequence=17;session.frame_time=7.083;session.frame_debug={'sentinel':'frame17'}
    clean=session.jpeg;calls=[]
    def render(jpeg, snapshot, **metadata):
        calls.append((jpeg,snapshot,metadata))
        # A concurrent newer publish cannot alter this selected snapshot.
        session.frame_sequence=18;session.frame_time=7.29;session.frame_debug={'sentinel':'frame18'}
        return b'debug-image'
    monkeypatch.setattr(vault_pose_debug,'render_pose_debug',render)
    base=f'/api/v1/vault-room/video-sessions/{sid}/frame'
    debug=client.get(base+'?debug=true')
    assert debug.content==b'debug-image'
    assert debug.headers['x-frame-sequence']=='17' and debug.headers['x-video-time']=='7.083'
    assert calls[0][1]=={'sentinel':'frame17'} and calls[0][2]['sequence']==17
    assert client.get(base).content==clean and session.jpeg==clean
    assert client.get(base+'?debug=false').headers['x-pose-debug']=='false'
    assert live.state()['state']=='IDLE' and not jobs


def test_pause_resume_stop_and_capacity_conflict(replay):
    manager, _live, _jobs, client, data = replay
    sid = upload(client, data)["session_id"]; root = f"/api/v1/vault-room/video-sessions/{sid}"
    client.post(root + "/start", json={})
    wait_for(lambda: manager.get(sid).processed_frames >= 2)
    assert client.post(root + "/control", json={"action": "pause"}).status_code == 200
    time.sleep(.15)
    frame_count = manager.get(sid).processed_frames
    source_time = manager.get(sid).current_time
    time.sleep(.2)
    assert manager.get(sid).processed_frames == frame_count
    assert manager.get(sid).current_time == source_time
    other = upload(client, data)["session_id"]
    assert client.post(f"/api/v1/vault-room/video-sessions/{other}/start", json={}).status_code == 409
    assert client.post(root + "/control", json={"action": "resume"}).status_code == 200
    wait_for(lambda: manager.get(sid).processed_frames > frame_count)
    client.post(root + "/control", json={"action": "stop"})
    wait_for(lambda: manager.get(sid).status == "stopped")
    assert not manager.get(sid).source.exists()
    assert client.post(root + "/start", json={}).status_code == 409
    assert client.delete(root).status_code == 200
    assert client.post(f"/api/v1/vault-room/video-sessions/{other}/start", json={}).status_code == 200


def test_validation_and_auth_including_all_media_reads(replay, monkeypatch):
    manager, _live, _jobs, client, data = replay
    endpoint = "/api/v1/vault-room/video-sessions"
    assert client.post(endpoint, files={"file": ("bad.exe", data, "video/mp4")}).status_code == 400
    assert client.post(endpoint, files={"file": ("bad.mp4", b"invalid", "video/mp4")}).status_code == 400
    monkeypatch.setattr("app.services.vault_room_replay.settings.MAX_VIDEO_UPLOAD_MB", 1)
    assert client.post(endpoint, files={"file": ("big.mp4", b"x" * 1048577, "video/mp4")}).status_code == 413
    sid = upload(client, data)["session_id"]
    root = f"{endpoint}/{sid}"
    assert client.post(root + "/start", json={"required_persons": 3}).status_code == 422
    for path in [root, root + "/frame", root + "/evidence/missing"]:
        assert client.get(path, headers={"X-API-Key": "wrong"}).status_code == 401
    assert not list(manager._root.glob("*/source.mp4"))


def test_shared_inference_slot_and_replay_cleanup_never_discard_live_auth(replay, monkeypatch):
    manager, live, _jobs, client, data = replay
    sid = upload(client, data)["session_id"]
    calls = []
    monkeypatch.setattr(VaultRoomManager, "_discard_dual", staticmethod(calls.append))
    live._inference_slot.acquire()
    try:
        manager.start(sid)
        wait_for(lambda: manager.get(sid).worker is not None)
        worker = manager.get(sid).worker
        assert worker._detector is live._detector
        assert worker._inference_slot is live._inference_slot
        assert worker._tracker is not live._tracker
        assert worker._ticker is None
        assert manager.get(sid).processed_frames == 0
    finally:
        live._inference_slot.release()
    wait_for(lambda: manager.get(sid).processed_frames >= 1)
    manager.delete(sid)
    assert calls == []


def test_detector_failure_is_visible_and_upload_capacity_is_reclaimed(replay):
    manager, live, _jobs, client, data = replay
    uploaded = [upload(client, data) for _ in range(manager.MAX_SESSIONS)]
    response = client.post("/api/v1/vault-room/video-sessions", files={"file": ("sample.avi", data, "video/x-msvideo")})
    assert response.status_code == 409
    sid = uploaded[0]["session_id"]
    live._detector.status = {"status": "unavailable"}
    manager.start(sid)
    wait_for(lambda: manager.get(sid).status == "error")
    assert "unavailable" in manager.status(sid)["error"].lower()
    wait_for(lambda: not manager.get(sid).source.exists())
    manager.delete(sid)
    assert upload(client, data)["status"] == "uploaded"
