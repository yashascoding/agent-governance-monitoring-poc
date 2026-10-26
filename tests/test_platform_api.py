from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("JWT_SECRET", "integration-test-jwt-key-with-32-characters")
os.environ.setdefault("APPROVAL_SIGNING_SECRET", "integration-test-signing-key-with-32")
os.environ.setdefault("POSTGRES_HOST", "localhost")

from app.db import Base, get_db
from app.main import app
from app.models import User
from app.security import hash_password


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to an isolated PostgreSQL test database")
    engine = create_engine(database_url)
    if engine.dialect.name != "postgresql":
        pytest.fail("Integration tests require PostgreSQL; SQLite is not supported")
    database_name = database_url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not database_name.endswith("_test") and database_name != "governance_test":
        pytest.fail("TEST_DATABASE_URL must point to an explicitly named *_test database")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_db() -> Generator[Session, None, None]:
        with TestSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setenv("JWT_SECRET", "integration-test-jwt-key-with-32-characters")
    monkeypatch.setenv("APPROVAL_SIGNING_SECRET", "integration-test-signing-key-with-32")
    with TestSession.begin() as db:
        db.add_all(
            [
                User(email="approver@example.com", password_hash=hash_password("correct-approver-password"), role="APPROVER"),
                User(email="viewer@example.com", password_hash=hash_password("correct-viewer-password"), role="VIEWER"),
            ]
        )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_auth_roles_policy_approvals_and_monitoring(client: TestClient) -> None:
    assert client.post(
        "/api/auth/login", json={"email": "approver@example.com", "password": "wrong"}
    ).status_code == 401
    assert client.get("/api/dashboard").status_code == 401
    assert client.get("/api/dashboard", headers={"Authorization": "Bearer invalid"}).status_code == 401

    approver = login(client, "approver@example.com", "correct-approver-password")
    viewer = login(client, "viewer@example.com", "correct-viewer-password")
    assert client.get("/api/dashboard", headers=viewer).status_code == 200
    assert client.post(
        "/api/applications",
        headers=viewer,
        json={"applicant_name": "Viewer", "amount": 500, "purpose": "Should be read only"},
    ).status_code == 403

    auto = client.post(
        "/api/applications",
        headers=approver,
        json={"applicant_name": "Auto Applicant", "amount": 999, "purpose": "Small demo request"},
    )
    assert auto.status_code == 201
    auto_data = auto.json()
    assert auto_data["status"] == "APPROVED"
    auto_events = client.get(
        f"/api/executions/{auto_data['execution_id']}", headers=viewer
    ).json()["events"]
    assert any(event["event_type"] == "loan.approved" for event in auto_events)

    pending = client.post(
        "/api/applications",
        headers=approver,
        json={"applicant_name": "Human Applicant", "amount": 1000, "purpose": "Needs approver"},
    )
    assert pending.status_code == 201
    pending_data = pending.json()
    assert pending_data["status"] == "PENDING_APPROVAL"
    denied = client.post(
        f"/api/applications/{pending_data['id']}/decision",
        headers=viewer,
        json={"decision": "APPROVE", "reason": "Unauthorized decision"},
    )
    assert denied.status_code == 403
    blank_reason = client.post(
        f"/api/applications/{pending_data['id']}/decision",
        headers=approver,
        json={"decision": "APPROVE", "reason": "   "},
    )
    assert blank_reason.status_code == 422
    approved = client.post(
        f"/api/applications/{pending_data['id']}/decision",
        headers=approver,
        json={"decision": "APPROVE", "reason": "Synthetic evidence meets policy"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["decision"]["signature_verified"] is True
    assert client.post(
        f"/api/applications/{pending_data['id']}/decision",
        headers=approver,
        json={"decision": "REJECT", "reason": "Duplicate must fail"},
    ).status_code == 409
    assert any(
        event["event_type"] == "approval.decision_verified"
        for event in client.get(
            f"/api/executions/{pending_data['execution_id']}", headers=viewer
        ).json()["events"]
    )

    large = client.post(
        "/api/applications",
        headers=approver,
        json={"applicant_name": "Large Applicant", "amount": 2000, "purpose": "Human workflow"},
    ).json()
    assert large["status"] == "PENDING_APPROVAL"
    rejected = client.post(
        f"/api/applications/{large['id']}/decision",
        headers=approver,
        json={"decision": "REJECT", "reason": "Synthetic test rejection"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"
    assert rejected.json()["decision"]["signature_verified"] is True
    rejected_events = client.get(
        f"/api/executions/{large['execution_id']}", headers=viewer
    ).json()["events"]
    assert any(event["event_type"] == "loan.rejected" for event in rejected_events)
    assert client.post(
        f"/api/applications/{large['id']}/decision",
        headers=approver,
        json={"decision": "APPROVE", "reason": "Duplicate must fail"},
    ).status_code == 409

    normal_scenario = client.post(
        "/api/scenarios",
        headers=approver,
        json={"scenario": "normal_auto_approval"},
    )
    assert normal_scenario.status_code == 201
    assert normal_scenario.json()["passed"] is True
    assert normal_scenario.json()["alert_ids"] == []
    human_scenario = client.post(
        "/api/scenarios",
        headers=approver,
        json={"scenario": "human_approval"},
    )
    assert human_scenario.status_code == 201
    assert human_scenario.json()["passed"] is True
    assert human_scenario.json()["application_id"]
    assert human_scenario.json()["evidence_events"]

    bypass = client.post(
        "/api/scenarios",
        headers=approver,
        json={"scenario": "approval_bypass"},
    )
    assert bypass.status_code == 201
    bypass_data = bypass.json()
    assert bypass_data["passed"] is True
    assert bypass_data["alert_ids"]
    alert = client.get(f"/api/alerts/{bypass_data['alert_ids'][0]}", headers=viewer).json()
    assert alert["severity"] == "HIGH"
    assert alert["evidence_event_ids"]
    assert any(event["event_type"] == "loan.approval_blocked" for event in alert["events"])

    abnormal = client.post(
        "/api/scenarios", headers=approver, json={"scenario": "abnormal_duration"}
    )
    assert abnormal.status_code == 201
    assert abnormal.json()["passed"] is True
    unauthorized = client.post(
        "/api/scenarios",
        headers=approver,
        json={"scenario": "unauthorized_resource_access"},
    )
    assert unauthorized.status_code == 201
    assert unauthorized.json()["passed"] is True
    assert client.post(
        "/api/scenarios", headers=viewer, json={"scenario": "approval_bypass"}
    ).status_code == 403
