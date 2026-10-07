"""Thread-safe, process-local coordinator for dual-custodian vault sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import secrets
import threading

from app.core.ml_config import load_ml_config_file


@dataclass
class DualControlSession:
    session_id: str
    started_at: datetime
    expires_at: datetime
    required_persons: int
    liveness_session_id: str
    liveness_challenge: str
    authenticated_employee_ids: set[str] = field(default_factory=set)
    status: str = "WAITING_FOR_FIRST_PERSON"
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def remaining_seconds(self) -> int:
        return max(0, int((self.expires_at - datetime.now(timezone.utc)).total_seconds() + 0.999))


class DualControlSessionNotFoundError(LookupError):
    """The requested dual-control session does not exist."""


class DualControlSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, DualControlSession] = {}
        self._lock = threading.RLock()

    @property
    def config(self):
        return load_ml_config_file().vault_access.dual_control

    def start(self, liveness_session_id: str, challenge: str) -> DualControlSession:
        now = datetime.now(timezone.utc)
        config = self.config
        session = DualControlSession(
            session_id=secrets.token_urlsafe(32),
            started_at=now,
            expires_at=now + timedelta(seconds=config.authorization_window_seconds),
            required_persons=config.required_persons,
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

    def expire_if_needed(self, session: DualControlSession) -> bool:
        if datetime.now(timezone.utc) < session.expires_at:
            return False
        session.authenticated_employee_ids.clear()
        session.status = "EXPIRED"
        return True


_manager = DualControlSessionManager()


def get_dual_control_session_manager() -> DualControlSessionManager:
    return _manager
