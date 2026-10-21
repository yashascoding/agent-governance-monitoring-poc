"""Append-only JSON Lines event store with robust read semantics.

Reads tolerate malformed records (skipped and counted, never crash the
monitor), deduplicate repeated event IDs (first occurrence wins), and reject
naive timestamps through the schema layer.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

from governance.event_schema import Event, SchemaValidationError


@dataclass(frozen=True)
class ReadReport:
    total_lines: int = 0
    valid_events: int = 0
    malformed_records: int = 0
    duplicate_events: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReadResult:
    events: list[Event]
    report: ReadReport


class EventStoreError(Exception):
    """Raised for unrecoverable event-store failures."""


class JsonlEventStore:
    """JSONL-backed event store scoped to a single run."""

    def __init__(self, path: str | Path, run_id: str) -> None:
        self.path = Path(path)
        self.run_id = run_id
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, event: Event) -> None:
        line = json.dumps(event.to_dict(), sort_keys=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()

    def append_many(self, events: list[Event]) -> None:
        lines = [json.dumps(event.to_dict(), sort_keys=True) for event in events]
        payload = "\n".join(lines) + ("\n" if lines else "")
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()

    def read_all(self) -> ReadResult:
        if not self.path.exists():
            return ReadResult(events=[], report=ReadReport())
        events: list[Event] = []
        seen_ids: set[str] = set()
        total = malformed = duplicates = 0
        errors: list[str] = []
        text = self.path.read_text(encoding="utf-8")
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            total += 1
            try:
                payload = json.loads(line)
                event = Event.from_dict(payload)
            except (json.JSONDecodeError, SchemaValidationError) as exc:
                malformed += 1
                errors.append(f"line {line_number}: {exc}")
                continue
            if event.event_id in seen_ids:
                duplicates += 1
                continue
            seen_ids.add(event.event_id)
            events.append(event)
        return ReadResult(
            events=events,
            report=ReadReport(
                total_lines=total,
                valid_events=len(events),
                malformed_records=malformed,
                duplicate_events=duplicates,
                errors=errors,
            ),
        )
