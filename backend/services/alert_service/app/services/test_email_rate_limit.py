from __future__ import annotations

import threading
import time


class TestEmailRateLimiter:
    __test__ = False

    def __init__(self, interval_seconds: float = 60):
        self.interval_seconds = interval_seconds
        self._accepted: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def allow(self, actor_id: str, branch_id: str) -> bool:
        now = time.monotonic()
        key = (actor_id, branch_id)
        with self._lock:
            previous = self._accepted.get(key)
            if previous is not None and now - previous < self.interval_seconds:
                return False
            self._accepted[key] = now
            return True
