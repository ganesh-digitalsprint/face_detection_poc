"""Validation, confirmation and fallback for discrete gate classifier results."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

CLASS_TO_STATE = {
    "closed": "CLOSED",
    "partially_open": "PARTIALLY_OPEN",
    "fully_open": "FULLY_OPEN",
}
VALID_STATES = frozenset(CLASS_TO_STATE.values())


@dataclass(frozen=True)
class ClassificationUpdate:
    state: str
    confirmed_state: str | None
    confidence: float | None
    valid: bool
    stale: bool
    using_fallback: bool
    direction: str | None = None


class GateClassificationTracker:
    """Require repeat valid classifications and retain the last one for a bounded time."""

    def __init__(self, *, confirmation_frames: int = 2, stale_after_seconds: float = 2.0,
                 minimum_confidence: float = 0.0):
        if confirmation_frames < 1 or stale_after_seconds <= 0:
            raise ValueError("confirmation_frames and stale_after_seconds must be positive")
        self.confirmation_frames = confirmation_frames
        self.stale_after_seconds = stale_after_seconds
        self.minimum_confidence = minimum_confidence
        self.confirmed_state: str | None = None
        self.confirmed_at: float | None = None
        self.confidence: float | None = None
        self.direction: str | None = None
        self._candidate: str | None = None
        self._count = 0

    @staticmethod
    def parse(result) -> tuple[str | None, float | None]:
        if not isinstance(result, dict):
            return None, None
        label = result.get("class", result.get("prediction", result.get("label")))
        confidence = result.get("confidence")
        if not isinstance(label, str) or not label.strip() or isinstance(confidence, bool):
            return None, None
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            return None, None
        if not 0 <= confidence <= 1:
            return None, None
        return CLASS_TO_STATE.get(label.strip().lower()), confidence

    def update(self, result, now: float) -> ClassificationUpdate:
        state, confidence = self.parse(result)
        valid = state is not None and confidence is not None and confidence >= self.minimum_confidence
        changed = False
        if valid:
            if state == self._candidate:
                self._count += 1
            else:
                self._candidate, self._count = state, 1
            if self._count >= self.confirmation_frames:
                if state != self.confirmed_state:
                    previous = self.confirmed_state
                    self.confirmed_state = state
                    if previous == "CLOSED" and state == "PARTIALLY_OPEN":
                        self.direction = "OPENING"
                    elif previous == "FULLY_OPEN" and state == "PARTIALLY_OPEN":
                        self.direction = "CLOSING"
                    elif previous == "PARTIALLY_OPEN" and state == "FULLY_OPEN":
                        self.direction = "OPENING"
                    elif previous == "PARTIALLY_OPEN" and state == "CLOSED":
                        self.direction = "CLOSING"
                    else:
                        self.direction = None
                    changed = True
                self.confirmed_at, self.confidence = now, confidence
        stale = self.confirmed_at is None or now - self.confirmed_at > self.stale_after_seconds
        displayed = "UNKNOWN" if stale else self.confirmed_state
        return ClassificationUpdate(displayed, self.confirmed_state, confidence if valid else self.confidence,
                                    bool(valid), stale, not valid and not stale, self.direction)
