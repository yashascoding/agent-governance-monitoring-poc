"""Audit report generation from findings and alert-delivery records.

Produces a Markdown audit report combining the raw findings, the alerts that
were emitted, and delivery outcomes (kept separate from detection status).
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from governance.findings import Finding, FindingStore


def build_audit_report(
    title: str,
    findings_path: str | Path,
    alerts_path: str | Path | None = None,
) -> str:
    findings = FindingStore(findings_path).load_all()
    alerts = _load_jsonl(alerts_path) if alerts_path else []
    delivery_by_finding: dict[str, list[str]] = {}
    for record in alerts:
        finding = record.get("finding", {})
        delivery = record.get("delivery", {})
        delivery_by_finding.setdefault(finding.get("finding_id", "?"), []).append(
            f"{delivery.get('backend')}:{delivery.get('status')}"
        )

    by_severity = Counter(f.severity.value for f in findings)
    by_status = Counter(f.status.value for f in findings)
    by_rule = Counter(f.rule_id for f in findings)

    lines: list[str] = [
        f"# Audit Report: {title}",
        "",
        f"- Generated at: {_now()}",
        f"- Findings total: {len(findings)}",
        f"- By severity: {dict(by_severity)}",
        f"- By status: {dict(by_status)}",
        f"- By rule: {dict(by_rule)}",
        f"- Alert records: {len(alerts)}",
        "",
        "## Findings",
        "",
    ]
    if not findings:
        lines.append("_No findings recorded._")
    for finding in sorted(findings, key=lambda f: (f.severity.value, f.detected_at)):
        deliveries = ", ".join(delivery_by_finding.get(finding.finding_id, [])) or "none"
        lines.extend(_finding_block(finding, deliveries))
    return "\n".join(lines) + "\n"


def _finding_block(finding: Finding, deliveries: str) -> list[str]:
    return [
        f"### [{finding.severity.value}/{finding.status.value}] {finding.rule_id}",
        "",
        f"- Finding ID: `{finding.finding_id}`",
        f"- Agent / task: `{finding.agent_id}` / `{finding.task_id}`",
        f"- Detected at: {finding.detected_at.isoformat()}",
        f"- Expected: {finding.expected_behaviour}",
        f"- Observed: {finding.observed_behaviour}",
        f"- Supporting events: {', '.join(finding.supporting_event_ids)}",
        f"- Explanation: {finding.explanation}",
        f"- Recommended response: {finding.recommended_response}",
        f"- Alert delivery (detection is independent of delivery): {deliveries}",
        "",
    ]


def _load_jsonl(path: str | Path) -> Iterable[dict]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    records = []
    for raw in file_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return records


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
