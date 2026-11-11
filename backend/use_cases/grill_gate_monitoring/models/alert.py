"""Durable Grill Gate alert records, shaped for later Contract v1 mapping."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, Index, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.database import Base

_JsonDocument = JSON().with_variant(JSONB(), "postgresql")


def _uuid() -> str:
    return str(uuid.uuid4())


class GrillGateAlert(Base):
    __tablename__ = "grill_gate_alerts"
    __table_args__ = (
        CheckConstraint("use_case = 'grill_gate'", name="ck_grill_gate_alerts_use_case"),
        CheckConstraint("status IN ('OPEN','ACKNOWLEDGED','RESOLVED','DISMISSED')", name="ck_grill_gate_alerts_status"),
        Index("ix_grill_gate_alerts_assignment_status_time", "assignment_id", "status", "triggered_at"),
        Index("ix_grill_gate_alerts_camera_time", "camera_id", "triggered_at"),
        Index("ix_grill_gate_alerts_type_time", "source_event_type", "triggered_at"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=_uuid)
    source_event_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    source_event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    use_case: Mapped[str] = mapped_column(String(39), nullable=False, default="grill_gate")
    source_event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64))
    camera_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), index=True)
    camera_name: Mapped[str | None] = mapped_column(String(120))
    assignment_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), index=True)
    video_job_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN", index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    condition_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gate_open_duration_seconds: Mapped[float | None] = mapped_column(Float)
    configured_threshold_seconds: Mapped[float | None] = mapped_column(Float)
    deduplication_key: Mapped[str | None] = mapped_column(String(512))
    source_status: Mapped[str | None] = mapped_column(String(64))
    resource_refs: Mapped[dict] = mapped_column(_JsonDocument, nullable=False, default=dict)
    domain_data: Mapped[dict] = mapped_column(_JsonDocument, nullable=False, default=dict)
    evidence_refs: Mapped[list] = mapped_column(_JsonDocument, nullable=False, default=list)
    resolution_note: Mapped[str | None] = mapped_column(String(500))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 server_default=func.now(), onupdate=func.now())
