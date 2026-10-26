from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.loan_agent import ApprovalRequiredError, LoanAgent
from governance.clock import SystemClock
from governance.detectors import (
    DataAccessDetector,
    MissingHumanAuthorizationDetector,
    TaskDurationDetector,
    UnauthorizedApprovalDetector,
)
from governance.event_schema import Event, EventType
from governance.findings import FindingStatus, Severity
from governance.policy_loader import load_policy_config

from app.models import (
    AgentEvent,
    AgentExecution,
    ApprovalDecision,
    ApprovalRequest,
    GovernanceAlert,
    LoanApplication,
    User,
    utc_now,
)
from app.security import (
    decision_payload,
    sign_decision,
    verify_approval_record,
    verify_decision_signature,
)


class DatabaseEventStore:
    def __init__(self, db: Session, execution: AgentExecution, application_id: str | None):
        self.db = db
        self.execution = execution
        self.application_id = application_id

    def append(self, event: Event) -> None:
        self.db.add(
            AgentEvent(
                id=event.event_id,
                execution_id=self.execution.id,
                application_id=self.application_id,
                agent_id=event.agent_id,
                event_type=event.event_type.value,
                action=event.action,
                timestamp=event.timestamp,
                policy_id=event.policy_id,
                decision=event.decision,
                resource=event.resource,
                correlation_id=event.correlation_id or event.task_id,
                payload=event.to_dict(),
            )
        )


def make_agent(db: Session, execution: AgentExecution, app: LoanApplication | None, agent_id: str = "loan-agent") -> LoanAgent:
    policy = load_policy_config("config/policies.yaml")
    return LoanAgent(
        agent_id=agent_id,
        policy=policy.loan_policy,
        store=DatabaseEventStore(db, execution, app.id if app else None),
        clock=SystemClock(),
        run_id=execution.id,
    )


def add_event(
    db: Session,
    execution: AgentExecution,
    event_type: str,
    action: str,
    *,
    application: LoanApplication | None = None,
    payload: dict[str, Any] | None = None,
    resource: str | None = None,
    decision: str | None = None,
) -> AgentEvent:
    event_id = str(uuid.uuid4())
    timestamp = utc_now()
    event_payload = {
        "event_id": event_id,
        "timestamp": timestamp.isoformat(),
        "agent_id": execution.agent_id,
        "run_id": execution.id,
        "task_id": execution.correlation_id,
        "event_type": event_type,
        "action": action,
        "resource": resource,
        "policy_id": "POL-MON-001",
        "decision": decision,
        "correlation_id": execution.correlation_id,
        "evidence": payload or {},
    }
    event = AgentEvent(
        id=event_id,
        execution_id=execution.id,
        application_id=application.id if application else None,
        agent_id=execution.agent_id,
        event_type=event_type,
        action=action,
        timestamp=timestamp,
        policy_id="POL-MON-001",
        decision=decision,
        resource=resource,
        correlation_id=execution.correlation_id,
        payload=event_payload,
    )
    db.add(event)
    return event


def complete_execution(execution: AgentExecution, duration: Decimal | None = None) -> None:
    execution.completed_at = utc_now()
    execution.status = "COMPLETED"
    execution.duration_seconds = duration or Decimal(
        str((execution.completed_at - execution.started_at).total_seconds())
    )


def create_application_workflow(db: Session, data: Any) -> LoanApplication:
    loan_policy = load_policy_config("config/policies.yaml").loan_policy
    execution_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    app = LoanApplication(
        id=str(uuid.uuid4()),
        applicant_name=data.applicant_name,
        amount=data.amount,
        purpose=data.purpose,
        status="PROCESSING",
        execution_id=execution_id,
        correlation_id=correlation_id,
    )
    execution = AgentExecution(
        id=execution_id,
        agent_id="loan-agent",
        application_id=app.id,
        correlation_id=correlation_id,
        started_at=utc_now(),
    )
    db.add(app)
    db.flush()
    db.add(execution)
    db.flush()
    agent = make_agent(db, execution, app)
    agent.request_loan(app.id, float(app.amount))
    add_event(
        db,
        execution,
        "policy.evaluated",
        "evaluate_loan_policy",
        application=app,
        payload={
            "policy_id": "POL-LOAN-001",
            "amount": str(app.amount),
            "requires_human_approval": loan_policy.requires_human_approval(float(app.amount)),
            "outcome": "human_approval_required"
            if loan_policy.requires_human_approval(float(app.amount))
            else "automatic_approval_allowed",
        },
        decision="evaluated",
    )
    agent.auto_approve_if_eligible(app.id)
    app.status = (
        "APPROVED"
        if loan_policy.may_auto_approve(float(app.amount))
        else "PENDING_APPROVAL"
    )
    if app.status == "PENDING_APPROVAL":
        db.add(ApprovalRequest(application_id=app.id, execution_id=execution.id))
        execution.status = "WAITING_FOR_APPROVAL"
    else:
        complete_execution(execution)
    app.updated_at = utc_now()
    evaluate_loan_monitor(db, app, execution)
    return app


