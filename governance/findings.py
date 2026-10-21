"""Policy violation findings produced by the independent monitoring engine.

Findings are distinct from raw events and from alert delivery records.
Duplicate suppression uses a deterministic content hash (rule + agent +
task + status + evidence signature), so reprocessing the same events does
not create duplicate findings or duplicate alerts.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from governance.event_schema import to_utc_iso, parse_utc_iso


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    PENDING_INVESTIGATION = "PENDING_INVESTIGATION"


class FindingStoreError(Exception):
    """Raised when the finding store cannot be read or written."""


@dataclass(frozen=True)
class Finding:
    rule_id: str
    agent_id: str
    task_id: str
    severity: Severity
    status: FindingStatus
    detected_at: datetime
    expected_behaviour: str
    observed_behaviour: str
    supporting_event_ids: list[str]
    explanation: str
    recommended_response: str
    key_evidence: dict[str, Any] = field(default_factory=dict)
    finding_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        if not self.supporting_event_ids:
            raise ValueError("a finding must cite at least one supporting event")
        if self.detected_at.tzinfo is None or self.detected_at.utcoffset() is None:
            raise ValueError("detected_at must be timezone-aware (UTC)")

    @property
    def finding_key(self) -> str:
        """Deterministic identity used for duplicate suppression."""
        signature = json.dumps(self.key_evidence, sort_keys=True, default=str)
        payload = "|".join(
            [
                self.rule_id,
                self.agent_id,
                self.task_id,
                self.status.value,
                signature,
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "finding_key": self.finding_key,
            "rule_id": self.rule_id,
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "severity": self.severity.value,
            "status": self.status.value,
            "detected_at": to_utc_iso(self.detected_at),
            "expected_behaviour": self.expected_behaviour,
            "observed_behaviour": self.observed_behaviour,
            "supporting_event_ids": list(self.supporting_event_ids),
            "explanation": self.explanation,
            "recommended_response": self.recommended_response,
            "key_evidence": dict(self.key_evidence),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Finding":
        return cls(
            finding_id=str(payload["finding_id"]),
            rule_id=str(payload["rule_id"]),
            agent_id=str(payload["agent_id"]),
            task_id=str(payload["task_id"]),
            severity=Severity(payload["severity"]),
            status=FindingStatus(payload["status"]),
            detected_at=parse_utc_iso(payload["detected_at"]),
            expected_behaviour=str(payload["expected_behaviour"]),
            observed_behaviour=str(payload["observed_behaviour"]),
            supporting_event_ids=[str(item) for item in payload["supporting_event_ids"]],
            explanation=str(payload["explanation"]),
            recommended_response=str(payload["recommended_response"]),
            key_evidence=dict(payload.get("key_evidence", {})),
        )


class FindingStore:
    """Append-only JSONL store for findings; used for dedupe across runs."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, finding: Finding) -> None:
        line = json.dumps(finding.to_dict(), sort_keys=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()

    def load_all(self) -> list[Finding]:
        findings: list[Finding] = []
        text = self.path.read_text(encoding="utf-8")
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                findings.append(Finding.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                raise FindingStoreError(
                    f"corrupt finding record in {self.path}: {exc}"
                ) from exc
        return findings

    def known_keys(self) -> set[str]:
        return {finding.finding_key for finding in self.load_all()}
