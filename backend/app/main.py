from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Any

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.events import alert_broadcaster
from app.models import (
    AgentEvent,
    AgentExecution,
    ApprovalDecision,
    ApprovalRequest,
    GovernanceAlert,
    LoanApplication,
    User,
)
from app.schemas import (
    AlertUpdate,
    DecisionRequest,
    HealthView,
    LoanCreate,
    LoginRequest,
    ScenarioRequest,
    TokenView,
    UserView,
)
from app.security import (
    ApproverUser,
    CurrentUser,
    create_access_token,
    verify_approval_record,
    verify_password,
)
from app.workflows import apply_decision, create_application_workflow, create_demo_scenario

@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("APP_ENV", "development").lower() in {"production", "prod"}:
        for secret_name in ("JWT_SECRET", "APPROVAL_SIGNING_SECRET"):
            if len(os.getenv(secret_name, "")) < 32:
                raise RuntimeError(
                    f"{secret_name} must be configured with at least 32 characters in production"
                )
    yield


app = FastAPI(
    title="AI Agent Governance & Monitoring Platform",
    version="1.0.0",
    description="Local governance console for loan-agent workflows, human approvals, policy monitoring, and audit evidence.",
    lifespan=lifespan,
)

configured_origins = [
    item.strip()
    for item in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def application_json(item: LoanApplication, db: Session) -> dict[str, Any]:
    decision = db.scalar(
        select(ApprovalDecision).where(ApprovalDecision.application_id == item.id)
    )
    return {
        "id": item.id,
        "applicant_name": item.applicant_name,
        "amount": str(item.amount),
        "purpose": item.purpose,
        "status": item.status,
        "execution_id": item.execution_id,
        "correlation_id": item.correlation_id,
        "correlation_id": item.correlation_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "decision": (
            {
                "id": decision.id,
                "decision": decision.decision,
                "reason": decision.reason,
                "approver_id": decision.approver_id,
                "decided_at": decision.decided_at,
                "signature": decision.signature,
                "signature_verified": verify_approval_record(decision),
            }
            if decision
            else None
        ),
    }


def alert_json(item: GovernanceAlert) -> dict[str, Any]:
    return {
        "id": item.id,
        "severity": item.severity,
        "rule_id": item.rule_id,
        "rule_name": item.rule_name,
        "agent_id": item.agent_id,
        "execution_id": item.execution_id,
        "application_id": item.application_id,
        "description": item.description,
        "evidence_event_ids": item.evidence_event_ids,
        "evidence": item.evidence,
        "status": item.status,
        "correlation_id": item.correlation_id,
        "created_at": item.created_at,
    }


def event_json(item: AgentEvent) -> dict[str, Any]:
    return {
        "id": item.id,
        "execution_id": item.execution_id,
        "application_id": item.application_id,
        "agent_id": item.agent_id,
        "event_type": item.event_type,
        "action": item.action,
        "timestamp": item.timestamp,
        "policy_id": item.policy_id,
        "decision": item.decision,
        "resource": item.resource,
        "correlation_id": item.correlation_id,
        "payload": item.payload,
    }


def page(query: Any, db: Session, limit: int, offset: int) -> dict[str, Any]:
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.limit(limit).offset(offset)).all()
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


