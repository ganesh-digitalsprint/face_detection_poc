"""Durable Grill Gate crossing and mesh event records."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, Index, Integer, JSON, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.database import Base

_JsonDocument = JSON().with_variant(JSONB(), "postgresql")


def _uuid() -> str:
    return str(uuid.uuid4())


class GrillGateEvent(Base):
    __tablename__ = "grill_gate_events"
    __table_args__ = (
        CheckConstraint("event_type IN ('CROSSING_COMPLETED','MESH_PERSON_ENTERED','MESH_PERSON_EXITED')",
                        name="ck_grill_gate_events_event_type"),
        Index("ix_grill_gate_events_assignment_time", "assignment_id", "occurred_at"),
        Index("ix_grill_gate_events_camera_time", "camera_id", "occurred_at"),
        Index("ix_grill_gate_events_assignment_type_time", "assignment_id", "event_type", "occurred_at"),
        Index("ix_grill_gate_events_type_time", "event_type", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=_uuid)
    camera_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    assignment_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False, default="LIVE_CAMERA")
    video_job_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    video_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    template_assignment_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    track_id: Mapped[int | None] = mapped_column(Integer)
    direction: Mapped[str | None] = mapped_column(String(32))
    source_zone: Mapped[str | None] = mapped_column(String(40))
    destination_zone: Mapped[str | None] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", _JsonDocument, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 server_default=func.now())
