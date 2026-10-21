"""Shared fixtures and the generated-test-report collector.

The collector records, for every acceptance scenario, the actual outcome,
findings, alert deliveries, and detection latency measured during execution.
`reports/test_report.{json,md}` is written from real pytest results at the
end of the session — nothing is fabricated.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

from governance.clock import SimulatedClock
from governance.event_store import JsonlEventStore
from governance.findings import FindingStore
from governance.monitor import MonitorResult, MonitoringEngine
from governance.policy_loader import PolicyConfig, load_policy_config
from notifications import LocalNotifier

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "config" / "policies.yaml"
REPORT_JSON = REPO_ROOT / "reports" / "test_report.json"
REPORT_MD = REPO_ROOT / "reports" / "test_report.md"


@dataclass
class ScenarioRecord:
    test_id: str
    nodeid: str
    injected_violation: bool
    expect_open_findings: int
    open_findings: int
    pending_findings: int
    total_findings: int
    alerts: int
    alert_backends: list[str]
    latency_ms: float
    outcome: str = "FAILED"
    findings_summary: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ReportCollector:
    records: list[ScenarioRecord] = field(default_factory=list)
    test_outcomes: dict[str, str] = field(default_factory=dict)

    def add(self, record: ScenarioRecord) -> None:
        self.records.append(record)

    def finalize(self) -> None:
        for record in self.records:
            record.outcome = self.test_outcomes.get(record.nodeid, "UNKNOWN")

    def write(self) -> None:
        self.finalize()
        scenarios = len(self.records)
        passed = sum(1 for r in self.records if r.outcome == "passed")
        failed = scenarios - passed
        injected = [r for r in self.records if r.injected_violation]
        detected = [r for r in injected if r.open_findings > 0]
        false_positives = [
            r
            for r in self.records
            if not r.injected_violation and r.open_findings > r.expect_open_findings
        ]
        alerts_for_findings = sum(1 for r in self.records if r.total_findings > 0 and r.alerts > 0)
        findings_in_any = sum(1 for r in self.records if r.total_findings > 0)
        latencies = [r.latency_ms for r in self.records]
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "scenarios_executed": scenarios,
            "passed": passed,
            "failed": failed,
            "injected_violation_scenarios": len(injected),
            "injected_violations_detected": len(detected),
            "detection_rate": (
                f"{len(detected)}/{len(injected)}"
                if injected
                else "n/a (no injected-violation scenarios)"
            ),
            "false_positive_count": len(false_positives),
            "false_positive_scenarios": [r.test_id for r in false_positives],
            "findings_produced_in_scenarios": findings_in_any,
            "scenarios_with_findings_and_alerts": alerts_for_findings,
            "detection_latency_ms": {
                "min": min(latencies) if latencies else None,
                "max": max(latencies) if latencies else None,
                "mean": (
                    round(sum(latencies) / len(latencies), 3) if latencies else None
                ),
                "note": (
                    "wall-clock time for one monitor batch (read events + evaluate "
                    "detectors + persist findings + deliver alerts) within the test"
                ),
            },
            "scenarios": [vars(r) for r in self.records],
        }
        REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
        REPORT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        REPORT_MD.write_text(self._markdown(payload), encoding="utf-8")

    @staticmethod
    def _markdown(payload: dict[str, Any]) -> str:
        lines = [
            "# Test Report (generated from actual pytest execution)",
            "",
            f"- Generated at: {payload['generated_at']}",
            f"- Scenarios executed: {payload['scenarios_executed']}",
            f"- Passed: {payload['passed']}",
            f"- Failed: {payload['failed']}",
            f"- Injected-violation scenarios: {payload['injected_violation_scenarios']}",
            f"- Injected violations detected: {payload['injected_violations_detected']}",
            f"- Detection rate: {payload['detection_rate']}",
            f"- False positives (unexpected OPEN findings on normal scenarios): "
            f"{payload['false_positive_count']}"
            f" {payload['false_positive_scenarios']}",
            f"- Scenarios with findings that produced at least one alert: "
            f"{payload['scenarios_with_findings_and_alerts']}/"
            f"{payload['findings_produced_in_scenarios']}",
            f"- Detection latency (ms): {payload['detection_latency_ms']}",
            "",
            "| Scenario | Outcome | Injected | OPEN findings | Pending | Alerts | Latency (ms) |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in payload["scenarios"]:
            lines.append(
                f"| {r['test_id']} | {r['outcome']} | {r['injected_violation']} | "
                f"{r['open_findings']} | {r['pending_findings']} | {r['alerts']} | "
                f"{r['latency_ms']} |"
            )
        lines.append("")
        lines.append("## Findings detail")
        lines.append("")
        for r in payload["scenarios"]:
            if not r["findings_summary"]:
                continue
            lines.append(f"### {r['test_id']} ({r['nodeid']})")
            for f in r["findings_summary"]:
                lines.append(
                    f"- [{f['severity']}/{f['status']}] {f['rule_id']}: {f['observed_behaviour']}"
                )
            lines.append("")
        return "\n".join(lines) + "\n"


@pytest.fixture(scope="session")
def report_collector(request) -> ReportCollector:
    return request.config._report_collector


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    collector = getattr(item.config, "_report_collector", None)
    if collector is not None and report.when == "call":
        collector.test_outcomes[item.nodeid] = report.outcome


def pytest_configure(config):
    collector = ReportCollector()
    config._report_collector = collector


def pytest_sessionfinish(session, exitstatus):
    collector = session.config._report_collector
    if collector.records:
        collector.write()


@pytest.fixture(scope="session")
def policy() -> PolicyConfig:
    return load_policy_config(POLICY_PATH)


@pytest.fixture
def clock() -> SimulatedClock:
    return SimulatedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))


@pytest.fixture
def event_store(tmp_path):
    def _make(run_id: str = "test-run", name: str = "events.jsonl") -> JsonlEventStore:
        return JsonlEventStore(tmp_path / name, run_id=run_id)

    return _make


@pytest.fixture
def make_engine(tmp_path, policy, clock, report_collector):
    """Build a MonitoringEngine with a local notifier; returns a callable."""

    def _make(name: str = "engine") -> tuple[MonitoringEngine, Path, LocalNotifier]:
        finding_store = FindingStore(tmp_path / f"{name}-findings.jsonl")
        alerts_path = tmp_path / f"{name}-alerts.jsonl"
        notifier = LocalNotifier(alerts_path, echo=False)
        engine = MonitoringEngine(
            policy, finding_store, notifiers=[notifier], clock=clock
        )
        return engine, alerts_path, notifier

    return _make


@pytest.fixture
def node_id(request) -> str:
    return request.node.nodeid


@pytest.fixture
def record_scenario(report_collector, node_id):
    """Callable used by scenario tests to record real results for the report."""

    def _record(
        test_id: str,
        injected_violation: bool,
        result: MonitorResult,
        latency_ms: float,
        expect_open_findings: int = 0,
    ) -> None:
        open_findings = [f for f in result.new_findings if f.status.value == "OPEN"]
        pending = [f for f in result.new_findings if f.status.value == "PENDING_INVESTIGATION"]
        report_collector.add(
            ScenarioRecord(
                test_id=test_id,
                nodeid=node_id,
                injected_violation=injected_violation,
                expect_open_findings=expect_open_findings,
                open_findings=len(open_findings),
                pending_findings=len(pending),
                total_findings=len(result.new_findings),
                alerts=len(result.deliveries),
                alert_backends=sorted({d.backend for d in result.deliveries}),
                latency_ms=round(latency_ms, 3),
                findings_summary=[
                    {
                        "rule_id": f.rule_id,
                        "severity": f.severity.value,
                        "status": f.status.value,
                        "observed_behaviour": f.observed_behaviour,
                    }
                    for f in result.new_findings
                ],
            )
        )

    return _record


@pytest.fixture
def timed_process():
    def _process(engine: MonitoringEngine, store: JsonlEventStore, now) -> tuple[MonitorResult, float]:
        start = time.perf_counter()
        result = engine.process_store(store, now=now)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return result, latency_ms

    return _process
