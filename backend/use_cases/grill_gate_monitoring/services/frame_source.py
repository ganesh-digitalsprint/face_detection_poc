"""Frame-source contracts shared by live camera and uploaded-video processing."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class FramePacketLike(Protocol):
    width: int
    height: int
    frame: object
    captured_monotonic: float
    captured_at: object
    sequence_number: int


@runtime_checkable
class FrameSource(Protocol):
    """Pull-based source. Implementations must return ``None`` on timeout/end."""

    @property
    def closed(self) -> bool: ...

    def get(self, timeout: float | None = None) -> FramePacketLike | None: ...

    def close(self) -> None: ...


class LiveCameraFrameSource:
    """Adapter over the existing camera worker subscription; it owns no capture."""

    def __init__(self, subscription: FrameSource):
        self._subscription = subscription

    @property
    def closed(self) -> bool:
        return self._subscription.closed

    def get(self, timeout: float | None = None) -> FramePacketLike | None:
        return self._subscription.get(timeout=timeout)

    def close(self) -> None:
        self._subscription.close()
