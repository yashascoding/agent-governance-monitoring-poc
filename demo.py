"""Demo scenario runners shared by the CLI.

Each scenario returns structured results; nothing here touches real customer
data or real financial systems.
"""

from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from agents import (
    AccessDeniedError,
    ApprovalRequiredError,
    DataAccessAgent,
    LegacyDataAgent,
    LegacyLoanAgent,
    LoanAgent,
    TaskAgent,
)
from governance.clock import Clock, SimulatedClock
from governance.event_store import JsonlEventStore
from governance.findings import FindingStore
from governance.monitor import MonitoringEngine, MonitorResult
from governance.policy_loader import PolicyConfig
from notifications import LocalNotifier


@dataclass
class DemoContext:
    root: Path
    policy: PolicyConfig
    clock: SimulatedClock
    store: JsonlEventStore
    finding_store: FindingStore
    notifier: LocalNotifier
    engine: MonitoringEngine
    notes: list[str] = field(default_factory=list)


def build_context(root: Path, policy: PolicyConfig) -> DemoContext:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    clock = SimulatedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    store = JsonlEventStore(root / "events.jsonl", run_id="demo-run")
    finding_store = FindingStore(root / "findings.jsonl")
    notifier = LocalNotifier(root / "alerts.jsonl", echo=True)
    engine = MonitoringEngine(policy, finding_store, notifiers=[notifier], clock=clock)
    return DemoContext(root, policy, clock, store, finding_store, notifier, engine)


def run_normal_demo(ctx: DemoContext) -> MonitorResult:
    """Normal, policy-compliant behaviour across all three agents."""
    loan = LoanAgent("loan-agent", ctx.policy.loan_policy, ctx.store, ctx.clock, "demo-run")
    loan.request_loan("loan-small", 800)
    loan.auto_approve_if_eligible("loan-small")

    loan.request_loan("loan-large", 1500)
    loan.auto_approve_if_eligible("loan-large")
    loan.record_authorization_result("loan-large", granted=True)
    loan.finalize_approval("loan-large")

    task = TaskAgent("task-agent", ctx.policy.task_policy, ctx.store, ctx.clock, "demo-run")
    task.execute_task("task-normal", "report_generation", duration_seconds=300)

    data = DataAccessAgent("data-agent", ctx.policy.data_policy, ctx.store, ctx.clock, "demo-run")
    data.read_dataset("data-ok", "public_test_data")

    result = ctx.engine.process_store(ctx.store, now=ctx.clock.now())
    ctx.notes.append(
        f"normal demo: {len(result.new_findings)} finding(s), "
        f"{len(result.deliveries)} alert delivery record(s)"
    )
    return result


def run_faulty_demo(ctx: DemoContext) -> MonitorResult:
    """Deliberately faulty behaviour: enforcement is tested, monitor must catch."""
    loan = LoanAgent("loan-agent", ctx.policy.loan_policy, ctx.store, ctx.clock, "demo-run")
    loan.request_loan("loan-bypass", 1500)
    loan.auto_approve_if_eligible("loan-bypass")
    try:
        loan.attempt_unauthorized_approval("loan-bypass")
        ctx.notes.append("WARNING: unauthorized approval attempt was NOT blocked")
    except ApprovalRequiredError:
        ctx.notes.append("enforcement boundary blocked the unauthorized approval attempt")

    legacy = LegacyLoanAgent("loan-agent", ctx.policy.loan_policy, ctx.store, ctx.clock, "demo-run")
    legacy.request_loan("loan-legacy-bug", 1500)
    legacy.legacy_record_approval_bypassing_policy("loan-legacy-bug")

    task = TaskAgent("task-agent", ctx.policy.task_policy, ctx.store, ctx.clock, "demo-run")
    task.execute_task("task-suspicious", "report_generation", duration_seconds=10)

    data = LegacyDataAgent("data-agent", ctx.policy.data_policy, ctx.store, ctx.clock, "demo-run")
    try:
        data.read_dataset("data-denied", "loan_applications")
    except AccessDeniedError:
        ctx.notes.append("data-access boundary denied the restricted read")

    legacy_data = LegacyDataAgent("data-agent", ctx.policy.data_policy, ctx.store, ctx.clock, "demo-run")
    legacy_data.legacy_read_without_enforcement("data-legacy-bug", "loan_applications")

    result = ctx.engine.process_store(ctx.store, now=ctx.clock.now())
    ctx.notes.append(
        f"faulty demo: {len(result.new_findings)} finding(s), "
        f"{len(result.deliveries)} alert delivery record(s)"
    )
    return result


