"""Server-side simulated door actuator."""
from __future__ import annotations
from typing import Protocol
from app.core.logging import get_logger

logger = get_logger(__name__)


class DoorController(Protocol):
    def unlock(self, session_id: str) -> None: ...
    def lock(self, session_id: str, reason: str) -> None: ...


class SimulatedDoorController:
    def __init__(self) -> None:
        self.locked = True

    def unlock(self, session_id: str) -> None:
        self.locked = False
        logger.info("SIMULATED_DOOR unlocked session=%s", session_id)

    def lock(self, session_id: str, reason: str) -> None:
        self.locked = True
        logger.info("SIMULATED_DOOR locked session=%s reason=%s", session_id, reason)
