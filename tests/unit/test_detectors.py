"""Unit tests for individual detectors."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from governance.detectors import (
    EventSequenceDetector,
    MissingHumanAuthorizationDetector,
    DataAccessDetector,
    TaskDurationDetector,
    UnauthorizedApprovalDetector,
)
from governance.event_schema import Event, EventType

UTC = timezone.utc
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def ev(
    event_type: EventType,
    *,
    task_id: str = "t1",
    agent_id: str = "loan-agent",
    ts: datetime | None = None,
    decision: str | None = None,
    evidence: dict | None = None,
    resource: str | None = None,
    event_id: str | None = None,
    correlation_id: str | None = None,
) -> Event:
    kwargs = {}
    if event_id:
        kwargs["event_id"] = event_id
    return Event(
        event_type=event_type,
        agent_id=agent_id,
        run_id="r1",
        task_id=task_id,
        timestamp=ts or NOW,
        decision=decision,
        evidence=evidence or {},
        resource=resource,
        correlation_id=correlation_id,
        **kwargs,
    )


class TestMissingHumanAuthorization:
    def detect(self, events, policy, now=NOW):
        return MissingHumanAuthorizationDetector().detect(events, policy, now)

    def test_small_loan_needs_no_authorization(self, policy) -> None:
        events = [
            ev(EventType.LOAN_REQUESTED, evidence={"amount": 800}),
            ev(EventType.LOAN_APPROVED, decision="approved", evidence={"amount": 800}),
        ]
        assert self.detect(events, policy) == []

    def test_authorized_loan_clean(self, policy) -> None:
        events = [
            ev(EventType.LOAN_REQUESTED, evidence={"amount": 1500}),
            ev(EventType.HUMAN_APPROVAL_GRANTED, decision="granted"),
            ev(EventType.LOAN_APPROVED, decision="approved", evidence={"amount": 1500}),
        ]
        assert self.detect(events, policy) == []

    def test_blocked_attempt_is_critical(self, policy) -> None:
        events = [
            ev(EventType.LOAN_REQUESTED, evidence={"amount": 1500}),
            ev(EventType.LOAN_APPROVAL_BLOCKED, decision="blocked",
               evidence={"amount": 1500, "bypass_attempted": True}),
        ]
        findings = self.detect(events, policy)
        assert len(findings) == 1
        assert findings[0].severity.value == "CRITICAL"
        assert findings[0].status.value == "OPEN"
        assert findings[0].key_evidence["bypass_attempted"] is True

    def test_incomplete_workflow_within_deadline_is_pending(self, policy) -> None:
        events = [
            ev(EventType.LOAN_REQUESTED, ts=NOW - timedelta(seconds=60), evidence={"amount": 1500}),
            ev(EventType.HUMAN_APPROVAL_REQUESTED, ts=NOW - timedelta(seconds=30)),
        ]
        findings = self.detect(events, policy, now=NOW)
        assert len(findings) == 1
        assert findings[0].status.value == "PENDING_INVESTIGATION"
        assert findings[0].severity.value == "LOW"

    def test_incomplete_workflow_past_deadline_escalates(self, policy) -> None:
        events = [
            ev(EventType.LOAN_REQUESTED, ts=NOW - timedelta(seconds=10_000),
               evidence={"amount": 1500}),
        ]
        findings = self.detect(events, policy, now=NOW)
        assert len(findings) == 1
        assert findings[0].severity.value == "CRITICAL"
        assert findings[0].status.value == "OPEN"


class TestUnauthorizedApproval:
    def detect(self, events, policy):
        return UnauthorizedApprovalDetector().detect(events, policy, NOW)

    def test_final_approval_without_grant_is_critical(self, policy) -> None:
        events = [
            ev(EventType.LOAN_REQUESTED, evidence={"amount": 1500}),
            ev(EventType.HUMAN_APPROVAL_DENIED, decision="denied"),
            ev(EventType.LOAN_APPROVED, decision="approved", evidence={"amount": 1500}),
        ]
        findings = self.detect(events, policy)
        assert len(findings) == 1
        assert findings[0].severity.value == "CRITICAL"
        assert findings[0].key_evidence["authorization_denied_recorded"] is True

    def test_final_approval_with_grant_is_clean(self, policy) -> None:
        events = [
            ev(EventType.LOAN_REQUESTED, evidence={"amount": 1500}),
            ev(EventType.HUMAN_APPROVAL_GRANTED),
            ev(EventType.LOAN_APPROVED, evidence={"amount": 1500}),
        ]
        assert self.detect(events, policy) == []


class TestTaskDuration:
    def detect(self, events, policy):
        return TaskDurationDetector().detect(events, policy, NOW)

    def test_short_duration_flagged(self, policy) -> None:
        events = [
            ev(EventType.TASK_COMPLETED, agent_id="task-agent", task_id="t6",
               evidence={"duration_seconds": 10, "observed_duration_seconds": 10})
        ]
        findings = self.detect(events, policy)
        assert len(findings) == 1
        assert findings[0].severity.value == "MEDIUM"
        assert findings[0].rule_id == "RULE-TASK-001"

    def test_normal_duration_clean(self, policy) -> None:
        events = [
            ev(EventType.TASK_COMPLETED, agent_id="task-agent",
               evidence={"duration_seconds": 300, "observed_duration_seconds": 300})
        ]
        assert self.detect(events, policy) == []

    def test_duration_recomputed_from_timestamps_when_not_reported(self, policy) -> None:
        start = NOW
        end = NOW + timedelta(seconds=10)
        events = [
            ev(EventType.TASK_COMPLETED, agent_id="task-agent", ts=end,
               evidence={"start_timestamp": start.isoformat(),
                         "end_timestamp": end.isoformat()})
        ]
        findings = self.detect(events, policy)
        assert len(findings) == 1


class TestDataAccess:
    def detect(self, events, policy):
        return DataAccessDetector().detect(events, policy, NOW)

    def test_denied_attempt_medium(self, policy) -> None:
        events = [
            ev(EventType.DATA_ACCESS_DENIED, agent_id="data-agent",
               resource="loan_applications", decision="denied")
        ]
        findings = self.detect(events, policy)
        assert len(findings) == 1
        assert findings[0].severity.value == "MEDIUM"
        assert findings[0].rule_id == "RULE-DATA-001"

    def test_unauthorized_read_high(self, policy) -> None:
        events = [
            ev(EventType.DATA_ACCESS_GRANTED, agent_id="data-agent",
               resource="loan_applications"),
            ev(EventType.DATA_READ_COMPLETED, agent_id="data-agent",
               resource="loan_applications", evidence={"rows_read": 5}),
        ]
        findings = self.detect(events, policy)
        assert len(findings) == 1  # one finding keyed per resource
        assert findings[0].severity.value == "HIGH"
        assert findings[0].rule_id == "RULE-DATA-002"

    def test_authorized_access_clean(self, policy) -> None:
        events = [
            ev(EventType.DATA_ACCESS_GRANTED, agent_id="data-agent",
               resource="public_test_data"),
            ev(EventType.DATA_READ_COMPLETED, agent_id="data-agent",
               resource="public_test_data"),
        ]
        assert self.detect(events, policy) == []


class TestEventSequence:
    def detect(self, events, policy):
        return EventSequenceDetector().detect(events, policy, NOW)

    def test_out_of_order_authorization(self, policy) -> None:
        events = [
            ev(EventType.LOAN_REQUESTED, evidence={"amount": 1500}),
            ev(EventType.HUMAN_APPROVAL_GRANTED),
            ev(EventType.HUMAN_APPROVAL_REQUESTED),
        ]
        findings = self.detect(events, policy)
        assert any(f.rule_id == "RULE-SEQ-001" for f in findings)

    def test_conflicting_finals_high(self, policy) -> None:
        events = [
            ev(EventType.LOAN_REQUESTED, evidence={"amount": 800}),
            ev(EventType.LOAN_APPROVED, evidence={"amount": 800}),
            ev(EventType.LOAN_REJECTED),
        ]
        findings = self.detect(events, policy)
        conflicting = [f for f in findings if f.key_evidence.get("kind") == "conflicting_final_outcomes"]
        assert len(conflicting) == 1
        assert conflicting[0].severity.value == "HIGH"

    def test_missing_prerequisite(self, policy) -> None:
        events = [ev(EventType.LOAN_APPROVED, evidence={"amount": 1500})]
        findings = self.detect(events, policy)
        missing = [f for f in findings if f.key_evidence.get("kind") == "missing_prerequisite"]
        assert missing and missing[0].severity.value == "MEDIUM"

    def test_ordered_workflow_clean(self, policy) -> None:
        events = [
            ev(EventType.LOAN_REQUESTED, evidence={"amount": 1500}),
            ev(EventType.HUMAN_APPROVAL_REQUESTED),
            ev(EventType.HUMAN_APPROVAL_GRANTED),
            ev(EventType.LOAN_APPROVED, evidence={"amount": 1500}),
        ]
        assert self.detect(events, policy) == []
