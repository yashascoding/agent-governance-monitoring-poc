"""Unit tests for audit report generation and the optional CloudTrail reader."""

from __future__ import annotations

from datetime import datetime, timezone

from governance.audit_report import build_audit_report
from governance.cloudtrail import CloudTrailReader
from governance.findings import Finding, FindingStore, FindingStatus, Severity

UTC = timezone.utc


def _finding(rule_id="RULE-LOAN-001") -> Finding:
    return Finding(
        rule_id=rule_id,
        agent_id="loan-agent",
        task_id="t1",
        severity=Severity.CRITICAL,
        status=FindingStatus.OPEN,
        detected_at=datetime(2026, 1, 1, tzinfo=UTC),
        expected_behaviour="expected",
        observed_behaviour="observed",
        supporting_event_ids=["e1"],
        explanation="why",
        recommended_response="act",
    )


def test_audit_report_lists_findings(tmp_path) -> None:
    findings_path = tmp_path / "findings.jsonl"
    FindingStore(findings_path).append(_finding())
    report = build_audit_report("faulty", findings_path, alerts_path=None)
    assert "# Audit Report: faulty" in report
    assert "RULE-LOAN-001" in report
    assert "Findings total: 1" in report


def test_audit_report_handles_empty(tmp_path) -> None:
    findings_path = tmp_path / "findings.jsonl"
    findings_path.touch()
    report = build_audit_report("empty", findings_path)
    assert "No findings recorded" in report


class FakeCloudTrailClient:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def lookup_events(self, **kwargs):
        if self.fail:
            raise RuntimeError("access denied")
        return {
            "Events": [
                {
                    "EventId": "ct-1",
                    "EventName": "DescribeInstances",
                    "EventTime": datetime(2026, 1, 1, tzinfo=UTC),
                    "Username": "svc-agent",
                    "CloudTrailEvent": "{}",
                }
            ]
        }


def test_cloudtrail_normalizes_events() -> None:
    reader = CloudTrailReader(client=FakeCloudTrailClient())
    events, error = reader.lookup_management_events(
        datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
    )
    assert error is None
    assert events[0]["event_name"] == "DescribeInstances"
    assert events[0]["source"] == "cloudtrail"


def test_cloudtrail_never_raises() -> None:
    reader = CloudTrailReader(client=FakeCloudTrailClient(fail=True))
    events, error = reader.lookup_management_events(
        datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
    )
    assert events == []
    assert error and "access denied" in error


def test_cloudtrail_rejects_naive_timestamps() -> None:
    reader = CloudTrailReader(client=FakeCloudTrailClient())
    events, error = reader.lookup_management_events(
        datetime(2026, 1, 1), datetime(2026, 1, 2, tzinfo=UTC)
    )
    assert events == []
    assert error and "timezone-aware" in error
