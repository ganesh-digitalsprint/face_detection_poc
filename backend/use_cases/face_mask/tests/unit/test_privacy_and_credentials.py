from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from app.core.logging_config import redact_url
from app.models.orm import Base
from app.schemas.camera import Camera
from app.schemas.review import REVIEW_TRANSITIONS

# FM-14: nothing that could identify a person or hold a face embedding may be stored.
_FORBIDDEN_COLUMN_PARTS = ("embedding", "identity", "person_name", "full_name", "face_id", "face_encoding", "employee")


def test_fm14_no_identity_or_embedding_columns_in_any_table() -> None:
    offenders = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if any(part in column.name.lower() for part in _FORBIDDEN_COLUMN_PARTS)
    ]
    assert offenders == []


def test_fm13_public_camera_never_contains_password_or_url_credentials() -> None:
    cam = Camera(
        id="c1", name="Gate", cam_type="rtsp", source="rtsp://admin:s3cret@10.0.0.5/stream1",
        username="admin", password="s3cret", created_at=datetime.now(timezone.utc),
    )
    dumped = cam.public().model_dump_json()
    assert "s3cret" not in dumped
    assert "admin" not in dumped
    assert cam.public().has_password is True


def test_fm13_redact_url_hides_credentials() -> None:
    assert redact_url("open rtsp://admin:s3cret@10.0.0.5/s1 failed") == "open rtsp://***:***@10.0.0.5/s1 failed"


def test_fm13_logger_filter_redacts_credentials(capsys: pytest.CaptureFixture[str]) -> None:
    from app.core.logging_config import configure_logging

    root = logging.getLogger()
    saved = root.handlers[:]
    root.handlers.clear()
    try:
        configure_logging()
        logging.getLogger("t").info("connect rtsp://admin:s3cret@cam/x")
        assert "s3cret" not in capsys.readouterr().out
    finally:
        root.handlers[:] = saved


def test_fm06_review_transitions_are_closed_loop() -> None:
    assert REVIEW_TRANSITIONS["OPEN"] == {"UNDER_REVIEW"}
    assert REVIEW_TRANSITIONS["CLOSED"] == frozenset()
    assert "CLOSED" in REVIEW_TRANSITIONS["CONFIRMED"] and "CLOSED" in REVIEW_TRANSITIONS["FALSE_POSITIVE"]