def apply_decision(
    db: Session, app: LoanApplication, user: User, decision: str, reason: str
) -> ApprovalDecision:
    request = db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.application_id == app.id)
        .with_for_update()
    )
    if request is None or request.status != "PENDING" or app.status != "PENDING_APPROVAL":
        raise ValueError("application has no pending approval request")
    decided_at = utc_now()
    decision_id = str(uuid.uuid4())
    payload = decision_payload(
        decision_id=decision_id,
        application_id=app.id,
        decision=decision,
        reason=reason,
        approver_id=user.id,
        decided_at=decided_at,
    )
    signature = sign_decision(payload)
    if not verify_decision_signature(payload, signature):
        raise ValueError("approval signature verification failed")
    record = ApprovalDecision(
        id=decision_id,
        application_id=app.id,
        request_id=request.id,
        execution_id=request.execution_id,
        approver_id=user.id,
        decision=decision,
        reason=reason,
        decided_at=decided_at,
        canonical_payload=payload,
        signature=signature,
    )
    db.add(record)
    request.status = decision
    app.status = "PROCESSING"
    app.updated_at = decided_at
    execution = db.get(AgentExecution, request.execution_id)
    if execution is None:
        raise ValueError("approval execution no longer exists")
    agent = make_agent(db, execution, app)
    add_event(
        db,
        execution,
        "approval.decision_received",
        "receive_human_decision",
        application=app,
        payload={
            "decision_id": decision_id,
            "approver_id": user.id,
            "decision": decision,
            "reason": reason,
        },
        decision=decision.lower(),
    )
    agent.request_loan(app.id, float(app.amount))
    agent.request_human_approval(app.id)
    agent.record_authorization_result(app.id, decision == "APPROVE")
    add_event(
        db,
        execution,
        "approval.decision_verified",
        "verify_signed_approval",
        application=app,
        payload={
            "decision_id": decision_id,
            "signature_verified": True,
            "approver_id": user.id,
            "decision": decision,
        },
        decision="verified",
    )
    if decision == "APPROVE":
        agent.finalize_approval(app.id)
        app.status = "APPROVED"
    else:
        agent.reject(app.id, reason)
        app.status = "REJECTED"
    complete_execution(execution)
    evaluate_loan_monitor(db, app, execution)
    return record


def evaluate_loan_monitor(db: Session, app: LoanApplication, execution: AgentExecution) -> list[GovernanceAlert]:
    return evaluate_execution_monitor(db, execution, app)


