"""Independent monitoring engine.

Reads the structured event log and evaluates events against the centralized
policies via deterministic detectors. The engine never trusts a task agent's
self-reported conclusion: it recomputes amounts against thresholds, checks
authorization state, corroborates durations with timestamps, and validates
permission mappings itself.

Duplicate handling: each finding has a deterministic content key; findings
whose key already exists (in the persistent finding store or earlier in the
same batch) are suppressed, and alerts are only emitted for new findings.
This makes repeated processing of the same event file idempotent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

from governance.clock import Clock, SystemClock
from governance.detectors import Detector, default_detectors
from governance.event_schema import Event
from governance.event_store import JsonlEventStore, ReadReport
from governance.findings import Finding, FindingStore
from governance.policy_loader import PolicyConfig
from notifications.base import DeliveryResult, Notifier

logger = logging.getLogger(__name__)


@dataclass
class MonitorResult:
    processed_events: int = 0
    read_report: ReadReport | None = None
    new_findings: list[Finding] = field(default_factory=list)
    suppressed_duplicates: list[Finding] = field(default_factory=list)
    deliveries: list[DeliveryResult] = field(default_factory=list)


class MonitoringEngine:
    def __init__(
        self,
        policy: PolicyConfig,
        finding_store: FindingStore,
        notifiers: Sequence[Notifier] = (),
        detectors: Sequence[Detector] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.policy = policy
        self.finding_store = finding_store
        self.notifiers = {notifier.name: notifier for notifier in notifiers}
        self.detectors = list(detectors) if detectors is not None else default_detectors()
        self.clock = clock or SystemClock()

    def process_store(self, store: JsonlEventStore, now: datetime | None = None) -> MonitorResult:
        read_result = store.read_all()
        result = self.process_events(read_result.events, now=now)
        result.read_report = read_result.report
        return result

    def process_events(self, events: Sequence[Event], now: datetime | None = None) -> MonitorResult:
        reference_time = now or self.clock.now()
        result = MonitorResult(processed_events=len(events))
        known_keys = self.finding_store.known_keys()
        batch_keys: set[str] = set()
        for detector in self.detectors:
            try:
                candidates = detector.detect(events, self.policy, reference_time)
            except Exception:
                logger.exception("detector %s failed; continuing", detector.rule_id)
                continue
            for finding in candidates:
                key = finding.finding_key
                if key in known_keys or key in batch_keys:
                    result.suppressed_duplicates.append(finding)
                    continue
                batch_keys.add(key)
                known_keys.add(key)
                self.finding_store.append(finding)
                result.new_findings.append(finding)
                logger.info(
                    "finding %s [%s] rule=%s agent=%s task=%s",
                    finding.finding_id,
                    finding.severity.value,
                    finding.rule_id,
                    finding.agent_id,
                    finding.task_id,
                )
        for finding in result.new_findings:
            result.deliveries.extend(self._alert(finding))
        return result

    def _alert(self, finding: Finding) -> list[DeliveryResult]:
        backends = self.policy.alert_policy.routing.get(finding.severity.value, ["local"])
        results: list[DeliveryResult] = []
        for backend_name in backends:
            notifier = self.notifiers.get(backend_name)
            if notifier is None:
                logger.debug(
                    "no notifier registered for backend %s; skipping alert", backend_name
                )
                continue
            try:
                results.append(notifier.send(finding))
            except Exception as exc:  # a notifier must never break monitoring
                logger.exception("notifier %s raised", backend_name)
                results.append(
                    DeliveryResult.failed(
                        backend=backend_name,
                        finding_id=finding.finding_id,
                        detail=f"notifier raised unexpectedly: {exc}",
                    )
                )
        return results
