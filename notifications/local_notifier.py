"""Local alert backend: JSONL alert file + concise terminal output.

Works fully offline with no AWS credentials or network access.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import console
from governance.event_schema import to_utc_iso
from notifications.base import DeliveryResult
from governance.findings import Finding


@dataclass
class LocalNotifier:
    alerts_path: str | Path
    echo: bool = True
    name: str = "local"
    color: bool | None = None

    def __post_init__(self) -> None:
        self.alerts_path = Path(self.alerts_path)
        if self.color is None:
            self.color = console.supports_color(sys.stderr)
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

    def _print(self, finding: Finding) -> None:
        color = bool(self.color)
        label = console.severity(f"[{finding.severity.value}]", enabled=color)
        rule = console.bold(finding.rule_id, enabled=color)
        meta = console.dim(
            f"agent={finding.agent_id}  task={finding.task_id}  "
            f"status={finding.status.value}  at={to_utc_iso(finding.detected_at)}",
            enabled=color,
        )
        observed = console.dim("observed ", enabled=color)
        response = console.dim("response ", enabled=color)
        print(f"{label} {rule}  {meta}", file=sys.stderr)
        print(f"    {observed} {finding.observed_behaviour}", file=sys.stderr)
        print(f"    {response} {finding.recommended_response}", file=sys.stderr)
        print("", file=sys.stderr)
