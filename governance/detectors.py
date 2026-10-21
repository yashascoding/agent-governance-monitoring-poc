"""Deterministic policy detectors for the monitoring engine.

Every detector re-evaluates raw recorded events against the centralized
policy. Nothing here trusts a task agent's self-reported conclusion: amounts,
durations, permissions, and event order are recomputed from the event stream
and corroborating metadata (e.g. start/end timestamps vs reported duration).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from governance.event_schema import Event, EventType, parse_utc_iso
from governance.findings import Finding, FindingStatus, Severity
from governance.policy_loader import PolicyConfig

LOAN_TERMINAL_TYPES = {
    EventType.LOAN_APPROVED,
    EventType.LOAN_REJECTED,
    EventType.LOAN_APPROVAL_BLOCKED,
}
LOAN_FINAL_TYPES = {EventType.LOAN_APPROVED, EventType.LOAN_REJECTED}


class Detector(ABC):
    """A single rule implementation that turns events into findings."""

    rule_id: str

    @abstractmethod
    def detect(
        self,
        events: Sequence[Event],
        policy: PolicyConfig,
        now: datetime,
    ) -> list[Finding]:
        raise NotImplementedError


@dataclass
class LoanWorkflow:
    """All loan-related events sharing a correlation ID, in stream order."""

    correlation_id: str
    events: list[Event] = field(default_factory=list)

    @property
    def agent_id(self) -> str:
        return self.events[0].agent_id

    @property
    def task_id(self) -> str:
        return self.events[0].task_id

    def of_type(self, *event_types: EventType) -> list[Event]:
        wanted = set(event_types)
        return [event for event in self.events if event.event_type in wanted]

    @property
    def first_request(self) -> Event | None:
        requested = self.of_type(EventType.LOAN_REQUESTED)
        return requested[0] if requested else None

    @property
    def amount(self) -> float | None:
        for event in reversed(self.events):
            amount = event.evidence.get("amount")
            if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                return float(amount)
        return None

    @property
    def currency(self) -> str:
        for event in reversed(self.events):
            currency = event.evidence.get("currency")
            if isinstance(currency, str):
                return currency
        return "INR"

    @property
    def has_authorization_granted(self) -> bool:
        return bool(self.of_type(EventType.HUMAN_APPROVAL_GRANTED))

    @property
    def has_authorization_denied(self) -> bool:
        return bool(self.of_type(EventType.HUMAN_APPROVAL_DENIED))

    @property
    def approval_attempts(self) -> list[Event]:
        return self.of_type(EventType.LOAN_APPROVAL_BLOCKED, EventType.LOAN_APPROVED)

    @property
    def final_approvals(self) -> list[Event]:
        return self.of_type(EventType.LOAN_APPROVED)

    @property
    def final_rejections(self) -> list[Event]:
        return self.of_type(EventType.LOAN_REJECTED)

    @property
    def has_final_outcome(self) -> bool:
        return bool(self.of_type(*LOAN_FINAL_TYPES))

    @property
    def last_timestamp(self) -> datetime:
        return max(event.timestamp for event in self.events)

    @property
    def event_ids(self) -> list[str]:
        return [event.event_id for event in self.events]


def group_loan_workflows(events: Sequence[Event]) -> list[LoanWorkflow]:
    """Group loan-related events by correlation ID, preserving stream order."""
    workflows: dict[str, LoanWorkflow] = {}
    loan_types = {
        EventType.LOAN_REQUESTED,
        EventType.HUMAN_APPROVAL_REQUESTED,
        EventType.HUMAN_APPROVAL_GRANTED,
        EventType.HUMAN_APPROVAL_DENIED,
        *LOAN_TERMINAL_TYPES,
    }
    for event in events:
        if event.event_type not in loan_types:
            continue
        key = event.correlation_id or event.task_id
        workflows.setdefault(key, LoanWorkflow(correlation_id=key)).events.append(event)
    return list(workflows.values())


class MissingHumanAuthorizationDetector(Detector):
    """RULE-LOAN-001: loan approval without required human authorization.

    * Approval attempted (blocked or finalized) at/above the threshold with no
      recorded authorization -> CRITICAL.
    * Incomplete workflow still within the configured deadline -> PENDING
      investigation, never an immediate accusation.
    * Incomplete workflow past the deadline -> CRITICAL (deadline expired).
    """

    rule_id = "RULE-LOAN-001"

    def detect(
        self, events: Sequence[Event], policy: PolicyConfig, now: datetime
    ) -> list[Finding]:
        findings: list[Finding] = []
        loan = policy.loan_policy
        monitoring = policy.monitoring_policy
        for workflow in group_loan_workflows(events):
            amount = workflow.amount
            if amount is None or not loan.requires_human_approval(amount):
                continue
            if workflow.has_authorization_granted:
                continue
            attempts = workflow.approval_attempts
            if attempts:
                findings.append(
                    self._attempt_without_authorization(workflow, amount, loan.currency, attempts)
                )
                continue
            if workflow.has_final_outcome:
                continue  # rejections are legitimate without authorization
            findings.append(
                self._incomplete_workflow(workflow, amount, loan.currency, monitoring, now)
            )
        return findings

    def _attempt_without_authorization(
        self,
        workflow: LoanWorkflow,
        amount: float,
        currency: str,
        attempts: list[Event],
    ) -> Finding:
        finalized = [event for event in attempts if event.event_type == EventType.LOAN_APPROVED]
        bypass_flags = [
            bool(event.evidence.get("bypass_attempted"))
            for event in attempts
            if event.event_type == EventType.LOAN_APPROVAL_BLOCKED
        ]
        if finalized:
            observed = (
                f"final approval recorded for {amount} {currency} with no "
                "human_approval.granted event in the workflow"
            )
        else:
            observed = (
                f"approval finalization was attempted for {amount} {currency} "
                f"without human authorization (bypass_attempted={any(bypass_flags)})"
            )
        return Finding(
            rule_id=self.rule_id,
            agent_id=workflow.agent_id,
            task_id=workflow.task_id,
            severity=Severity.CRITICAL,
            status=FindingStatus.OPEN,
            detected_at=workflow.last_timestamp,
            expected_behaviour=(
                f"loans >= {amount:.0f} {currency} require a recorded human "
                "authorization before approval is finalized"
            ),
            observed_behaviour=observed,
            supporting_event_ids=workflow.event_ids,
            explanation=(
                "The monitoring engine found no human_approval.granted event "
                "corroborating the approval activity for a loan that exceeds the "
                "auto-approval threshold."
            ),
            recommended_response=(
                "Halt the approval, require independent human review, audit the "
                "agent's authorization checks, and inspect for tampering."
            ),
            key_evidence={
                "amount": amount,
                "currency": currency,
                "finalized": bool(finalized),
                "bypass_attempted": any(bypass_flags),
            },
        )

    def _incomplete_workflow(
        self,
        workflow: LoanWorkflow,
        amount: float,
        currency: str,
        monitoring: Any,
        now: datetime,
    ) -> Finding:
        age_seconds = max(0.0, (now - workflow.last_timestamp).total_seconds())
        expired = age_seconds > monitoring.workflow_deadline_seconds
        if expired and monitoring.escalate_expired_incomplete_workflows:
            return Finding(
                rule_id=self.rule_id,
                agent_id=workflow.agent_id,
                task_id=workflow.task_id,
                severity=Severity.CRITICAL,
                status=FindingStatus.OPEN,
                detected_at=now,
                expected_behaviour=(
                    "an authorization decision and final outcome must be recorded "
                    f"within {monitoring.workflow_deadline_seconds:.0f} seconds"
                ),
                observed_behaviour=(
                    f"workflow incomplete for {age_seconds:.0f}s with no "
                    f"authorization and no final outcome for a {amount} {currency} loan"
                ),
                supporting_event_ids=workflow.event_ids,
                explanation=(
                    "The approval workflow stalled past the configured deadline "
                    "without the required human authorization."
                ),
                recommended_response=(
                    "Escalate to the compliance queue and require manual disposition "
                    "of the stalled loan workflow."
                ),
                key_evidence={
                    "amount": amount,
                    "currency": currency,
                    "expired": True,
                    "age_seconds": round(age_seconds, 3),
                },
            )
        return Finding(
            rule_id=self.rule_id,
            agent_id=workflow.agent_id,
            task_id=workflow.task_id,
            severity=Severity.LOW,
            status=FindingStatus.PENDING_INVESTIGATION,
            detected_at=now,
            expected_behaviour=(
                "human authorization and a final outcome are still required before "
                "the deadline expires"
            ),
            observed_behaviour=(
                f"authorization is missing, but the workflow is only {age_seconds:.0f}s "
                "old (deadline "
                f"{monitoring.workflow_deadline_seconds:.0f}s) and has no final outcome"
            ),
            supporting_event_ids=workflow.event_ids,
            explanation=(
                "This is not classified as a violation: the workflow is incomplete "
                "and still within the configured deadline, so the authorization event "
                "may simply not have arrived yet."
            ),
            recommended_response=(
                "Monitor for the delayed authorization or final-outcome event; "
                "escalate automatically if the deadline expires."
            ),
            key_evidence={
                "amount": amount,
                "currency": currency,
                "expired": False,
                "age_seconds": round(age_seconds, 3),
            },
        )


class UnauthorizedApprovalDetector(Detector):
    """RULE-LOAN-002: final approval inconsistent with authorization state.

    Also catches approvals corroborated by an explicit denial event.
    """

    rule_id = "RULE-LOAN-002"

    def detect(
        self, events: Sequence[Event], policy: PolicyConfig, now: datetime
    ) -> list[Finding]:
        findings: list[Finding] = []
        loan = policy.loan_policy
        for workflow in group_loan_workflows(events):
            approvals = workflow.final_approvals
            if not approvals:
                continue
            amount = workflow.amount
            if amount is None or not loan.requires_human_approval(amount):
                continue
            if workflow.has_authorization_granted:
                continue
            denial_ids = [event.event_id for event in workflow.of_type(EventType.HUMAN_APPROVAL_DENIED)]
            corroborating = workflow.of_type(EventType.HUMAN_APPROVAL_REQUESTED) + approvals
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    agent_id=workflow.agent_id,
                    task_id=workflow.task_id,
                    severity=Severity.CRITICAL,
                    status=FindingStatus.OPEN,
                    detected_at=max(event.timestamp for event in approvals),
                    expected_behaviour=(
                        "no final loan.approved event may exist without a prior "
                        "human_approval.granted event for amounts at or above the threshold"
                    ),
                    observed_behaviour=(
                        f"loan.approved recorded for {amount} {loan.currency} while "
                        "authorization state is "
                        + ("explicitly denied" if denial_ids else "missing")
                    ),
                    supporting_event_ids=[
                        event.event_id
                        for event in corroborating
                    ],
                    explanation=(
                        "The independent monitor recomputed the authorization state "
                        "from the event stream and found the final approval unsupported."
                        + (
                            " The workflow also contains an explicit denial, making the "
                            "approval directly contradictory."
                            if denial_ids
                            else ""
                        )
                    ),
                    recommended_response=(
                        "Reverse or quarantine the approval, open an incident, and "
                        "forensically review the agent's decision path."
                    ),
                    key_evidence={
                        "amount": amount,
                        "currency": loan.currency,
                        "authorization_denied_recorded": bool(denial_ids),
                    },
                )
            )
        return findings


class TaskDurationDetector(Detector):
    """RULE-TASK-001: implausibly short task execution.

    Duration is corroborated by recomputing it from start/end timestamps;
    the monitor does not rely on the agent's self-reported duration alone.
    A short duration is an investigation signal, not proof of malice.
    """

    rule_id = "RULE-TASK-001"

    def detect(
        self, events: Sequence[Event], policy: PolicyConfig, now: datetime
    ) -> list[Finding]:
        findings: list[Finding] = []
        task_policy = policy.task_policy
        for event in events:
            if event.event_type != EventType.TASK_COMPLETED:
                continue
            reported = _as_float(event.evidence.get("duration_seconds"))
            observed = _as_float(event.evidence.get("observed_duration_seconds"))
            if reported is None and observed is None:
                observed = self._duration_from_timestamps(event)
            durations = [value for value in (reported, observed) if value is not None]
            shortest = min(durations) if durations else None
            if shortest is None or not task_policy.is_short_duration_anomaly(shortest):
                continue
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    agent_id=event.agent_id,
                    task_id=event.task_id,
                    severity=Severity.MEDIUM,
                    status=FindingStatus.OPEN,
                    detected_at=event.timestamp,
                    expected_behaviour=(
                        f"tasks of this type take about "
                        f"{task_policy.baseline_duration_seconds:.0f}s; durations below "
                        f"{task_policy.anomaly_min_duration_seconds:.0f}s are implausible"
                    ),
                    observed_behaviour=(
                        f"task completed in {shortest:.0f}s "
                        f"(reported={reported}, observed={observed}) against a "
                        f"{task_policy.baseline_duration_seconds:.0f}s baseline"
                    ),
                    supporting_event_ids=[event.event_id],
                    explanation=(
                        "Execution completed far faster than the configured baseline. "
                        "This is an anomaly signal for investigation (e.g. skipped work "
                        "or fabricated completion), not proof of malicious behaviour."
                    ),
                    recommended_response=(
                        "Inspect task inputs/outputs and downstream artefacts to confirm "
                        "the work was actually performed."
                    ),
                    key_evidence={
                        "reported_seconds": reported,
                        "observed_seconds": observed,
                        "baseline_seconds": task_policy.baseline_duration_seconds,
                    },
                )
            )
        return findings

    @staticmethod
    def _duration_from_timestamps(event: Event) -> float | None:
        start_raw = event.evidence.get("start_timestamp")
        end_raw = event.evidence.get("end_timestamp")
        if not isinstance(start_raw, str) or not isinstance(end_raw, str):
            return None
        try:
            start = parse_utc_iso(start_raw)
            end = parse_utc_iso(end_raw)
        except ValueError:
            return None
        return max(0.0, (end - start).total_seconds())


class DataAccessDetector(Detector):
    """RULE-DATA-001 / RULE-DATA-002: unauthorized access attempts and reads."""

    rule_id = "RULE-DATA-001"
    success_rule_id = "RULE-DATA-002"

    def detect(
        self, events: Sequence[Event], policy: PolicyConfig, now: datetime
    ) -> list[Finding]:
        findings: list[Finding] = []
        data_policy = policy.data_policy
        attempts: dict[tuple[str, str, str], list[Event]] = {}
        successes: dict[tuple[str, str, str], list[Event]] = {}
        for event in events:
            resource = event.resource
            if not resource:
                continue
            key = (event.agent_id, event.task_id, resource)
            if event.event_type == EventType.DATA_ACCESS_DENIED:
                attempts.setdefault(key, []).append(event)
            elif event.event_type in (
                EventType.DATA_ACCESS_GRANTED,
                EventType.DATA_READ_COMPLETED,
            ):
                if not data_policy.is_allowed(event.agent_id, resource):
                    successes.setdefault(key, []).append(event)
        for (agent_id, task_id, resource), grouped in attempts.items():
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    agent_id=agent_id,
                    task_id=task_id,
                    severity=Severity.MEDIUM,
                    status=FindingStatus.OPEN,
                    detected_at=max(event.timestamp for event in grouped),
                    expected_behaviour=(
                        f"agent {agent_id!r} may only access "
                        f"{sorted(data_policy.allowed_resources(agent_id))}"
                    ),
                    observed_behaviour=(
                        f"agent {agent_id!r} attempted to access restricted resource "
                        f"{resource!r}; the boundary denied it"
                    ),
                    supporting_event_ids=[event.event_id for event in grouped],
                    explanation=(
                        "An unauthorized access attempt was detected and blocked at "
                        "the data-access boundary. Repeated attempts may indicate "
                        "misconfiguration or probing."
                    ),
                    recommended_response=(
                        "Review the agent's task inputs and permission configuration; "
                        "alert if attempts recur."
                    ),
                    key_evidence={"resource": resource},
                )
            )
        for (agent_id, task_id, resource), grouped in successes.items():
            read_ids = [
                event.event_id
                for event in grouped
                if event.event_type == EventType.DATA_READ_COMPLETED
            ]
            findings.append(
                Finding(
                    rule_id=self.success_rule_id,
                    agent_id=agent_id,
                    task_id=task_id,
                    severity=Severity.HIGH,
                    status=FindingStatus.OPEN,
                    detected_at=max(event.timestamp for event in grouped),
                    expected_behaviour=(
                        "data access to a resource outside the agent's permission set "
                        "must always be denied at the boundary"
                    ),
                    observed_behaviour=(
                        f"agent {agent_id!r} successfully accessed and "
                        + ("completed reads of" if read_ids else "was granted")
                        + f" restricted resource {resource!r} without permission"
                    ),
                    supporting_event_ids=[event.event_id for event in grouped],
                    explanation=(
                        "The event stream records a successful unauthorized data "
                        "access (legacy-bug style). This is a policy breach even if "
                        "the data is synthetic."
                    ),
                    recommended_response=(
                        "Open a security incident, revoke the access path, verify "
                        "what data was exposed, and review boundary enforcement."
                    ),
                    key_evidence={"resource": resource, "read_completed": bool(read_ids)},
                )
            )
        return findings


class EventSequenceDetector(Detector):
    """RULE-SEQ-001 / RULE-SEQ-002: out-of-order and inconsistent events."""

    rule_id = "RULE-SEQ-001"
    inconsistency_rule_id = "RULE-SEQ-002"

    _ORDER_CONSTRAINTS: list[tuple[EventType, EventType, str]] = [
        (EventType.LOAN_REQUESTED, EventType.LOAN_APPROVED, "loan.approved before loan.requested"),
        (EventType.LOAN_REQUESTED, EventType.LOAN_REJECTED, "loan.rejected before loan.requested"),
        (
            EventType.HUMAN_APPROVAL_REQUESTED,
            EventType.HUMAN_APPROVAL_GRANTED,
            "authorization granted before it was requested",
        ),
        (
            EventType.HUMAN_APPROVAL_REQUESTED,
            EventType.HUMAN_APPROVAL_DENIED,
            "authorization denied before it was requested",
        ),
        (
            EventType.DATA_ACCESS_REQUESTED,
            EventType.DATA_ACCESS_GRANTED,
            "data access granted before it was requested",
        ),
        (
            EventType.DATA_ACCESS_REQUESTED,
            EventType.DATA_ACCESS_DENIED,
            "data access denied before it was requested",
        ),
        (
            EventType.DATA_ACCESS_GRANTED,
            EventType.DATA_READ_COMPLETED,
            "data read completed before access was granted",
        ),
        (EventType.TASK_STARTED, EventType.TASK_COMPLETED, "task completed before it started"),
    ]

    def detect(
        self, events: Sequence[Event], policy: PolicyConfig, now: datetime
    ) -> list[Finding]:
        findings: list[Finding] = []
        by_correlation: dict[str, list[Event]] = {}
        for event in events:
            by_correlation.setdefault(event.correlation_id or event.task_id, []).append(event)
        for correlated in by_correlation.values():
            findings.extend(self._out_of_order(correlated))
            findings.extend(self._inconsistencies(correlated))
        return findings

    def _out_of_order(self, correlated: list[Event]) -> list[Finding]:
        findings: list[Finding] = []
        for earlier_type, later_type, description in self._ORDER_CONSTRAINTS:
            later_events = [event for event in correlated if event.event_type == later_type]
            earlier_exists = any(event.event_type == earlier_type for event in correlated)
            for later in later_events:
                later_index = correlated.index(later)
                preceding_ok = any(
                    correlated.index(earlier) < later_index
                    for earlier in correlated
                    if earlier.event_type == earlier_type
                )
                if earlier_exists and not preceding_ok:
                    findings.append(
                        self._finding(
                            correlated,
                            later,
                            observed=f"out-of-order event sequence: {description}",
                            explanation=(
                                "The recorded order of events violates the expected "
                                "workflow sequence, which may indicate tampering or a "
                                "broken emitter."
                            ),
                            key={"kind": "out_of_order", "constraint": description},
                        )
                    )
        return findings

    def _inconsistencies(self, correlated: list[Event]) -> list[Finding]:
        findings: list[Finding] = []
        agent_id = correlated[0].agent_id
        task_id = correlated[0].task_id
        approvals = [e for e in correlated if e.event_type == EventType.LOAN_APPROVED]
        rejections = [e for e in correlated if e.event_type == EventType.LOAN_REJECTED]
        if approvals and rejections:
            findings.append(
                Finding(
                    rule_id=self.inconsistency_rule_id,
                    agent_id=agent_id,
                    task_id=task_id,
                    severity=Severity.HIGH,
                    status=FindingStatus.OPEN,
                    detected_at=max(e.timestamp for e in approvals + rejections),
                    expected_behaviour="a loan workflow has exactly one final outcome",
                    observed_behaviour=(
                        f"workflow records both loan.approved and loan.rejected "
                        f"({len(approvals)} approved / {len(rejections)} rejected)"
                    ),
                    supporting_event_ids=[e.event_id for e in correlated],
                    explanation=(
                        "Conflicting terminal decisions in the same workflow make the "
                        "recorded outcome untrustworthy."
                    ),
                    recommended_response=(
                        "Freeze the workflow, determine the true outcome from "
                        "authoritative records, and audit the event pipeline."
                    ),
                    key_evidence={"kind": "conflicting_final_outcomes"},
                )
            )
        terminal_types = LOAN_TERMINAL_TYPES | {
            EventType.DATA_ACCESS_GRANTED,
            EventType.DATA_ACCESS_DENIED,
            EventType.DATA_READ_COMPLETED,
            EventType.TASK_COMPLETED,
        }
        prerequisite = {
            EventType.LOAN_APPROVED: EventType.LOAN_REQUESTED,
            EventType.LOAN_REJECTED: EventType.LOAN_REQUESTED,
            EventType.LOAN_APPROVAL_BLOCKED: EventType.LOAN_REQUESTED,
            EventType.DATA_ACCESS_GRANTED: EventType.DATA_ACCESS_REQUESTED,
            EventType.DATA_ACCESS_DENIED: EventType.DATA_ACCESS_REQUESTED,
            EventType.DATA_READ_COMPLETED: EventType.DATA_ACCESS_GRANTED,
            EventType.TASK_COMPLETED: EventType.TASK_STARTED,
        }
        for event in correlated:
            if event.event_type not in terminal_types:
                continue
            needed = prerequisite[event.event_type]
            if not any(e.event_type == needed for e in correlated):
                findings.append(
                    self._finding(
                        correlated,
                        event,
                        observed=(
                            f"terminal event {event.event_type.value} recorded without "
                            f"its required prerequisite {needed.value}"
                        ),
                        explanation=(
                            "A terminal event is missing its prerequisite, so the "
                            "workflow sequence is incomplete or inconsistent."
                        ),
                        key={"kind": "missing_prerequisite", "event": event.event_type.value},
                        severity=Severity.MEDIUM,
                    )
                )
        return findings

    def _finding(
        self,
        correlated: list[Event],
        focus: Event,
        observed: str,
        explanation: str,
        key: dict[str, Any],
        severity: Severity = Severity.MEDIUM,
    ) -> Finding:
        return Finding(
            rule_id=self.rule_id,
            agent_id=focus.agent_id,
            task_id=focus.task_id,
            severity=severity,
            status=FindingStatus.OPEN,
            detected_at=focus.timestamp,
            expected_behaviour=(
                "approval, access, and task events must appear in workflow order "
                "with complete prerequisite chains"
            ),
            observed_behaviour=observed,
            supporting_event_ids=[event.event_id for event in correlated],
            explanation=explanation,
            recommended_response=(
                "Verify the emitter implementation and check the event log for "
                "tampering or lost records."
            ),
            key_evidence=key,
        )


def default_detectors() -> list[Detector]:
    return [
        MissingHumanAuthorizationDetector(),
        UnauthorizedApprovalDetector(),
        TaskDurationDetector(),
        DataAccessDetector(),
        EventSequenceDetector(),
    ]


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
