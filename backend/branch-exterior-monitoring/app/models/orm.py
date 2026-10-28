"""SQLAlchemy ORM models.

These map 1:1 onto the SQL-family engines (SQLite / PostgreSQL / MySQL /
Oracle) - SQLAlchemy's dialect layer handles the differences in SQL syntax.
The MongoDB path does not use these classes; it stores the equivalent shape
as plain documents (see `app/db/repositories/mongo_repo.py`) so both paths
present identical Pydantic schemas to the rest of the app.

All primary keys are client-generated UUID4 strings (not auto-increment
integers) precisely so the same id format works whether the record ends up
in a SQL table or a Mongo collection.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class CameraORM(Base):
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120))
    # cam_type: "rtsp" (IP camera w/ credentials) | "webcam" (local device) |
    #           "upload" (a file the user uploaded) | "folder" (a file browsed
    #           from the server's sample_videos folder)
    cam_type: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(500))  # rtsp URL / device index / file path
    username: Mapped[str] = mapped_column(String(120), default="")
    password: Mapped[str] = mapped_column(String(120), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    simulation_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    loop_video: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    zones: Mapped[list["ZoneORM"]] = relationship(back_populates="camera", cascade="all, delete-orphan")


class ZoneORM(Base):
    __tablename__ = "zones"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"))
    name: Mapped[str] = mapped_column(String(120))
    # zone_type: entrance | atm | side_lane | forecourt | rear | restricted | other
    zone_type: Mapped[str] = mapped_column(String(30))
    restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    # immediate-alert rule: off | enter | near   (see schemas/zone.py)
    alert_mode: Mapped[str] = mapped_column(String(10), default="off", server_default="off")
    alert_severity: Mapped[str] = mapped_column(String(10), default="high", server_default="high")
    # normalised polygon points [[x,y], ...] with 0<=x,y<=1 (fraction of frame)
    polygon: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    camera: Mapped["CameraORM"] = relationship(back_populates="zones")


class GuardORM(Base):
    __tablename__ = "guards"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120))
    employee_id: Mapped[str] = mapped_column(String(60), default="")
    photo_paths: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EventORM(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    camera_id: Mapped[str] = mapped_column(String(32))
    camera_name: Mapped[str] = mapped_column(String(120), default="")
    zone_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    zone_name: Mapped[str] = mapped_column(String(120), default="")
    # scenario: loitering | gathering | movement | intrusion | anomaly | simulated
    scenario: Mapped[str] = mapped_column(String(30))
    # severity: info | low | medium | high | critical
    severity: Mapped[str] = mapped_column(String(20))
    # status: open | under_review | confirmed | false_positive | closed
    status: Mapped[str] = mapped_column(String(20), default="open")
    track_ids: Mapped[list] = mapped_column(JSON, default=list)
    message: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    snapshot_path: Mapped[str] = mapped_column(String(500), default="")
    clip_path: Mapped[str] = mapped_column(String(500), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    reviewer_remarks: Mapped[str] = mapped_column(Text, default="")
    dedupe_key: Mapped[str] = mapped_column(String(200), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
