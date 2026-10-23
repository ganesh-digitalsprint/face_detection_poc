"""Audit records for simulated vault-room sessions."""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class VaultRoomSession(Base):
    __tablename__ = "vault_room_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dual_control_session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
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
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    count_at_open: Mapped[int | None] = mapped_column(Integer)
    expected: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column()