def evaluate_execution_monitor(
    db: Session, execution: AgentExecution, application: LoanApplication | None = None
) -> list[GovernanceAlert]:
    db.flush()
    records = list(
        db.scalars(
            select(AgentEvent)
            .where(AgentEvent.execution_id == execution.id)
            .order_by(AgentEvent.timestamp)
        )
    )
    known_types = {event_type.value for event_type in EventType}
    events = [
        Event.from_dict(record.payload)
        for record in records
        if record.event_type in known_types
    ]
    policy = load_policy_config("config/policies.yaml")
    anomaly_threshold = float(
        os.getenv(
            "ANOMALY_THRESHOLD_SECONDS",
            str(policy.task_policy.anomaly_min_duration_seconds),
        )
    )
    if anomaly_threshold <= 0:
        raise ValueError("ANOMALY_THRESHOLD_SECONDS must be positive")
    policy = replace(
        policy,
        task_policy=replace(
            policy.task_policy,
            anomaly_min_duration_seconds=anomaly_threshold,
        ),
    )
    findings = []
    for detector in (
        MissingHumanAuthorizationDetector(),
        UnauthorizedApprovalDetector(),
        TaskDurationDetector(),
        DataAccessDetector(),
    ):
        findings.extend(detector.detect(events, policy, utc_now()))

    if application is not None:
        loan_policy = policy.loan_policy
        if (
            application.amount >= Decimal(str(loan_policy.human_approval_required_at))
            and application.status == "APPROVED"
        ):
            decision = db.scalar(
                select(ApprovalDecision).where(
                    ApprovalDecision.application_id == application.id
                )
            )
            signature_is_valid = bool(
                decision
                and decision.decision == "APPROVE"
                and verify_approval_record(decision)
            )
            if not signature_is_valid and not any(
                finding.rule_id == "RULE-LOAN-001"
                for finding in findings
            ):
                findings.append(
                    {
                        "rule_id": "RULE-LOAN-001",
                        "rule_name": "Human approval bypass",
                        "severity": "HIGH",
                        "description": (
                            "A high-value loan was approved without a valid signed "
                            "human decision."
                        ),
                        "event_ids": [event.id for event in records],
                        "evidence": {
                            "amount": str(application.amount),
                            "application_id": application.id,
                            "valid_signed_decision": False,
                        },
                    }
                )

    rule_names = {
        "RULE-LOAN-001": "Human approval bypass",
        "RULE-LOAN-002": "Unauthorized final approval",
        "RULE-TASK-001": "Abnormal execution duration",
        "RULE-DATA-001": "Unauthorized resource access",
        "RULE-DATA-002": "Unauthorized resource read",
    }
    event_ids = {record.id for record in records}
    created: list[GovernanceAlert] = []
    for finding in findings:
        if isinstance(finding, dict):
            rule_id = finding["rule_id"]
            rule_name = finding["rule_name"]
            severity = finding["severity"]
            description = finding["description"]
            evidence_ids = finding["event_ids"]
            evidence = finding["evidence"]
        else:
            if finding.status != FindingStatus.OPEN:
                continue
            rule_id = finding.rule_id
            rule_name = rule_names.get(rule_id, rule_id)
            severity = (
                "HIGH"
                if finding.severity == Severity.CRITICAL
                else finding.severity.value
            )
            description = finding.observed_behaviour
            evidence_ids = [
                event_id
                for event_id in finding.supporting_event_ids
                if event_id in event_ids
            ]
            evidence = {
                "expected": finding.expected_behaviour,
                "observed": finding.observed_behaviour,
                "explanation": finding.explanation,
                "key_evidence": finding.key_evidence,
                "simulated": any(
                    event.payload.get("evidence", {}).get("timing_mode") == "simulated"
                    for event in records
                    if event.id in evidence_ids
                ),
            }
        dedupe_key = hashlib.sha256(
            f"{rule_id}:{execution.id}".encode()
        ).hexdigest()
        if db.scalar(
            select(GovernanceAlert.id).where(
                GovernanceAlert.dedupe_key == dedupe_key
            )
        ):
            continue
        alert = GovernanceAlert(
            severity=severity,
            rule_id=rule_id,
            rule_name=rule_name,
            agent_id=execution.agent_id,
            execution_id=execution.id,
            application_id=application.id if application else None,
            description=description,
            evidence_event_ids=evidence_ids,
            evidence=evidence,
            status="OPEN",
            correlation_id=execution.correlation_id,
            dedupe_key=dedupe_key,
        )
        db.add(alert)
        created.append(alert)
    return created


