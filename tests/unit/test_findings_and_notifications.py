"""Unit tests for findings model and notification backends."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from governance.findings import Finding, FindingStore, FindingStatus, Severity
from notifications import LocalNotifier, SNSNotifier

UTC = timezone.utc


def make_finding(**overrides) -> Finding:
    defaults = dict(
        rule_id="RULE-TEST-001",
        agent_id="loan-agent",
        task_id="t1",
        severity=Severity.CRITICAL,
        status=FindingStatus.OPEN,
        detected_at=datetime(2026, 1, 1, tzinfo=UTC),
        expected_behaviour="expected",
        observed_behaviour="observed",
        supporting_event_ids=["e1"],
        explanation="because",
        recommended_response="act",
        key_evidence={"amount": 1500},
    )
    defaults.update(overrides)
    return Finding(**defaults)


class TestFindings:
    def test_finding_key_is_deterministic(self) -> None:
        assert make_finding().finding_key == make_finding().finding_key

    def test_finding_key_changes_with_evidence(self) -> None:
        assert make_finding().finding_key != make_finding(key_evidence={"amount": 9999}).finding_key

    def test_store_roundtrip(self, tmp_path) -> None:
        store = FindingStore(tmp_path / "findings.jsonl")
        finding = make_finding()
        store.append(finding)
        loaded = store.load_all()
        assert loaded[0].finding_id == finding.finding_id
        assert store.known_keys() == {finding.finding_key}

    def test_requires_supporting_events(self) -> None:
        with pytest.raises(ValueError, match="supporting event"):
            make_finding(supporting_event_ids=[])


class FakeSNSClient:
    def __init__(self, fail_times: int = 0, error: Exception | None = None) -> None:
        self.fail_times = fail_times
        self.calls = 0
        self.error = error or RuntimeError("SNS unavailable")

    def publish(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.error
        return {"MessageId": "msg-123"}


class TestLocalNotifier:
    def test_writes_alert_jsonl(self, tmp_path) -> None:
        alerts_path = tmp_path / "alerts.jsonl"
        notifier = LocalNotifier(alerts_path, echo=False)
        result = notifier.send(make_finding())
        assert result.status == "SUCCESS"
        record = json.loads(alerts_path.read_text(encoding="utf-8").strip())
        assert record["finding"]["rule_id"] == "RULE-TEST-001"
        assert record["delivery"]["backend"] == "local"

    def test_write_failure_reported_not_raised(self, tmp_path) -> None:
        directory = tmp_path / "blocker"
        directory.write_text("x", encoding="utf-8")  # file where dir expected
        notifier = LocalNotifier(directory / "alerts.jsonl", echo=False)
        result = notifier.send(make_finding())
        assert result.status == "FAILED"


class TestSNSNotifier:
    def test_publish_success_never_claims_delivery(self, tmp_path) -> None:
        client = FakeSNSClient()
        notifier = SNSNotifier(topic_arn="arn:aws:sns:us-east-1:123:topic", client=client,
                               sleep_fn=lambda _s: None)
        result = notifier.send(make_finding())
        assert result.status == "SUCCESS"
        assert "not confirmed" in result.detail
        assert client.calls == 1

    def test_retries_then_succeeds(self) -> None:
        client = FakeSNSClient(fail_times=2)
        notifier = SNSNotifier(topic_arn="arn:aws:sns:us-east-1:123:topic", client=client,
                               max_attempts=3, backoff_seconds=0, sleep_fn=lambda _s: None)
        result = notifier.send(make_finding())
        assert result.status == "SUCCESS"
        assert result.attempts == 3

    def test_persistent_failure_is_failed_result(self) -> None:
        client = FakeSNSClient(fail_times=99)
        notifier = SNSNotifier(topic_arn="arn:aws:sns:us-east-1:123:topic", client=client,
                               max_attempts=3, backoff_seconds=0, sleep_fn=lambda _s: None)
        result = notifier.send(make_finding())
        assert result.status == "FAILED"
        assert result.attempts == 3
        assert "after 3 attempts" in result.detail

    def test_empty_topic_arn_rejected(self) -> None:
        with pytest.raises(ValueError, match="topic ARN"):
            SNSNotifier(topic_arn="")
