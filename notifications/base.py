"""Notification backend contract.

Notification *delivery* status is deliberately kept separate from
*detection* status: a finding exists regardless of whether an alert was
delivered, and a publish attempt is never reported as confirmed delivery.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from governance.event_schema import utc_now
from governance.findings import Finding


class NotificationError(Exception):
    """Raised when a notification backend cannot accept a message."""


@dataclass(frozen=True)
class DeliveryResult:
    backend: str
    finding_id: str
    status: str  # SUCCESS | FAILED | SKIPPED
    detail: str
    attempts: int = 1
    timestamp: datetime = field(default_factory=utc_now)
    alert_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @classmethod
    def success(cls, backend: str, finding_id: str, detail: str, attempts: int = 1) -> "DeliveryResult":
        return cls(backend=backend, finding_id=finding_id, status="SUCCESS", detail=detail, attempts=attempts)

    @classmethod
    def failed(cls, backend: str, finding_id: str, detail: str, attempts: int = 1) -> "DeliveryResult":
        return cls(backend=backend, finding_id=finding_id, status="FAILED", detail=detail, attempts=attempts)

    @classmethod
    def skipped(cls, backend: str, finding_id: str, detail: str) -> "DeliveryResult":
        return cls(backend=backend, finding_id=finding_id, status="SKIPPED", detail=detail, attempts=0)


class Notifier(Protocol):
    name: str

    def send(self, finding: Finding) -> DeliveryResult: ...
