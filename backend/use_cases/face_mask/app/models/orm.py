"""SQLAlchemy ORM models (FM-14: no identity, name or embedding columns exist or may be added).

Primary keys are client-generated UUID4 hex strings, as in branch_exterior.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class CameraORM(Base):
    __tablename__ = "fm_camera"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120))
    cam_type: Mapped[str] = mapped_column(String(20))  # rtsp | webcam | upload | folder
    source: Mapped[str] = mapped_column(String(500))
    username: Mapped[str] = mapped_column(String(120), default="")
    password: Mapped[str] = mapped_column(String(120), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    loop_video: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EntryRoiORM(Base):
    __tablename__ = "fm_entry_roi"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    camera_id: Mapped[str] = mapped_column(ForeignKey("fm_camera.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    polygon: Mapped[list] = mapped_column(JSON)          # [{x, y}] normalised 0..1
    inward_vector: Mapped[dict] = mapped_column(JSON)    # {x, y} direction a person moves when entering
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EntryLogORM(Base):
    __tablename__ = "fm_entry_log"
    __table_args__ = (Index("ix_fm_entry_log_camera_time", "camera_id", "evaluated_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    camera_id: Mapped[str] = mapped_column(String(32))
    roi_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    track_id: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(24))     # VISIBLE | CONCEALED | UNABLE_TO_ASSESS
    score: Mapped[float] = mapped_column(Float, default=0.0)
    frames_evaluated: Mapped[int] = mapped_column(Integer, default=0)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ConcealmentEventORM(Base):
    __tablename__ = "fm_concealment_event"
    __table_args__ = (
        Index("ix_fm_event_camera_first_seen", "camera_id", "first_seen"),
        Index("ix_fm_event_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    covering_type: Mapped[str] = mapped_column(String(32), default="")
    track_id: Mapped[int] = mapped_column(Integer)
    camera_id: Mapped[str] = mapped_column(String(32))
    roi_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    alert_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot_path: Mapped[str] = mapped_column(String(300), default="")
    clip_path: Mapped[str] = mapped_column(String(300), default="")
    clip_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | ready | failed
    clip_error: Mapped[str] = mapped_column(String(300), default="")
    reviewer: Mapped[str] = mapped_column(String(120), default="")
    remarks: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewActionORM(Base):
    __tablename__ = "fm_review_action"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(ForeignKey("fm_concealment_event.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    actor: Mapped[str] = mapped_column(String(120), default="")
    remarks: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
