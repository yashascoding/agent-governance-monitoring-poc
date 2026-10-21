"""Local alert backend: JSONL alert file + concise terminal output.

Works fully offline with no AWS credentials or network access.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from governance.event_schema import to_utc_iso
from notifications.base import DeliveryResult
from governance.findings import Finding


@dataclass
class LocalNotifier:
    alerts_path: str | Path
    echo: bool = True
    name: str = "local"

    def __post_init__(self) -> None:
        self.alerts_path = Path(self.alerts_path)
        try:
            if not self.alerts_path.parent.is_dir():
                self.alerts_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass  # send() will report the failure as a DeliveryResult

    def send(self, finding: Finding) -> DeliveryResult:
        record = {
            "alert_type": "policy_violation_finding",
            "finding": finding.to_dict(),
            "delivery": {
                "backend": self.name,
                "status": "SUCCESS",
                "detail": "written to local alert log and echoed to terminal",
            },
        }
        line = json.dumps(record, sort_keys=True)
        try:
            with self.alerts_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
        except OSError as exc:
            return DeliveryResult.failed(
                backend=self.name,
                finding_id=finding.finding_id,
                detail=f"failed to write alert file: {exc}",
            )
        if self.echo:
            self._print(finding)
        return DeliveryResult.success(
            backend=self.name,
            finding_id=finding.finding_id,
            detail=f"alert written to {self.alerts_path}",
        )

    @staticmethod
    def _print(finding: Finding) -> None:
        summary = (
            f"[ALERT][{finding.severity.value}] {finding.rule_id} "
            f"agent={finding.agent_id} task={finding.task_id} "
            f"status={finding.status.value} at={to_utc_iso(finding.detected_at)}\n"
            f"    {finding.observed_behaviour}\n"
            f"    -> {finding.recommended_response}"
        )
        print(summary, file=sys.stderr)
