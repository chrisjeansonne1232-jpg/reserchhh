"""Small HTTP client: rate limit + retry/backoff. Never logs headers (they carry the API keys)."""
from __future__ import annotations

import time

import requests

from .ratelimit import RateLimiter


class ProviderError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status, self.message = status, message


class Http:
    def __init__(self, headers: dict[str, str], limiter: RateLimiter, retries: int = 5, timeout: float = 60,
                 session: requests.Session | None = None, sleep=time.sleep):
        self._headers, self.limiter, self.retries, self.timeout = headers, limiter, retries, timeout
        self.session, self._sleep = session or requests.Session(), sleep

    def get_json(self, url: str, params: dict | None = None) -> dict:
        last = "no attempt"
        for attempt in range(self.retries + 1):
            self.limiter.wait()
            try:
                r = self.session.get(url, params=params, headers=self._headers, timeout=self.timeout)
            except requests.RequestException as e:  # network blip: retry
                last = type(e).__name__
                self._sleep(min(60, 2 ** attempt))
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                ra = r.headers.get("Retry-After")
                self._sleep(float(ra) if ra and ra.replace(".", "", 1).isdigit() else min(60, 2 ** (attempt + 1)))
                continue
            raise ProviderError(r.status_code, r.text[:200].replace("\n", " "))  # 4xx: not retryable
        raise ProviderError(0, f"gave up after {self.retries + 1} attempts ({last})")
