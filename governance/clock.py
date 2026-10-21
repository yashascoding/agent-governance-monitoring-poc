"""Injectable clocks so agents and tests never sleep or depend on wall time."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """Real wall-clock time, always timezone-aware UTC."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class SimulatedClock:
    """Deterministic clock for tests and simulated legacy scenarios."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("SimulatedClock requires a timezone-aware start time")
        self._current = start.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self._current

    def advance(self, seconds: float) -> datetime:
        self._current = self._current + timedelta(seconds=seconds)
        return self._current
