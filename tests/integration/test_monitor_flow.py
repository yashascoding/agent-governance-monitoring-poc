"""Integration tests for the event -> monitor -> finding -> alert flow."""

from __future__ import annotations

from datetime import datetime, timezone

from agents import (
    ApprovalRequiredError,
    DataAccessAgent,
    LegacyDataAgent,
    LegacyLoanAgent,
    LoanAgent,
    TaskAgent,
)
from governance.event_store import JsonlEventStore
from governance.findings import FindingStore
from governance.monitor import MonitoringEngine
from notifications import LocalNotifier

UTC = timezone.utc


def test_full_flow_faulty_run_produces_findings_and_alerts(tmp_path, policy, clock) -> None:
    store = JsonlEventStore(tmp_path / "events.jsonl", run_id="r")
    finding_store = FindingStore(tmp_path / "findings.jsonl")
    alerts = tmp_path / "alerts.jsonl"
    engine = MonitoringEngine(policy, finding_store, notifiers=[LocalNotifier(alerts, echo=False)], clock=clock)

    loan = LoanAgent("loan-agent", policy.loan_policy, store, clock, "r")
    loan.request_loan("t3", 1500)
    try:
        loan.attempt_unauthorized_approval("t3")
    except ApprovalRequiredError:
        pass

    task = TaskAgent("task-agent", policy.task_policy, store, clock, "r")
    task.execute_task("t6", "batch_job", duration_seconds=10)

    data = DataAccessAgent("data-agent", policy.data_policy, store, clock, "r")
    try:
        data.read_dataset("t7", "loan_applications")
    except Exception:
        pass

    result = engine.process_store(store)
    rule_ids = {f.rule_id for f in result.new_findings}
    assert {"RULE-LOAN-001", "RULE-TASK-001", "RULE-DATA-001"} <= rule_ids
    assert len(result.deliveries) == len(result.new_findings)
    assert all(d.status == "SUCCESS" for d in result.deliveries)
    assert alerts.exists()
    assert len(alerts.read_text(encoding="utf-8").strip().splitlines()) == len(result.new_findings)


def test_reprocessing_is_idempotent(tmp_path, policy, clock) -> None:
    store = JsonlEventStore(tmp_path / "events.jsonl", run_id="r")
    finding_store = FindingStore(tmp_path / "findings.jsonl")
    engine = MonitoringEngine(policy, finding_store, notifiers=[LocalNotifier(tmp_path / "a.jsonl", echo=False)], clock=clock)

    loan = LoanAgent("loan-agent", policy.loan_policy, store, clock, "r")
    loan.request_loan("t3", 1500)
    try:
        loan.attempt_unauthorized_approval("t3")
    except ApprovalRequiredError:
        pass

    first = engine.process_store(store)
    second = engine.process_store(store)
    assert first.new_findings
    assert second.new_findings == []
    assert len(second.suppressed_duplicates) == len(first.new_findings)
    assert second.deliveries == []


def test_duplicate_events_in_file_do_not_duplicate_findings(tmp_path, policy, clock) -> None:
    store = JsonlEventStore(tmp_path / "events.jsonl", run_id="r")
    finding_store = FindingStore(tmp_path / "findings.jsonl")
    engine = MonitoringEngine(policy, finding_store, notifiers=[], clock=clock)

    legacy = LegacyLoanAgent("loan-agent", policy.loan_policy, store, clock, "r")
    legacy.request_loan("t4", 1500)
    legacy.legacy_record_approval_bypassing_policy("t4")

    # Re-append the exact same event records (same event IDs).
    result = store.read_all()
    store.append_many(result.events)

    monitored = engine.process_store(store)
    loan_findings = [f for f in monitored.new_findings if f.rule_id.startswith("RULE-LOAN")]
    assert len(loan_findings) == 2  # 001 + 002, not quadrupled
    assert monitored.read_report.duplicate_events == len(result.events)


def test_legacy_data_read_detected_as_high(tmp_path, policy, clock) -> None:
    store = JsonlEventStore(tmp_path / "events.jsonl", run_id="r")
    finding_store = FindingStore(tmp_path / "findings.jsonl")
    engine = MonitoringEngine(policy, finding_store, notifiers=[], clock=clock)

    agent = LegacyDataAgent("data-agent", policy.data_policy, store, clock, "r")
    agent.legacy_read_without_enforcement("t8", "loan_applications", row_count=42)

    result = engine.process_store(store)
    high = [f for f in result.new_findings if f.rule_id == "RULE-DATA-002"]
    assert len(high) == 1
    assert high[0].severity.value == "HIGH"


def test_detector_crash_does_not_break_monitoring(tmp_path, policy, clock) -> None:
    class ExplodingDetector:
        rule_id = "RULE-EXPLODE"

        def detect(self, events, config, now):
            raise RuntimeError("boom")

    store = JsonlEventStore(tmp_path / "events.jsonl", run_id="r")
    finding_store = FindingStore(tmp_path / "findings.jsonl")
    engine = MonitoringEngine(
        policy, finding_store, notifiers=[], detectors=[ExplodingDetector()], clock=clock
    )
    loan = LoanAgent("loan-agent", policy.loan_policy, store, clock, "r")
    loan.request_loan("t", 1500)
    try:
        loan.attempt_unauthorized_approval("t")
    except ApprovalRequiredError:
        pass
    result = engine.process_store(store)
    assert isinstance(result.new_findings, list)  # no exception escaped
