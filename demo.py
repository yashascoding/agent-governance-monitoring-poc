"""Demo scenario runners shared by the CLI.

Each scenario returns structured results; nothing here touches real customer
data or real financial systems.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agents import (
    AccessDeniedError,
    ApprovalRequiredError,
    DataAccessAgent,
    LegacyDataAgent,
    LegacyLoanAgent,
    LoanAgent,
    TaskAgent,
)
from governance.clock import SimulatedClock
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