def run_deadline_demo(ctx: DemoContext) -> MonitorResult:
    """A stalled workflow: held as pending, escalated only after the deadline.

    This is the scenario the tests cover but the other demos do not show. The
    monitor must not accuse an agent whose authorization event may simply be
    in flight; only once the configured deadline has expired does the missing
    authorization become a violation.
    """
    loan = LoanAgent("loan-agent", ctx.policy.loan_policy, ctx.store, ctx.clock, "demo-run")
    loan.request_loan("loan-stalled", 1500)
    loan.auto_approve_if_eligible("loan-stalled")  # asks for sign-off; never granted

    within = ctx.engine.process_store(ctx.store, now=ctx.clock.now())
    pending = [f for f in within.new_findings if f.status.value == "PENDING_INVESTIGATION"]
    ctx.notes.append(
        f"within the deadline: {len(pending)} PENDING_INVESTIGATION, "
        "0 violations (the authorization event may still arrive)"
    )

    deadline = ctx.policy.monitoring_policy.workflow_deadline_seconds
    ctx.clock.advance(deadline + 60)
    expired = ctx.engine.process_store(ctx.store, now=ctx.clock.now())
    escalated = [
        f for f in expired.new_findings if f.severity.value == "CRITICAL"
    ]
    ctx.notes.append(
        f"after the {deadline:.0f}s deadline: {len(escalated)} CRITICAL violation(s) "
        "raised for the same workflow"
    )
    return _merge_results(within, expired)


def _merge_results(*results: MonitorResult) -> MonitorResult:
    """Combine several monitoring passes into one summary."""
    merged = MonitorResult()
    for result in results:
        merged.processed_events += result.processed_events
        merged.new_findings.extend(result.new_findings)
        merged.suppressed_duplicates.extend(result.suppressed_duplicates)
        merged.deliveries.extend(result.deliveries)
    if results:
        merged.read_report = results[-1].read_report
    return merged


def live_workload_steps(
    policy: PolicyConfig, store: JsonlEventStore, clock: Clock
) -> list[tuple[str, Callable[[], None]]]:
    """Build the paced agent workload used by the live monitor demo.

    The steps are ordered from fully compliant behaviour to outright
    violations so the recording escalates rather than jumping around.
    """
    loan = LoanAgent("loan-agent", policy.loan_policy, store, clock, "watch-run")
    task = TaskAgent("task-agent", policy.task_policy, store, clock, "watch-run")
    data = DataAccessAgent("data-agent", policy.data_policy, store, clock, "watch-run")
    legacy_loan = LegacyLoanAgent(
        "loan-agent", policy.loan_policy, store, clock, "watch-run"
    )
    legacy_data = LegacyDataAgent(
        "data-agent", policy.data_policy, store, clock, "watch-run"
    )

    def compliant_small_loan() -> None:
        loan.request_loan("loan-small", 800)
        loan.auto_approve_if_eligible("loan-small")

    def compliant_authorized_loan() -> None:
        loan.request_loan("loan-large", 1500)
        loan.auto_approve_if_eligible("loan-large")
        loan.record_authorization_result("loan-large", granted=True)
        loan.finalize_approval("loan-large")

    def compliant_task() -> None:
        task.execute_task("task-normal", "report_generation", duration_seconds=300)

    def short_task() -> None:
        task.execute_task("task-suspicious", "report_generation", duration_seconds=10)

    def blocked_data_read() -> None:
        try:
            data.read_dataset("data-denied", "loan_applications")
        except AccessDeniedError:
            pass

    def legacy_unauthorized_approval() -> None:
        legacy_loan.request_loan("loan-legacy-bug", 1500)
        legacy_loan.legacy_record_approval_bypassing_policy("loan-legacy-bug")

    def legacy_unauthorized_read() -> None:
        legacy_data.legacy_read_without_enforcement(
            "data-legacy-bug", "loan_applications"
        )

    return [
        ("compliant  auto-approve INR 800 (below threshold)", compliant_small_loan),
        ("compliant  INR 1,500 approved after recorded human sign-off", compliant_authorized_loan),
        ("compliant  300s task within baseline", compliant_task),
        ("anomaly    10s task vs 300s baseline", short_task),
        ("blocked    restricted dataset read denied at the boundary", blocked_data_read),
        ("violation  approval recorded with no human authorization", legacy_unauthorized_approval),
        ("violation  successful read of a restricted dataset", legacy_unauthorized_read),
    ]


def run_live_workload(
    policy: PolicyConfig,
    store: JsonlEventStore,
    clock: Clock,
    pace: float = 1.5,
    on_step: Callable[[str], None] | None = None,
    stop: threading.Event | None = None,
) -> None:
    """Run the paced workload in the current thread, one step per ``pace`` seconds."""
    for label, action in live_workload_steps(policy, store, clock):
        if stop is not None and stop.is_set():
            return
        action()
        if on_step is not None:
            on_step(label)
        if stop is not None:
            stop.wait(pace)
        else:
            time.sleep(pace)