def create_demo_scenario(db: Session, scenario: str) -> tuple[dict[str, Any], list[GovernanceAlert]]:
    if scenario == "normal_auto_approval":
        from app.schemas import LoanCreate

        app = create_application_workflow(
            db,
            LoanCreate(applicant_name="Demo applicant", amount=Decimal("500"), purpose="Scenario: normal automatic approval"),
        )
        return {
            "scenario": scenario,
            "expected": "Application is automatically approved and no bypass alert is created.",
            "actual": f"Application status is {app.status}.",
            "passed": app.status == "APPROVED",
            "execution_id": app.execution_id,
            "application_id": app.id,
            "evidence": ["loan.requested", "loan.approved"],
            "alert_ids": [],
        }, []
    if scenario == "human_approval":
        from app.schemas import LoanCreate

        app = create_application_workflow(
            db,
            LoanCreate(applicant_name="Demo applicant", amount=Decimal("2000"), purpose="Scenario: human approval"),
        )
        return {
            "scenario": scenario,
            "expected": "Application remains pending until an approver records a signed decision.",
            "actual": f"Application status is {app.status}; an approver can decide it in the approval queue.",
            "passed": app.status == "PENDING_APPROVAL",
            "execution_id": app.execution_id,
            "application_id": app.id,
            "evidence": ["loan.requested", "human_approval.requested"],
            "alert_ids": [],
        }, []
    if scenario == "approval_bypass":
        app = LoanApplication(
            id=str(uuid.uuid4()),
            applicant_name="Isolated test fixture",
            amount=Decimal("2000"),
            purpose="Controlled policy-bypass test; not a real loan",
            status="TEST_BLOCKED",
            execution_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
        )
        execution = AgentExecution(
            id=app.execution_id,
            agent_id="loan-agent-test-fixture",
            application_id=app.id,
            correlation_id=app.correlation_id,
            started_at=utc_now(),
        )
        db.add(app)
        db.flush()
        db.add(execution)
        db.flush()
        agent = make_agent(db, execution, app, agent_id="loan-agent-test-fixture")
        agent.request_loan(app.id, float(app.amount))
        try:
            agent.attempt_unauthorized_approval(app.id)
        except ApprovalRequiredError:
            pass
        else:
            raise RuntimeError("loan agent failed to enforce the human-approval policy")
        complete_execution(execution)
        alerts = evaluate_loan_monitor(db, app, execution)
        return {
            "scenario": scenario,
            "expected": "High-severity alert is generated and no legitimate approval is finalized.",
            "actual": "The enforcement boundary blocked the test agent; the monitor recorded the attempt.",
            "passed": bool(alerts) and app.status == "TEST_BLOCKED",
            "execution_id": execution.id,
            "application_id": app.id,
            "evidence": ["loan.requested", "loan.approval_blocked"],
            "alert_ids": [alert.id for alert in alerts],
        }, alerts
    if scenario == "abnormal_duration":
        task_policy = load_policy_config("config/policies.yaml").task_policy
        baseline_seconds = Decimal(str(task_policy.baseline_duration_seconds))
        execution = AgentExecution(
            agent_id="task-agent-test-fixture",
            correlation_id=str(uuid.uuid4()),
            started_at=utc_now(),
            timing_mode="simulated",
            duration_seconds=Decimal("10.000"),
            completed_at=utc_now(),
            status="COMPLETED",
        )
        db.add(execution)
        db.flush()
        add_event(
            db,
            execution,
            "task.started",
            "start_test_task",
            payload={"timing_mode": "simulated", "baseline_seconds": float(baseline_seconds)},
        )
        add_event(
            db,
            execution,
            "task.completed",
            "complete_test_task",
            payload={"duration_seconds": 10, "timing_mode": "simulated"},
        )
        threshold = Decimal(
            os.getenv(
                "ANOMALY_THRESHOLD_SECONDS",
                str(task_policy.anomaly_min_duration_seconds),
            )
        )
        alerts = evaluate_execution_monitor(db, execution)
        return {
            "scenario": scenario,
            "expected": f"Duration below {threshold}s produces an anomaly alert.",
            "actual": "10-second simulated execution was evaluated against the configured threshold.",
            "passed": bool(alerts),
            "execution_id": execution.id,
            "application_id": None,
            "evidence": ["task.started", "task.completed (simulated timing)"],
            "alert_ids": [alert.id for alert in alerts],
        }, alerts
    if scenario == "unauthorized_resource_access":
        resource_policy = load_policy_config("config/policies.yaml").data_policy
        execution = AgentExecution(
            agent_id="data-agent-test-fixture",
            correlation_id=str(uuid.uuid4()),
            started_at=utc_now(),
        )
        db.add(execution)
        db.flush()
        resource = "restricted_credit_records"
        allowed_resources = set(resource_policy.allowed_resources("data-agent"))
        add_event(db, execution, "data.access_requested", "request_resource", resource=resource)
        denied = resource not in allowed_resources
        add_event(
            db,
            execution,
            "data.access_denied" if denied else "data.access_granted",
            "enforce_resource_boundary",
            resource=resource,
            payload={"permitted_resources": sorted(allowed_resources), "access_granted": not denied},
        )
        complete_execution(execution)
        alerts = evaluate_execution_monitor(db, execution)
        return {
            "scenario": scenario,
            "expected": "Out-of-scope resource access is denied and generates an alert.",
            "actual": f"Access to {resource} was {'denied' if denied else 'granted'} at the backend boundary.",
            "passed": denied and bool(alerts),
            "execution_id": execution.id,
            "application_id": None,
            "evidence": ["data.access_requested", "data.access_denied"],
            "alert_ids": [alert.id for alert in alerts],
        }, alerts
    raise ValueError(f"unsupported scenario: {scenario}")
