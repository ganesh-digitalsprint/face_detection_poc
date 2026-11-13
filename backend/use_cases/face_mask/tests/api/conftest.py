from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core import settings_store
from app.core.paths import CLIP_DIR, SNAPSHOT_DIR, STORAGE_DIR, UPLOAD_DIR
from app.services.detection_pipeline import FrameResult


class _NoopPipeline:
    """Stands in for the real models in API tests: every frame has nobody in it."""
    analyzer_name = "noop"

    def process_frame(self, frame, ts, rois):
        return FrameResult([], [])

    def active_track_ids(self):
        return []


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "api.db"


@pytest.fixture
def client(db_path, monkeypatch, tmp_path):
    monkeypatch.setenv("DB_SQLITE_PATH", str(db_path))
    monkeypatch.setattr(settings_store, "OVERRIDES_FILE", tmp_path / "overrides.json")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.main import app
    from app.services.runtime import Runtime

    monkeypatch.setattr(Runtime, "make_pipeline", lambda self, camera_id: _NoopPipeline())
    uploaded_before = set(UPLOAD_DIR.glob("*"))
    with TestClient(app) as test_client:
        yield test_client
    for leftover in set(UPLOAD_DIR.glob("*")) - uploaded_before:
        leftover.unlink(missing_ok=True)
    get_settings.cache_clear()


@pytest.fixture
def make_video(tmp_path):
    def build(name: str = "t.mp4", frames: int = 12, size=(320, 240)) -> Path:
        path = tmp_path / name
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, size)
        rng = np.random.default_rng(0)
        for _ in range(frames):
            writer.write(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8))
        writer.release()
        return path
    return build


@pytest.fixture
def add_event(db_path, client):
    """Insert an event row directly (the pipeline's DB writer is exercised by the live end-to-end run)."""
    created: list[Path] = []

    def insert(camera_id="cam1", status="OPEN", covering="scarf", minutes_ago=0, score=0.9, snapshot="", clip="",
               clip_status="pending", remarks="", reviewer="") -> str:
        event_id = uuid.uuid4().hex
        at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).replace(tzinfo=None)
        with sqlite3.connect(db_path) as db:
            db.execute(
                "INSERT INTO fm_concealment_event (id,status,score,covering_type,track_id,camera_id,first_seen,last_seen,"
                "frame_count,snapshot_path,clip_path,clip_status,clip_error,reviewer,remarks,evidence_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (event_id, status, score, covering, 1, camera_id, at, at, 7, snapshot, clip, clip_status, "", reviewer, remarks, event_id))
        return event_id

    yield insert
    for path in created:
        path.unlink(missing_ok=True)


@pytest.fixture
def add_entry(db_path, client):
    def insert(outcome="VISIBLE", camera_id="cam1", hours_ago=0.0) -> None:
        at = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).replace(tzinfo=None)
        with sqlite3.connect(db_path) as db:
            db.execute("INSERT INTO fm_entry_log (id,camera_id,track_id,outcome,score,frames_evaluated,evaluated_at) "
                       "VALUES (?,?,?,?,?,?,?)", (uuid.uuid4().hex, camera_id, 1, outcome, 0.5, 5, at))
    return insert


@pytest.fixture
def evidence_files():
    """Create real snapshot/clip files under storage/ and remove them afterwards."""
    made: list[Path] = []

    def make(name: str, kind: str = "snapshot") -> str:
        folder = SNAPSHOT_DIR if kind == "snapshot" else CLIP_DIR
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 2000 if kind == "snapshot" else b"0" * 5000)
        made.append(path)
        return path.relative_to(STORAGE_DIR).as_posix()

    yield make
    for path in made:
        path.unlink(missing_ok=True)
