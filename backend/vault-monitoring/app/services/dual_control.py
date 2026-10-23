"""Thread-safe, process-local coordinator for dual-custodian vault sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import secrets
import threading

from app.core.config import settings
from app.core.ml_config import load_ml_config_file


@dataclass(frozen=True)
class VerifiedCustodian:
    """Display details captured when a custodian is accepted into a session slot."""

    slot: int
    employee_id: str
    name: str
    department: str | None
    designation: str | None
    verified_at: datetime


@dataclass
class DualControlSession:
    session_id: str
    started_at: datetime
    expires_at: datetime
    required_persons: int
    liveness_session_id: str
    liveness_challenge: str
    # employee_id -> custodian record, in verification order.
    verified: dict[str, VerifiedCustodian] = field(default_factory=dict)
    status: str = "WAITING_FOR_FIRST_PERSON"
    handoff_until: float | None = None
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def remaining_seconds(self) -> int:
        return max(0, int((self.expires_at - datetime.now(timezone.utc)).total_seconds() + 0.999))

    @property
    def authenticated_employee_ids(self) -> set[str]:
        return set(self.verified)

    def custodians(self) -> list[VerifiedCustodian]:
        return sorted(self.verified.values(), key=lambda custodian: custodian.slot)


class DualControlSessionNotFoundError(LookupError):
    """The requested dual-control session does not exist."""


class DualControlSessionManager:
    def __init__(self, config_override=None) -> None:
        self._sessions: dict[str, DualControlSession] = {}
        self._lock = threading.RLock()
        self._config_override = config_override

    @property
    def config(self):
        if self._config_override is not None:
            return self._config_override
        configured = load_ml_config_file().vault_access.dual_control
        required_persons = (
            settings.VAULT_REQUIRED_PERSONS
            if settings.VAULT_REQUIRED_PERSONS is not None
            else configured.required_persons
        )
        allow_mode_select = (
            settings.VAULT_ALLOW_MODE_SELECT
            if settings.VAULT_ALLOW_MODE_SELECT is not None
            else configured.allow_mode_select
        )
        return configured.model_copy(update={
            "required_persons": required_persons,
            "allow_mode_select": allow_mode_select,
        })

    def start(
        self,
        liveness_session_id: str,
        challenge: str,
        required_persons: int | None = None,
    ) -> DualControlSession:
        if required_persons is not None and (
            type(required_persons) is not int or required_persons not in (1, 2)
        ):
            raise ValueError("required_persons must be 1 or 2")
        now = datetime.now(timezone.utc)
        config = self.config
        effective_required_persons = (
            required_persons
            if config.allow_mode_select and required_persons is not None
            else config.required_persons
        )
        session = DualControlSession(
            session_id=secrets.token_urlsafe(32),
            started_at=now,
            expires_at=now + timedelta(seconds=config.authorization_window_seconds),
            required_persons=effective_required_persons,
            liveness_session_id=liveness_session_id,
            liveness_challenge=challenge,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> DualControlSession:
        with self._lock:
            try:
                return self._sessions[session_id]
            except KeyError as exc:
                raise DualControlSessionNotFoundError("Dual-control session not found") from exc

    def discard(self, session_id: str) -> None:
        """Remove a completed session; missing IDs are intentionally harmless."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def expire_if_needed(self, session: DualControlSession) -> bool:
        if datetime.now(timezone.utc) < session.expires_at:
            return False
        session.verified = {}
        session.status = "EXPIRED"
        return True


_manager = DualControlSessionManager()


def get_dual_control_session_manager() -> DualControlSessionManager:
    return _manager
