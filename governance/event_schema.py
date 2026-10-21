"""Shared structured event schema for all agents.

Raw agent events are kept strictly separate from monitoring findings and
alerts. Events never contain secrets, credentials, or personal data; agents
are expected to pass only synthetic identifiers and amounts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(str, Enum):
    LOAN_REQUESTED = "loan.requested"
    HUMAN_APPROVAL_REQUESTED = "human_approval.requested"
    HUMAN_APPROVAL_GRANTED = "human_approval.granted"
    HUMAN_APPROVAL_DENIED = "human_approval.denied"
    LOAN_APPROVAL_BLOCKED = "loan.approval_blocked"
    LOAN_APPROVED = "loan.approved"
    LOAN_REJECTED = "loan.rejected"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    DATA_ACCESS_REQUESTED = "data.access_requested"
    DATA_ACCESS_GRANTED = "data.access_granted"
    DATA_ACCESS_DENIED = "data.access_denied"
    DATA_READ_COMPLETED = "data.read_completed"


class SchemaValidationError(ValueError):
    """Raised when an event record cannot be validated."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_utc_iso(value: datetime) -> str:
    """Render a timezone-aware datetime as an ISO-8601 UTC string with 'Z'."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchemaValidationError("timestamp must be timezone-aware (UTC)")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc_iso(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise SchemaValidationError("timestamp must be a non-empty ISO-8601 string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SchemaValidationError(f"invalid ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SchemaValidationError("timestamp must be timezone-aware (UTC)")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class Event:
    """A single structured action record emitted by a task agent."""

    event_type: EventType
    agent_id: str
    run_id: str
    task_id: str
    timestamp: datetime
    action: str = ""
    resource: str | None = None
    policy_id: str | None = None
    decision: str | None = None
    correlation_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        if not self.agent_id:
            raise SchemaValidationError("agent_id is required")
        if not self.run_id:
            raise SchemaValidationError("run_id is required")
        if not self.task_id:
            raise SchemaValidationError("task_id is required")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise SchemaValidationError("timestamp must be timezone-aware (UTC)")
        if self.correlation_id is None:
            object.__setattr__(self, "correlation_id", self.task_id)
        _reject_sensitive_evidence(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": to_utc_iso(self.timestamp),
            "agent_id": self.agent_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "event_type": self.event_type.value,
            "action": self.action,
            "resource": self.resource,
            "policy_id": self.policy_id,
            "decision": self.decision,
            "correlation_id": self.correlation_id,
            "evidence": dict(self.evidence),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Event":
        if not isinstance(payload, dict):
            raise SchemaValidationError("event record must be a JSON object")
        required = ("event_type", "agent_id", "run_id", "task_id", "timestamp")
        missing = [key for key in required if key not in payload]
        if missing:
            raise SchemaValidationError(f"event missing required fields: {missing}")
        try:
            event_type = EventType(payload["event_type"])
        except ValueError as exc:
            raise SchemaValidationError(
                f"unknown event_type: {payload['event_type']!r}"
            ) from exc
        evidence = payload.get("evidence", {})
        if evidence is None:
            evidence = {}
        if not isinstance(evidence, dict):
            raise SchemaValidationError("evidence must be a JSON object")
        return cls(
            event_id=str(payload.get("event_id") or uuid.uuid4()),
            timestamp=parse_utc_iso(payload["timestamp"]),
            agent_id=str(payload["agent_id"]),
            run_id=str(payload["run_id"]),
            task_id=str(payload["task_id"]),
            event_type=event_type,
            action=str(payload.get("action") or ""),
            resource=payload.get("resource"),
            policy_id=payload.get("policy_id"),
            decision=payload.get("decision"),
            correlation_id=payload.get("correlation_id"),
            evidence=dict(evidence),
        )


_FORBIDDEN_EVIDENCE_KEYS = {
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "credentials",
    "ssn",
    "aadhaar",
    "pan",
    "card_number",
    "account_number",
}


def _reject_sensitive_evidence(evidence: dict[str, Any]) -> None:
    for key in evidence:
        lowered = key.lower()
        if any(bad in lowered for bad in _FORBIDDEN_EVIDENCE_KEYS):
            raise SchemaValidationError(
                f"evidence key {key!r} looks sensitive and must not be logged"
            )
