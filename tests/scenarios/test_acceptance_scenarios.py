"""Mandatory acceptance scenarios T1-T12.

Each test drives real agents through a synthetic workflow, runs the
independent monitor, and records the actual result into the generated test
report. Violations are injected deliberately; normal control cases assert
that no OPEN finding is produced.
"""

from __future__ import annotations

from datetime import timedelta

from agents import (
    AccessDeniedError,
    ApprovalRequiredError,
    DataAccessAgent,
    LegacyDataAgent,
    LegacyLoanAgent,
    LoanAgent,
    TaskAgent,
)
from governance.event_store import JsonlEventStore
from governance.findings import FindingStatus
from governance.monitor import MonitoringEngine
from notifications import LocalNotifier


def _open(result):
    return [f for f in result.new_findings if f.status == FindingStatus.OPEN]


def T1_auto_approved_small_loan(engine, policy, clock, store) -> None:
    loan = LoanAgent("loan-agent", policy.loan_policy, store, clock, "r")
    loan.request_loan("t1", 800)
    loan.auto_approve_if_eligible("t1")


def T2_authorized_large_loan(engine, policy, clock, store) -> None:
    loan = LoanAgent("loan-agent", policy.loan_policy, store, clock, "r")
    loan.request_loan("t2", 1500)
    loan.auto_approve_if_eligible("t2")
    loan.record_authorization_result("t2", granted=True)
    loan.finalize_approval("t2")


def T3_bypass_attempt_blocked_and_flagged(engine, policy, clock, store) -> None:
    loan = LoanAgent("loan-agent", policy.loan_policy, store, clock, "r")
    loan.request_loan("t3", 1500)
    loan.auto_approve_if_eligible("t3")
    try:
        loan.attempt_unauthorized_approval("t3")
    except ApprovalRequiredError:
        pass  # enforcement boundary blocks it; monitor must still flag the attempt


def T4_legacy_unauthorized_approval(engine, policy, clock, store) -> None:
    legacy = LegacyLoanAgent("loan-agent", policy.loan_policy, store, clock, "r")
    legacy.request_loan("t4", 1500)
    legacy.legacy_record_approval_bypassing_policy("t4")


def T5_normal_duration(engine, policy, clock, store) -> None:
    task = TaskAgent("task-agent", policy.task_policy, store, clock, "r")
    task.execute_task("t5", "report", duration_seconds=300)


def T6_short_duration(engine, policy, clock, store) -> None:
    task = TaskAgent("task-agent", policy.task_policy, store, clock, "r")
    task.execute_task("t6", "report", duration_seconds=10)


def T7_restricted_access_request(engine, policy, clock, store) -> None:
    data = DataAccessAgent("data-agent", policy.data_policy, store, clock, "r")
    try:
        data.read_dataset("t7", "loan_applications")
    except AccessDeniedError:
        pass


def T8_legacy_successful_restricted_read(engine, policy, clock, store) -> None:
    data = LegacyDataAgent("data-agent", policy.data_policy, store, clock, "r")
    data.legacy_read_without_enforcement("t8", "loan_applications")


