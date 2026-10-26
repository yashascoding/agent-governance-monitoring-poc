from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

os.environ.setdefault("JWT_SECRET", "unit-test-jwt-key-with-at-least-32-characters")
os.environ.setdefault("APPROVAL_SIGNING_SECRET", "unit-test-approval-key-with-at-least-32")

from app.models import User
from app.security import (
    create_access_token,
    decision_payload,
    hash_password,
    require_approver,
    sign_decision,
    verify_approval_record,
    verify_decision_signature,
    verify_password,
    sign_decision,
)


def test_argon2_password_hash_is_not_plaintext() -> None:
    encoded = hash_password("local-test-password")
    assert encoded != "local-test-password"
    assert encoded.startswith("$argon2")
    assert verify_password("local-test-password", encoded)
    assert not verify_password("wrong-password", encoded)


def test_signed_approval_payload_detects_tampering_and_wrong_key(monkeypatch) -> None:
    payload = {
        "decision_id": "decision-1",
        "application_id": "application-1",
        "decision": "APPROVE",
        "reason": "Verified synthetic demo documents",
        "approver_id": "approver-1",
        "timestamp": "2026-10-26T00:00:00+00:00",
    }
    signature = sign_decision(payload)
    assert verify_decision_signature(payload, signature)
    assert not verify_decision_signature({**payload, "reason": "changed"}, signature)
    monkeypatch.setenv("APPROVAL_SIGNING_SECRET", "different-approval-key-with-32-characters")
    assert not verify_decision_signature(payload, signature)


def test_viewer_role_is_rejected_by_approver_dependency() -> None:
    viewer = User(id="viewer", email="viewer@example.com", password_hash="not-used", role="VIEWER")
    with pytest.raises(HTTPException) as raised:
        require_approver(viewer)
    assert raised.value.status_code == 403


def test_signed_record_detects_database_field_tampering() -> None:
    from types import SimpleNamespace

    decided_at = datetime(2026, 10, 26, tzinfo=timezone.utc)
    payload = decision_payload(
        "decision-1",
        "application-1",
        "APPROVE",
        "Synthetic documents reviewed",
        "approver-1",
        decided_at,
    )
    record = SimpleNamespace(
        id="decision-1",
        application_id="application-1",
        decision="APPROVE",
        reason="Synthetic documents reviewed",
        approver_id="approver-1",
        decided_at=decided_at,
        canonical_payload=payload,
        signature=sign_decision(payload),
    )
    assert verify_approval_record(record)
    record.reason = "Tampered decision reason"
    assert not verify_approval_record(record)


def test_jwt_contains_subject_and_expiration() -> None:
    import jwt

    approver = User(
        id="approver-id",
        email="approver@example.com",
        password_hash="not-used",
        role="APPROVER",
    )
    token = create_access_token(approver)
    claims = jwt.decode(
        token,
        os.environ["JWT_SECRET"],
        algorithms=["HS256"],
        options={"verify_exp": False},
    )
    assert claims["sub"] == "approver-id"
    assert claims["role"] == "APPROVER"
    assert "exp" in claims
