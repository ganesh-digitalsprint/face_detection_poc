"""Reusable, named Grill Gate zone and processing configurations."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.database import Base

_JSON = JSON().with_variant(JSONB(), "postgresql")


class GrillGateZoneConfiguration(Base):
    __tablename__ = "grill_gate_zone_configurations"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_grill_gate_zone_configs_owner_name"),)

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    reference_width: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_height: Mapped[int] = mapped_column(Integer, nullable=False)
    config_json: Mapped[dict] = mapped_column(_JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