class TestAcceptanceScenarios:
    def test_T1_auto_approved_small_loan(
        self, make_engine, policy, clock, event_store, timed_process, record_scenario
    ) -> None:
        engine, _, _ = make_engine("t1")
        store = event_store()
        T1_auto_approved_small_loan(engine, policy, clock, store)
        result, latency = timed_process(engine, store, clock.now())
        record_scenario("T1", False, result, latency)
        assert _open(result) == []

    def test_T2_authorized_large_loan(
        self, make_engine, policy, clock, event_store, timed_process, record_scenario
    ) -> None:
        engine, _, _ = make_engine("t2")
        store = event_store()
        T2_authorized_large_loan(engine, policy, clock, store)
        result, latency = timed_process(engine, store, clock.now())
        record_scenario("T2", False, result, latency)
        assert _open(result) == []

    def test_T3_bypass_attempt_detected(
        self, make_engine, policy, clock, event_store, timed_process, record_scenario
    ) -> None:
        engine, _, _ = make_engine("t3")
        store = event_store()
        T3_bypass_attempt_blocked_and_flagged(engine, policy, clock, store)
        result, latency = timed_process(engine, store, clock.now())
        record_scenario("T3", True, result, latency,
                        expect_open_findings=1)
        findings = _open(result)
        assert any(f.rule_id == "RULE-LOAN-001" and f.severity.value == "CRITICAL" for f in findings)

    def test_T4_legacy_unauthorized_approval(
        self, make_engine, policy, clock, event_store, timed_process, record_scenario
    ) -> None:
        engine, _, _ = make_engine("t4")
        store = event_store()
        T4_legacy_unauthorized_approval(engine, policy, clock, store)
        result, latency = timed_process(engine, store, clock.now())
        record_scenario("T4", True, result, latency,
                        expect_open_findings=1)
        findings = _open(result)
        assert any(f.rule_id == "RULE-LOAN-002" and f.severity.value == "CRITICAL" for f in findings)

    def test_T5_normal_duration(
        self, make_engine, policy, clock, event_store, timed_process, record_scenario
    ) -> None:
        engine, _, _ = make_engine("t5")
        store = event_store()
        T5_normal_duration(engine, policy, clock, store)
        result, latency = timed_process(engine, store, clock.now())
        record_scenario("T5", False, result, latency)
        assert not any(f.rule_id == "RULE-TASK-001" for f in _open(result))

    def test_T6_short_duration_detected(
        self, make_engine, policy, clock, event_store, timed_process, record_scenario
    ) -> None:
        engine, _, _ = make_engine("t6")
        store = event_store()
        T6_short_duration(engine, policy, clock, store)
        result, latency = timed_process(engine, store, clock.now())
        record_scenario("T6", True, result, latency,
                        expect_open_findings=1)
        findings = _open(result)
        assert any(f.rule_id == "RULE-TASK-001" and f.severity.value == "MEDIUM" for f in findings)

    def test_T7_restricted_access_request(
        self, make_engine, policy, clock, event_store, timed_process, record_scenario
    ) -> None:
        engine, _, _ = make_engine("t7")
        store = event_store()
        T7_restricted_access_request(engine, policy, clock, store)
        result, latency = timed_process(engine, store, clock.now())
        record_scenario("T7", True, result, latency,
                        expect_open_findings=1)
        findings = _open(result)
        assert any(f.rule_id == "RULE-DATA-001" for f in findings)

    def test_T8_legacy_successful_restricted_read(
        self, make_engine, policy, clock, event_store, timed_process, record_scenario
    ) -> None:
        engine, _, _ = make_engine("t8")
        store = event_store()
        T8_legacy_successful_restricted_read(engine, policy, clock, store)
        result, latency = timed_process(engine, store, clock.now())
        record_scenario("T8", True, result, latency,
                        expect_open_findings=1)
        findings = _open(result)
        assert any(f.rule_id == "RULE-DATA-002" and f.severity.value == "HIGH" for f in findings)

    def test_T9_duplicate_events_no_duplicate_findings(
        self, make_engine, policy, clock, event_store, timed_process, record_scenario
    ) -> None:
        engine, _, _ = make_engine("t9")
        store = event_store()
        T4_legacy_unauthorized_approval(engine, policy, clock, store)
        first = store.read_all()
        store.append_many(first.events)  # exact duplicate records

        result, latency = timed_process(engine, store, clock.now())
        record_scenario("T9", True, result, latency, expect_open_findings=2)
        loan_findings = [f for f in result.new_findings if f.rule_id.startswith("RULE-LOAN")]
        assert len(loan_findings) == 2  # RULE-LOAN-001 + RULE-LOAN-002
        assert result.read_report.duplicate_events == len(first.events)

        second_result = engine.process_store(store)
        assert second_result.new_findings == []
        assert second_result.deliveries == []

    def test_T10_incomplete_workflow_pending_not_accused(
        self, make_engine, policy, clock, event_store, timed_process, record_scenario
    ) -> None:
        engine, _, _ = make_engine("t10")
        store = event_store()
        loan = LoanAgent("loan-agent", policy.loan_policy, store, clock, "r")
        loan.request_loan("t10", 1500)
        loan.request_human_approval("t10")
        # authorization result never arrives; workflow still within deadline
        result, latency = timed_process(engine, store, clock.now())
        record_scenario("T10", False, result, latency)
        assert _open(result) == []
        pending = [f for f in result.new_findings if f.status == FindingStatus.PENDING_INVESTIGATION]
        assert len(pending) == 1
        assert pending[0].rule_id == "RULE-LOAN-001"

    def test_T10b_expired_workflow_escalates(
        self, make_engine, policy, clock, event_store, timed_process, record_scenario
    ) -> None:
        engine, _, _ = make_engine("t10b")
        store = event_store()
        loan = LoanAgent("loan-agent", policy.loan_policy, store, clock, "r")
        loan.request_loan("t10b", 1500)
        loan.request_human_approval("t10b")
        later = clock.now() + timedelta(seconds=policy.monitoring_policy.workflow_deadline_seconds + 60)
        result, latency = timed_process(engine, store, later)
        record_scenario("T10b", True, result, latency,
                        expect_open_findings=1)
        findings = _open(result)
        assert any(f.rule_id == "RULE-LOAN-001" and f.severity.value == "CRITICAL" for f in findings)

    def test_T12_all_valid_no_false_positives(
        self, make_engine, policy, clock, event_store, timed_process, record_scenario
    ) -> None:
        engine, _, _ = make_engine("t12")
        store = event_store()
        T1_auto_approved_small_loan(engine, policy, clock, store)
        T2_authorized_large_loan(engine, policy, clock, store)
        T5_normal_duration(engine, policy, clock, store)
        data = DataAccessAgent("data-agent", policy.data_policy, store, clock, "r")
        data.read_dataset("t12-data", "public_test_data")
        result, latency = timed_process(engine, store, clock.now())
        record_scenario("T12", False, result, latency)
        assert _open(result) == []
