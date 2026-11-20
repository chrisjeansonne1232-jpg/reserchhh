"""Sliding-window rate limiter (thread-safe)."""
from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, max_calls: int, per_seconds: float, clock=time.monotonic, sleep=time.sleep):
        self.max_calls, self.per, self._clock, self._sleep = max_calls, per_seconds, clock, sleep
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def wait(self) -> float:
        """Block until a call is allowed; returns seconds slept."""
        slept = 0.0
        with self._lock:
            while True:
                now = self._clock()
                while self._calls and now - self._calls[0] >= self.per:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return slept
                delay = self.per - (now - self._calls[0]) + 0.01
                self._sleep(delay)
                slept += delay
