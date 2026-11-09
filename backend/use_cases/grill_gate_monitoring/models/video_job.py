"""Persisted metadata for an isolated uploaded-video processing job."""
from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, func, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid
from app.db.database import Base

_JSON = JSON().with_variant(JSONB(), "postgresql")


class GrillGateVideoJob(Base):
    __tablename__ = "grill_gate_video_jobs"
    __table_args__ = (Index("ix_grill_gate_video_jobs_status_created", "status", "created_at"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="UPLOADED")
    asset_job_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), ForeignKey("grill_gate_video_jobs.id"), nullable=True, index=True)
    template_assignment_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False))
    config_snapshot: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
