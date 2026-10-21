"""Unit tests for the event schema and JSONL event store."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from governance.event_schema import Event, EventType, SchemaValidationError
from governance.event_store import JsonlEventStore

UTC = timezone.utc


def _event(event_id: str = "e1", task_id: str = "t1") -> Event:
    return Event(
        event_id=event_id,
        event_type=EventType.LOAN_REQUESTED,
        agent_id="loan-agent",
        run_id="r1",
        task_id=task_id,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        action="request_loan",
        decision="requested",
        evidence={"amount": 100},
    )


def test_event_roundtrip() -> None:
    event = _event()
    restored = Event.from_dict(event.to_dict())
    assert restored == event


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(SchemaValidationError, match="timezone-aware"):
        Event(
            event_type=EventType.LOAN_REQUESTED,
            agent_id="a",
            run_id="r",
            task_id="t",
            timestamp=datetime(2026, 1, 1),
        )


def test_sensitive_evidence_rejected() -> None:
    with pytest.raises(SchemaValidationError, match="sensitive"):
        Event(
            event_type=EventType.LOAN_REQUESTED,
            agent_id="a",
            run_id="r",
            task_id="t",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            evidence={"api_key": "sk-not-real"},
        )


def test_unknown_event_type_rejected() -> None:
    payload = _event().to_dict()
    payload["event_type"] = "loan.teleported"
    with pytest.raises(SchemaValidationError, match="unknown event_type"):
        Event.from_dict(payload)


def test_store_append_and_read(event_store) -> None:
    store = event_store()
    first, second = _event("e1"), _event("e2", task_id="t2")
    store.append(first)
    store.append(second)
    result = store.read_all()
    assert [event.event_id for event in result.events] == ["e1", "e2"]
    assert result.report.valid_events == 2
    assert result.report.malformed_records == 0


def test_store_skips_malformed_and_duplicates(tmp_path) -> None:
    store = JsonlEventStore(tmp_path / "events.jsonl", run_id="r1")
    store.append(_event("e1"))
    with store.path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
        handle.write(json.dumps({"event_id": "e2"}) + "\n")  # missing fields
        handle.write(json.dumps(_event("e1").to_dict()) + "\n")  # duplicate id
    result = store.read_all()
    assert [event.event_id for event in result.events] == ["e1"]
    assert result.report.malformed_records == 2
    assert result.report.duplicate_events == 1
    assert len(result.report.errors) == 2


def test_correlation_defaults_to_task_id() -> None:
    assert _event().correlation_id == "t1"
