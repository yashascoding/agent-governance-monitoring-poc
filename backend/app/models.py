from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    DateTime,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('APPROVER', 'VIEWER')", name="ck_user_role"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LoanApplication(Base):
    __tablename__ = "loan_applications"
    __table_args__ = (
        Index("ix_loan_status_created", "status", "created_at"),
        CheckConstraint("amount > 0", name="ck_loan_amount_positive"),
        CheckConstraint(
            "status IN ('PROCESSING', 'APPROVED', 'REJECTED', 'PENDING_APPROVAL', 'TEST_BLOCKED')",
            name="ck_loan_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    applicant_name: Mapped[str] = mapped_column(String(160))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    purpose: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(24), default="PROCESSING")
    execution_id: Mapped[str] = mapped_column(String(36), index=True)
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    approval_request: Mapped["ApprovalRequest | None"] = relationship(
        back_populates="application", uselist=False
    )


class AgentExecution(Base):
    __tablename__ = "agent_executions"
    __table_args__ = (Index("ix_execution_agent_started", "agent_id", "started_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(String(120), index=True)
    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("loan_applications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(24), default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    timing_mode: Mapped[str] = mapped_column(String(24), default="measured")


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (
        Index("ix_event_execution_time", "execution_id", "timestamp"),
        Index("ix_event_type_time", "event_type", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="CASCADE"), index=True
    )
    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("loan_applications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(120), index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    action: Mapped[str] = mapped_column(String(120))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    policy_id: Mapped[str | None] = mapped_column(String(120))
    decision: Mapped[str | None] = mapped_column(String(32))
    resource: Mapped[str | None] = mapped_column(String(180))
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (UniqueConstraint("application_id", name="uq_approval_application"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("loan_applications.id", ondelete="CASCADE"), index=True
    )
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="PENDING")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    application: Mapped[LoanApplication] = relationship(back_populates="approval_request")


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"
    __table_args__ = (
        UniqueConstraint("application_id", name="uq_decision_application"),
        CheckConstraint("decision IN ('APPROVE', 'REJECT')", name="ck_decision_value"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("loan_applications.id", ondelete="CASCADE"), index=True
    )
    request_id: Mapped[str] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="CASCADE"), index=True
    )
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="CASCADE"), index=True
    )
    approver_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    canonical_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    signature: Mapped[str] = mapped_column(String(64))


class GovernanceAlert(Base):
    __tablename__ = "governance_alerts"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_alert_dedupe_key"),
        Index("ix_alert_status_severity", "status", "severity"),
        Index("ix_alert_created", "created_at"),
        CheckConstraint("severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')", name="ck_alert_severity"),
        CheckConstraint("status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED')", name="ck_alert_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    severity: Mapped[str] = mapped_column(String(16))
    rule_id: Mapped[str] = mapped_column(String(80), index=True)
    rule_name: Mapped[str] = mapped_column(String(180))
    agent_id: Mapped[str] = mapped_column(String(120), index=True)
    execution_id: Mapped[str] = mapped_column(String(36), index=True)
    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("loan_applications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    description: Mapped[str] = mapped_column(Text)
    evidence_event_ids: Mapped[list[str]] = mapped_column(JSONB)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    acknowledged_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
