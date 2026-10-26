from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    email: str
    password: str


class UserView(BaseModel):
    id: str
    email: str
    role: str


class TokenView(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserView


class LoanCreate(BaseModel):
    applicant_name: str = Field(min_length=2, max_length=160)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    purpose: str = Field(min_length=3, max_length=500)

    @field_validator("applicant_name", "purpose")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class DecisionRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def reason_is_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("a non-empty decision reason is required")
        return stripped


class AlertUpdate(BaseModel):
    status: Literal["ACKNOWLEDGED", "RESOLVED"]


class ScenarioRequest(BaseModel):
    scenario: Literal["normal_auto_approval", "human_approval", "approval_bypass", "abnormal_duration", "unauthorized_resource_access"]


class Page(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class HealthView(BaseModel):
    status: str
    database: str


class ORMView(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class GenericObject(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    created_at: datetime | None = None
