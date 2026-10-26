from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApprovalDecision, User

password_hasher = PasswordHasher()
bearer = HTTPBearer(auto_error=False)


def _required_secret(name: str, minimum_length: int = 32) -> str:
    value = os.getenv(name, "")
    if len(value) < minimum_length:
        raise RuntimeError(f"{name} must be configured with at least {minimum_length} characters")
    return value


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return password_hasher.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    expiry_minutes = int(os.getenv("JWT_EXPIRY_MINUTES", "30"))
    if expiry_minutes < 1:
        raise RuntimeError("JWT_EXPIRY_MINUTES must be greater than zero")
    claims = {
        "sub": user.id,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=expiry_minutes),
    }
    return jwt.encode(claims, _required_secret("JWT_SECRET"), algorithm="HS256")


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_decision(payload: dict[str, Any]) -> str:
    key = _required_secret("APPROVAL_SIGNING_SECRET")
    return hmac.new(key.encode(), canonical_json(payload).encode(), hashlib.sha256).hexdigest()


def verify_decision_signature(payload: dict[str, Any], signature: str) -> bool:
    return hmac.compare_digest(sign_decision(payload), signature)


def decision_payload(
    decision_id: str,
    application_id: str,
    decision: str,
    reason: str,
    approver_id: str,
    decided_at: datetime,
) -> dict[str, Any]:
    return {
        "decision_id": decision_id,
        "application_id": application_id,
        "decision": decision,
        "reason": reason,
        "approver_id": approver_id,
        "timestamp": decided_at.isoformat(),
    }


def verify_approval_record(record: ApprovalDecision) -> bool:
    expected = decision_payload(
        decision_id=record.id,
        application_id=record.application_id,
        decision=record.decision,
        reason=record.reason,
        approver_id=record.approver_id,
        decided_at=record.decided_at,
    )
    return (
        record.canonical_payload == expected
        and verify_decision_signature(expected, record.signature)
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        claims = jwt.decode(
            credentials.credentials,
            _required_secret("JWT_SECRET"),
            algorithms=["HS256"],
            options={"require": ["sub", "exp"]},
        )
    except (jwt.InvalidTokenError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc
    user = db.scalar(select(User).where(User.id == claims.get("sub")))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
    return user


def require_approver(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != "APPROVER":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Approver role required")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
ApproverUser = Annotated[User, Depends(require_approver)]
