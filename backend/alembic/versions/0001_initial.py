"""Initial PostgreSQL schema for governance workflows."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('APPROVER', 'VIEWER')", name="ck_user_role"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "loan_applications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("applicant_name", sa.String(160), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("purpose", sa.String(500), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("execution_id", sa.String(36), nullable=False),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_loan_amount_positive"),
        sa.CheckConstraint(
            "status IN ('PROCESSING', 'APPROVED', 'REJECTED', 'PENDING_APPROVAL', 'TEST_BLOCKED')",
            name="ck_loan_status",
        ),
    )
    op.create_index("ix_loan_applications_execution_id", "loan_applications", ["execution_id"])
    op.create_index("ix_loan_applications_correlation_id", "loan_applications", ["correlation_id"])
    op.create_index("ix_loan_status_created", "loan_applications", ["status", "created_at"])
    op.create_table(
        "agent_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(120), nullable=False),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("loan_applications.id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("duration_seconds", sa.Numeric(12, 3)),
        sa.Column("timing_mode", sa.String(24), nullable=False),
    )
    op.create_index("ix_agent_executions_agent_id", "agent_executions", ["agent_id"])
    op.create_index("ix_agent_executions_application_id", "agent_executions", ["application_id"])
    op.create_index("ix_agent_executions_correlation_id", "agent_executions", ["correlation_id"])
    op.create_index("ix_execution_agent_started", "agent_executions", ["agent_id", "started_at"])
    op.create_table(
        "agent_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("execution_id", sa.String(36), sa.ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("loan_applications.id", ondelete="SET NULL")),
        sa.Column("agent_id", sa.String(120), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_id", sa.String(120)),
        sa.Column("decision", sa.String(32)),
        sa.Column("resource", sa.String(180)),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    for col in ("execution_id", "application_id", "agent_id", "event_type", "timestamp", "correlation_id"):
        op.create_index(f"ix_agent_events_{col}", "agent_events", [col])
    op.create_index("ix_event_execution_time", "agent_events", ["execution_id", "timestamp"])
    op.create_index("ix_event_type_time", "agent_events", ["event_type", "timestamp"])
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("loan_applications.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("execution_id", sa.String(36), sa.ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_approval_requests_application_id", "approval_requests", ["application_id"])
    op.create_index("ix_approval_requests_execution_id", "approval_requests", ["execution_id"])
    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("loan_applications.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("request_id", sa.String(36), sa.ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("execution_id", sa.String(36), sa.ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("approver_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canonical_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.CheckConstraint("decision IN ('APPROVE', 'REJECT')", name="ck_decision_value"),
    )
    op.create_index("ix_approval_decisions_application_id", "approval_decisions", ["application_id"])
    op.create_index("ix_approval_decisions_request_id", "approval_decisions", ["request_id"])
    op.create_index("ix_approval_decisions_execution_id", "approval_decisions", ["execution_id"])
    op.create_table(
        "governance_alerts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("rule_id", sa.String(80), nullable=False),
        sa.Column("rule_name", sa.String(180), nullable=False),
        sa.Column("agent_id", sa.String(120), nullable=False),
        sa.Column("execution_id", sa.String(36), nullable=False),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("loan_applications.id", ondelete="SET NULL")),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence_event_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("dedupe_key", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')", name="ck_alert_severity"),
        sa.CheckConstraint("status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED')", name="ck_alert_status"),
    )
    for col in ("rule_id", "agent_id", "execution_id", "application_id", "status"):
        op.create_index(f"ix_governance_alerts_{col}", "governance_alerts", [col])
    op.create_index("ix_alert_status_severity", "governance_alerts", ["status", "severity"])
    op.create_index("ix_alert_created", "governance_alerts", ["created_at"])


def downgrade() -> None:
    op.drop_table("governance_alerts")
    op.drop_table("approval_decisions")
    op.drop_table("approval_requests")
    op.drop_table("agent_events")
    op.drop_table("agent_executions")
    op.drop_table("loan_applications")
    op.drop_table("users")
