from __future__ import annotations

import os

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User
from app.security import hash_password


def seed() -> None:
    accounts = [
        (
            os.getenv("SEED_APPROVER_EMAIL", "approver@example.com").strip().lower(),
            os.getenv("SEED_APPROVER_PASSWORD", ""),
            "APPROVER",
        ),
        (
            os.getenv("SEED_VIEWER_EMAIL", "viewer@example.com").strip().lower(),
            os.getenv("SEED_VIEWER_PASSWORD", ""),
            "VIEWER",
        ),
    ]
    if any(len(password) < 12 for _, password, _ in accounts):
        raise RuntimeError(
            "Set SEED_APPROVER_PASSWORD and SEED_VIEWER_PASSWORD to at least 12 characters before seeding"
        )
    with SessionLocal.begin() as db:
        for email, password, role in accounts:
            existing = db.scalar(select(User).where(User.email == email))
            if existing is None:
                db.add(User(email=email, password_hash=hash_password(password), role=role))
            elif existing.role != role:
                raise RuntimeError(f"refusing to change existing account role for {email}")


if __name__ == "__main__":
    seed()
