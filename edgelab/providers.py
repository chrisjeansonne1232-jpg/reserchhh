"""Shared plumbing for market-data providers: credentials, pacing, redaction.

Credentials are read from the environment ONLY, sent ONLY as request headers, and scrubbed from every exception
message and log line. Nothing here prints, stores or returns a key.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request


class ProviderError(Exception):
    """A provider call failed. The message is guaranteed not to contain credentials."""


class MissingCredentials(ProviderError):
    pass


class RecentDataRefused(ProviderError):
    """Requested window ends inside the provider's real-time embargo (free SIP is historical-only)."""


def require_env(*names: str) -> dict[str, str]:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise MissingCredentials(f"missing environment variable(s): {', '.join(missing)}")
    return {n: os.environ[n] for n in names}


def redact(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s and len(s) >= 6:
            text = text.replace(s, "***")
    # belt and braces: any apiKey=... query parameter, or key-shaped header echo
    text = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+", "Bearer ***", text)
    return re.sub(r"(?i)(api[_-]?key|secret(?:[_-]?key)?|key[_-]?id|authorization)([\"'=: ]+)(?!\*\*\*|Bearer \*\*\*)[^\s\"'&,}]+", r"\1\2***", text)


class Throttle:
    """Minimum spacing between calls (calls_per_minute), plus a shared back-off after a 429."""

    def __init__(self, calls_per_minute: float):
        self.gap = 60.0 / calls_per_minute
        self.next_ok = 0.0

    def wait(self):
        now = time.monotonic()
        if now < self.next_ok:
            time.sleep(self.next_ok - now)
        self.next_ok = max(now, self.next_ok) + self.gap

    def penalise(self, seconds: float):
        self.next_ok = max(self.next_ok, time.monotonic() + seconds)


class HttpClient:
    def __init__(self, base: str, headers: dict[str, str], secrets: list[str], calls_per_minute: float, retries: int = 5):
        self.base, self._headers, self._secrets = base.rstrip("/"), headers, secrets
        self.throttle, self.retries = Throttle(calls_per_minute), retries
        self.n_calls = 0

    def get_json(self, url_or_path: str, params: dict | None = None) -> dict:
        url = url_or_path if url_or_path.startswith("http") else self.base + url_or_path
        if params:
            from urllib.parse import urlencode
            url += ("&" if "?" in url else "?") + urlencode({k: v for k, v in params.items() if v is not None})
        last = ""
        for attempt in range(self.retries):
            self.throttle.wait()
            req = urllib.request.Request(url, headers=self._headers)
            try:
                self.n_calls += 1
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                body = redact(e.read()[:300].decode(errors="replace"), self._secrets)
                last = f"HTTP {e.code}: {body}"
                if e.code == 429:
                    self.throttle.penalise(float(e.headers.get("Retry-After") or 15) + attempt * 10)
                    continue
                if e.code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                raise ProviderError(f"{redact(url, self._secrets).split('?')[0]} -> {last}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = redact(repr(e), self._secrets)
                time.sleep(2 ** attempt)
        raise ProviderError(f"{redact(url, self._secrets).split('?')[0]} failed after {self.retries} attempts: {last}")
