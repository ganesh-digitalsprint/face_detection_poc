"""Time-windowed stable count filtering, independent of cameras and persistence."""
from __future__ import annotations

from collections import Counter, deque
from collections.abc import Callable


class StableCounter:
    def __init__(self, *, window_seconds: float, min_samples: int, majority_ratio: float,
                 stale_seconds: float, clock: Callable[[], float] | None = None):
        self.window_seconds = window_seconds
        self.min_samples = min_samples
        self.majority_ratio = majority_ratio
        self.stale_seconds = stale_seconds
        self._clock = clock
        self._samples: deque[tuple[float, int]] = deque()
        self._stable: int | None = None

    def feed(self, now: float, raw_count: int) -> int | None:
        if raw_count < 0:
            raise ValueError("raw_count must be nonnegative")
        self._samples.append((now, raw_count))
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        counts = Counter(value for _, value in self._samples)
        if len(self._samples) >= self.min_samples:
            value, votes = counts.most_common(1)[0]
            if votes / len(self._samples) >= self.majority_ratio:
                self._stable = value
        return self._stable

    def stable_count(self, now: float) -> int | None:
        if not self._samples or now - self._samples[-1][0] >= self.stale_seconds:
            return None
        return self._stable

    @property
    def last_feed_at(self) -> float | None:
        return self._samples[-1][0] if self._samples else None

    def reset(self) -> None:
        self._samples.clear()
        self._stable = None