@app.get("/api/health", response_model=HealthView)
def health(db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@app.post("/api/auth/login", response_model=TokenView)
def login(body: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "expires_in": int(os.getenv("JWT_EXPIRY_MINUTES", "30")) * 60,
        "user": {"id": user.id, "email": user.email, "role": user.role},
    }


@app.get("/api/auth/me", response_model=UserView)
def who_am_i(user: CurrentUser) -> dict[str, str]:
    return {"id": user.id, "email": user.email, "role": user.role}


@app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(_: CurrentUser) -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/dashboard")
def dashboard(_: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    return {
        "total_executions": db.scalar(select(func.count()).select_from(AgentExecution)) or 0,
        "total_alerts": db.scalar(select(func.count()).select_from(GovernanceAlert)) or 0,
        "open_high_alerts": db.scalar(
            select(func.count()).select_from(GovernanceAlert).where(
                GovernanceAlert.severity.in_(["HIGH", "CRITICAL"]), GovernanceAlert.status == "OPEN"
            )
        ) or 0,
        "pending_approvals": db.scalar(
            select(func.count()).select_from(ApprovalRequest).where(ApprovalRequest.status == "PENDING")
        ) or 0,
        "policy_violations": db.scalar(
            select(func.count()).select_from(GovernanceAlert).where(
                GovernanceAlert.rule_id == "RULE-LOAN-001"
            )
        ) or 0,
        "recent_executions": [
            {
                "id": row.id,
                "agent_id": row.agent_id,
                "status": row.status,
                "started_at": row.started_at,
                "application_id": row.application_id,
            }
            for row in db.scalars(
                select(AgentExecution).order_by(AgentExecution.started_at.desc()).limit(6)
            )
        ],
        "recent_alerts": [
            alert_json(row)
            for row in db.scalars(
                select(GovernanceAlert).order_by(GovernanceAlert.created_at.desc()).limit(6)
            )
        ],
        "recent_decisions": [
            {
                "id": row.id,
                "application_id": row.application_id,
                "decision": row.decision,
                "approver_id": row.approver_id,
                "reason": row.reason,
                "decided_at": row.decided_at,
            }
            for row in db.scalars(
                select(ApprovalDecision).order_by(ApprovalDecision.decided_at.desc()).limit(6)
            )
        ],
    }


@app.get("/api/applications")
def list_applications(
    _: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    query = select(LoanApplication)
    if status_filter:
        query = query.where(LoanApplication.status == status_filter.upper())
    if search:
        query = query.where(LoanApplication.applicant_name.ilike(f"%{search}%"))
    result = page(query.order_by(LoanApplication.created_at.desc()), db, limit, offset)
    return {**result, "items": [application_json(item, db) for item in result["items"]]}


@app.post("/api/applications", status_code=status.HTTP_201_CREATED)
async def submit_application(
    body: LoanCreate,
    _: ApproverUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    item = create_application_workflow(db, body)
    alerts = db.scalars(
        select(GovernanceAlert).where(
            GovernanceAlert.execution_id == item.execution_id
        )
    ).all()
    db.commit()
    for alert in alerts:
        await alert_broadcaster.publish(alert_json(alert))
    return application_json(item, db)


@app.get("/api/applications/{application_id}")
def application_detail(
    application_id: str, _: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> dict[str, Any]:
    item = db.get(LoanApplication, application_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Application not found")
    events = db.scalars(
        select(AgentEvent).where(AgentEvent.application_id == item.id).order_by(AgentEvent.timestamp)
    )
    return {**application_json(item, db), "events": [event_json(event) for event in events]}


@app.get("/api/approvals")
def approval_queue(_: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(LoanApplication)
        .join(ApprovalRequest, ApprovalRequest.application_id == LoanApplication.id)
        .where(ApprovalRequest.status == "PENDING")
        .order_by(ApprovalRequest.requested_at)
    )
    return [application_json(item, db) for item in rows]


@app.post("/api/applications/{application_id}/decision", status_code=status.HTTP_200_OK)
async def decide_application(
    application_id: str,
    body: DecisionRequest,
    user: ApproverUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    item = db.scalar(
        select(LoanApplication).where(LoanApplication.id == application_id).with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Application not found")
    try:
        record = apply_decision(db, item, user, body.decision, body.reason)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A decision was already recorded") from exc
    new_alerts = db.scalars(
        select(GovernanceAlert).where(
            GovernanceAlert.execution_id == record.execution_id,
            GovernanceAlert.created_at >= record.decided_at,
        )
    )
    for alert in new_alerts:
        await alert_broadcaster.publish(alert_json(alert))
    return application_json(item, db)


@app.get("/api/alerts")
def list_alerts(
    _: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    severity: str | None = None,
    rule_id: str | None = None,
    agent_id: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    sort: str = Query(default="newest", pattern="^(newest|oldest|severity)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    query = select(GovernanceAlert)
    if severity:
        query = query.where(GovernanceAlert.severity == severity.upper())
    if rule_id:
        query = query.where(GovernanceAlert.rule_id == rule_id)
    if agent_id:
        query = query.where(GovernanceAlert.agent_id == agent_id)
    if status_filter:
        query = query.where(GovernanceAlert.status == status_filter.upper())
    ordering = {
        "newest": GovernanceAlert.created_at.desc(),
        "oldest": GovernanceAlert.created_at.asc(),
        "severity": case(
            (GovernanceAlert.severity == "CRITICAL", 0),
            (GovernanceAlert.severity == "HIGH", 1),
            (GovernanceAlert.severity == "MEDIUM", 2),
            (GovernanceAlert.severity == "LOW", 3),
            else_=4,
        ).asc(),
    }[sort]
    result = page(query.order_by(ordering), db, limit, offset)
    return {**result, "items": [alert_json(item) for item in result["items"]]}


@app.get("/api/alerts/stream")
async def stream_alerts(_: CurrentUser) -> StreamingResponse:
    queue = await alert_broadcaster.subscribe()

    async def stream():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=20)
                    yield f"event: alert\ndata: {message}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            alert_broadcaster.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/alerts/{alert_id}")
def alert_detail(
    alert_id: str, _: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> dict[str, Any]:
    item = db.get(GovernanceAlert, alert_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    events = db.scalars(
        select(AgentEvent)
        .where(AgentEvent.id.in_(item.evidence_event_ids))
        .order_by(AgentEvent.timestamp)
    )
    return {**alert_json(item), "events": [event_json(event) for event in events]}


@app.patch("/api/alerts/{alert_id}")
def update_alert(
    alert_id: str,
    body: AlertUpdate,
    user: ApproverUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    item = db.get(GovernanceAlert, alert_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    item.status = body.status
    item.acknowledged_by = user.id
    item.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    return alert_json(item)


@app.get("/api/agents")
def agents(_: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            AgentExecution.agent_id,
            func.count(AgentExecution.id).label("execution_count"),
            func.max(AgentExecution.started_at).label("last_execution"),
        ).group_by(AgentExecution.agent_id)
    ).all()
    found = {
        row.agent_id: {
            "id": row.agent_id,
            "execution_count": row.execution_count,
            "last_execution": row.last_execution,
            "status": "MONITORED",
        }
        for row in rows
    }
    if "loan-agent" not in found:
        found["loan-agent"] = {
            "id": "loan-agent",
            "execution_count": 0,
            "last_execution": None,
            "status": "MONITORED",
        }
    return list(found.values())


@app.get("/api/executions")
def executions(
    _: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    agent_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    query = select(AgentExecution)
    if agent_id:
        query = query.where(AgentExecution.agent_id == agent_id)
    result = page(query.order_by(AgentExecution.started_at.desc()), db, limit, offset)
    return {
        **result,
        "items": [
            {
                "id": item.id,
                "agent_id": item.agent_id,
                "application_id": item.application_id,
                "correlation_id": item.correlation_id,
                "status": item.status,
                "started_at": item.started_at,
                "completed_at": item.completed_at,
                "duration_seconds": str(item.duration_seconds) if item.duration_seconds is not None else None,
                "timing_mode": item.timing_mode,
            }
            for item in result["items"]
        ],
    }


@app.get("/api/executions/{execution_id}")
def execution_detail(
    execution_id: str, _: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> dict[str, Any]:
    item = db.get(AgentExecution, execution_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    events = db.scalars(
        select(AgentEvent).where(AgentEvent.execution_id == item.id).order_by(AgentEvent.timestamp)
    )
    alerts = db.scalars(
        select(GovernanceAlert).where(GovernanceAlert.execution_id == item.id)
    )
    return {
        "id": item.id,
        "agent_id": item.agent_id,
        "application_id": item.application_id,
        "correlation_id": item.correlation_id,
        "status": item.status,
        "started_at": item.started_at,
        "completed_at": item.completed_at,
        "duration_seconds": str(item.duration_seconds) if item.duration_seconds is not None else None,
        "timing_mode": item.timing_mode,
        "events": [event_json(event) for event in events],
        "alerts": [alert_json(alert) for alert in alerts],
    }


@app.get("/api/executions/{execution_id}/events")
def execution_events(
    execution_id: str,
    _: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    if db.get(AgentExecution, execution_id) is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    query = select(AgentEvent).where(AgentEvent.execution_id == execution_id)
    result = page(query.order_by(AgentEvent.timestamp), db, limit, offset)
    return {**result, "items": [event_json(item) for item in result["items"]]}


@app.post("/api/scenarios", status_code=status.HTTP_201_CREATED)
async def run_scenario(
    body: ScenarioRequest,
    _: ApproverUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    result, alerts = create_demo_scenario(db, body.scenario)
    db.flush()
    result["alert_ids"] = [alert.id for alert in alerts]
    evidence = db.scalars(
        select(AgentEvent)
        .where(AgentEvent.execution_id == result["execution_id"])
        .order_by(AgentEvent.timestamp)
    ).all()
    result["evidence"] = [item.event_type for item in evidence]
    result["evidence_events"] = [
        {"id": item.id, "event_type": item.event_type, "timestamp": item.timestamp}
        for item in evidence
    ]
    result["recorded_at"] = datetime.now(timezone.utc).isoformat()
    db.commit()
    for alert in alerts:
        await alert_broadcaster.publish(alert_json(alert))
    return result
