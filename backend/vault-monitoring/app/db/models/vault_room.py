"""Audit records for simulated vault-room sessions."""
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class VaultRoomSession(Base):
    __tablename__ = "vault_room_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Legacy column retained for compatibility; token values are redacted by
    # migration and new writes use the UUID session reference only.
    dual_control_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    session_ref: Mapped[str | None] = mapped_column(String(36), index=True)
    employees: Mapped[list] = mapped_column(JSON, nullable=False)
    required_persons: Mapped[int] = mapped_column(Integer, nullable=False)
    test_mode: Mapped[bool] = mapped_column(Boolean, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    expired_before_close: Mapped[bool] = mapped_column(Boolean, nullable=False)
    expired_alert_count: Mapped[int] = mapped_column(Integer, nullable=False)
    peak_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    seconds_at_count: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    alert_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    count_at_expiry: Mapped[int | None] = mapped_column(Integer)
    count_at_close: Mapped[int | None] = mapped_column(Integer)


class VaultRoomEvent(Base):
    __tablename__ = "vault_room_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VaultRoomAlert(Base):
    __tablename__ = "vault_room_alerts"
    __table_args__ = (
        CheckConstraint("status IN ('OPEN','ACKNOWLEDGED','RESOLVED','DISMISSED')", name="ck_vault_room_alerts_status"),
        CheckConstraint("occurrence_count >= 1", name="ck_vault_room_alerts_occurrence_count"),
        CheckConstraint("count_at_open IS NULL OR count_at_open >= 0", name="ck_vault_room_alerts_count_at_open"),
        CheckConstraint("expected IS NULL OR expected >= 0", name="ck_vault_room_alerts_expected"),
        CheckConstraint("observed_count IS NULL OR observed_count >= 0", name="ck_vault_room_alerts_observed_count"),
        CheckConstraint("required_count IS NULL OR required_count >= 0", name="ck_vault_room_alerts_required_count"),
        Index("ix_vault_room_alerts_status_created", "status", "created_at"),
        Index("ix_vault_room_alerts_severity", "severity"),
        Index("ix_vault_room_alerts_type", "type"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Active sessions are process-local and only archived at session end, so
    # this reference intentionally cannot FK to vault_room_sessions.
    session_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    count_at_open: Mapped[int | None] = mapped_column(Integer)
    expected: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column()
    title: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="VAULT_MONITORING", server_default="VAULT_MONITORING")
    observed_count: Mapped[int | None] = mapped_column(Integer)
    required_count: Mapped[int | None] = mapped_column(Integer)
    camera_id: Mapped[str | None] = mapped_column(String(128), index=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN", server_default="OPEN")
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(String(128))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(128))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_by: Mapped[str | None] = mapped_column(String(128))
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("vault_incidents.id", ondelete="SET NULL"), index=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict, server_default=text("'{}'"))
    session_ref: Mapped[str | None] = mapped_column(String(36), index=True)
    dedup_key: Mapped[str | None] = mapped_column(String(512))
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolution_source: Mapped[str | None] = mapped_column(String(16))
    evidence_status: Mapped[str] = mapped_column(String(16), nullable=False, default="NONE", server_default="NONE")


class VaultIncident(Base):
    __tablename__ = "vault_incidents"
    __table_args__ = (
        CheckConstraint("status IN ('OPEN','INVESTIGATING','RESOLVED','CLOSED')", name="ck_vault_incidents_status"),
        CheckConstraint("severity IN ('INFO','WARNING','HIGH','CRITICAL')", name="ck_vault_incidents_severity"),
        Index("ix_vault_incidents_status_updated", "status", "updated_at"),
        Index("uq_vault_incidents_active_session", "session_ref", unique=True,
              postgresql_where=text("session_ref IS NOT NULL AND status IN ('OPEN','INVESTIGATING')")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    incident_number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN", server_default="OPEN")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="WARNING", server_default="WARNING")
    session_id: Mapped[str | None] = mapped_column(String(36), index=True)
    camera_id: Mapped[str | None] = mapped_column(String(128), index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(128))
    retention_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict, server_default=text("'{}'"))
    session_ref: Mapped[str | None] = mapped_column(String(36), index=True)
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    hold_reason: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class VaultEvidence(Base):
    __tablename__ = "vault_evidence"
    __table_args__ = (
        CheckConstraint("alert_id IS NOT NULL OR incident_id IS NOT NULL", name="ck_vault_evidence_parent"),
        CheckConstraint("width IS NULL OR width > 0", name="ck_vault_evidence_width"),
        CheckConstraint("height IS NULL OR height > 0", name="ck_vault_evidence_height"),
        CheckConstraint("file_size_bytes IS NULL OR file_size_bytes >= 0", name="ck_vault_evidence_size"),
        UniqueConstraint("storage_provider", "storage_public_id", name="uq_vault_evidence_storage_public_id"),
        Index("ix_vault_evidence_incident", "incident_id"), Index("ix_vault_evidence_alert", "alert_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("vault_incidents.id", ondelete="RESTRICT"))
    alert_id: Mapped[str | None] = mapped_column(ForeignKey("vault_room_alerts.id", ondelete="RESTRICT"))
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="CLOUDINARY", server_default="CLOUDINARY")
    storage_delivery_type: Mapped[str] = mapped_column(String(24), nullable=False, default="authenticated", server_default="authenticated")
    storage_public_id: Mapped[str | None] = mapped_column(String(255))
    resource_type: Mapped[str | None] = mapped_column(String(32))
    asset_format: Mapped[str | None] = mapped_column(String(16))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    uploaded_by: Mapped[str | None] = mapped_column(String(128))
    session_id: Mapped[str | None] = mapped_column(String(36), index=True)
    camera_id: Mapped[str | None] = mapped_column(String(128), index=True)
    comment: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str | None] = mapped_column(String(128))
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict, server_default=text("'{}'"))
    session_ref: Mapped[str | None] = mapped_column(String(36), index=True)
    thumbnail_public_id: Mapped[str | None] = mapped_column(String(255))


class VaultIncidentComment(Base):
    __tablename__ = "vault_incident_comments"
    __table_args__ = (Index("ix_vault_incident_comments_incident_created", "incident_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("vault_incidents.id", ondelete="RESTRICT"), nullable=False)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("vault_evidence.id", ondelete="RESTRICT"))
    author_id: Mapped[str] = mapped_column(String(128), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VaultAuditEvent(Base):
    __tablename__ = "vault_audit_events"
    __table_args__ = (Index("ix_vault_audit_entity", "entity_type", "entity_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default=text("'{}'"))


class VaultSession(Base):
    """Persisted lifecycle using only the public UUID session reference."""
    __tablename__ = "vault_sessions"
    __table_args__ = (CheckConstraint("required_persons IN (1,2)", name="ck_vault_sessions_required_persons"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    required_persons: Mapped[int] = mapped_column(Integer, nullable=False)
    camera_id: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(64))


class VaultAlertCondition(Base):
    """Durable edge/episode state so workers can recover after restart."""
    __tablename__ = "vault_alert_conditions"
    condition_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    session_ref: Mapped[str | None] = mapped_column(String(36), index=True)
    camera_id: Mapped[str | None] = mapped_column(String(128), index=True)
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    discriminator: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    episode: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    clear_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_touch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_alert_id: Mapped[str | None] = mapped_column(String(36))
    operator_closed_episode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
