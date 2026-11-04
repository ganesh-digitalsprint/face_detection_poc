"""Common stable camera identities and assignment-scoped zones.

Branch Exterior's legacy camera and zone tables deliberately remain separate;
their existing IDs and cropped-frame polygon semantics are unchanged.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.database import Base

_JsonDocument = JSON().with_variant(JSONB(), "postgresql")


def _uuid() -> str:
    return str(uuid.uuid4())


class RegistryLocation(Base):
    __tablename__ = "registry_locations"
    __table_args__ = (UniqueConstraint("code", name="uq_registry_locations_code"),)

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(39), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class RegistryCamera(Base):
    __tablename__ = "registry_cameras"
    __table_args__ = (UniqueConstraint("location_id", "code", name="uq_registry_cameras_location_code"),)

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=_uuid)
    location_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("registry_locations.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(39), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CameraSource(Base):
    __tablename__ = "camera_sources"
    __table_args__ = (
        Index("uq_camera_sources_active_fingerprint", "fingerprint", unique=True,
              postgresql_where=text("is_active = true")),
        Index("ix_camera_sources_camera_active", "camera_id", "is_active"),
        CheckConstraint("purpose IN ('detection','evidence','both')", name="ck_camera_sources_purpose"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=_uuid)
    camera_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("registry_cameras.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # A server-side environment-variable reference, never a credential-bearing URL.
    connection_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(1024), nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False, default="both", server_default="both")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CameraUseCaseAssignment(Base):
    __tablename__ = "camera_use_case_assignments"
    __table_args__ = (
        UniqueConstraint("camera_id", "use_case", name="uq_camera_use_case_assignment"),
        Index("ix_camera_use_case_assignments_use_case_active", "use_case", "is_active"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=_uuid)
    camera_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("registry_cameras.id"), nullable=False, index=True)
    use_case: Mapped[str] = mapped_column(String(39), nullable=False)
    exclusive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    configuration: Mapped[dict] = mapped_column(_JsonDocument, nullable=False, default=dict, server_default=text("'{}'"))
    calibration: Mapped[dict | None] = mapped_column(_JsonDocument)
    zones_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class RegistryZone(Base):
    __tablename__ = "registry_zones"
    __table_args__ = (
        UniqueConstraint("assignment_id", "zone_key", name="uq_registry_zones_assignment_key"),
        Index("ix_registry_zones_assignment_enabled", "assignment_id", "enabled"),
        CheckConstraint("version >= 1", name="ck_registry_zones_version"),
        CheckConstraint("coordinate_system IN ('normalized_raw','normalized_cropped_analysis')",
                        name="ck_registry_zones_coordinate_system"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=_uuid)
    assignment_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("camera_use_case_assignments.id"), nullable=False)
    zone_key: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    zone_type: Mapped[str | None] = mapped_column(String(40))
    polygon: Mapped[list] = mapped_column(_JsonDocument, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(32))
    properties: Mapped[dict | None] = mapped_column(_JsonDocument)
    coordinate_system: Mapped[str] = mapped_column(String(40), nullable=False)
    calibration: Mapped[dict | None] = mapped_column(_JsonDocument)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    imported_batch_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
