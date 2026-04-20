from __future__ import annotations

import threading
import time

from sentinelops.config import settings


class LLMCircuitOpen(Exception):
    """Raised when a guarded LLM component is temporarily disabled after repeated failures."""


class _CircuitBreaker:
    """Tracks recent failures for one LLM component and opens briefly after repeated errors."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._lock = threading.Lock()
        self._failure_count = 0
        self._opened_until = 0.0
        self._last_error: str | None = None

    def ensure_available(self) -> None:
        """Raises when the breaker is open so callers can fail over immediately instead of waiting."""

        with self._lock:
            now = time.monotonic()
            if self._opened_until > now:
                remaining = max(0.0, self._opened_until - now)
                raise LLMCircuitOpen(f"{self.name} breaker open for another {remaining:.1f}s")
            if self._opened_until and now >= self._opened_until:
                self._opened_until = 0.0
                self._failure_count = 0

    def record_success(self) -> None:
        """Closes the breaker after a healthy request so transient failures do not linger."""

        with self._lock:
            self._failure_count = 0
            self._opened_until = 0.0
            self._last_error = None

    def record_failure(self, error: str, *, open_for_seconds: float | None = None) -> None:
        """Increments failure count and opens the breaker after the configured threshold or an explicit delay."""

        with self._lock:
            self._last_error = error
            if open_for_seconds is not None and open_for_seconds > 0:
                self._failure_count = 0
                self._opened_until = time.monotonic() + open_for_seconds
                return

            self._failure_count += 1
            if self._failure_count >= settings.LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD:
                self._opened_until = time.monotonic() + settings.LLM_CIRCUIT_BREAKER_RESET_SECONDS
                self._failure_count = 0

    def snapshot(self) -> dict:
        """Returns a serializable breaker state for health endpoints and dashboards."""

        with self._lock:
            now = time.monotonic()
            is_open = self._opened_until > now
            return {
                "name": self.name,
                "open": is_open,
                "open_for_seconds": round(max(0.0, self._opened_until - now), 3) if is_open else 0.0,
                "last_error": self._last_error,
            }


_BREAKERS = {
    "grouping": _CircuitBreaker("grouping"),
    "runbook_synthesis": _CircuitBreaker("runbook_synthesis"),
}


def get_breaker(name: str) -> _CircuitBreaker:
    """Returns a named breaker so different LLM components can fail independently."""

    return _BREAKERS[name]


def breaker_snapshots() -> dict[str, dict]:
    """Returns all breaker states for readiness reporting and dashboard diagnostics."""

    return {name: breaker.snapshot() for name, breaker in _BREAKERS.items()}
