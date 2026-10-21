"""T11: malformed events and invalid policy configuration are handled safely.

The system must not crash and must surface explicit errors: malformed event
records are skipped and reported, invalid policy configuration raises a clear
PolicyConfigError at startup.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from governance.findings import FindingStore
from governance.monitor import MonitoringEngine
from governance.policy_loader import PolicyConfigError, load_policy_config

UTC = timezone.utc

BROKEN_CONFIGS = {
    "missing_yaml_file": None,
    "not_yaml": "loan_policy: [unclosed",
    "missing_threshold": """
version: 1
loan_policy:
  id: POL-LOAN-001
  currency: INR
  auto_approval_max_exclusive: 1000
task_policy: {id: x, baseline_duration_seconds: 300, anomaly_ratio: 0.2, anomaly_min_duration_seconds: 60}
data_policy: {id: x, permissions: {a: [b]}}
monitoring: {id: x, workflow_deadline_seconds: 600}
alerts: {id: x, severities: [LOW], routing: {LOW: [local]}}
""",
    "bad_routing": """
version: 1
loan_policy: {id: a, currency: INR, auto_approval_max_exclusive: 1000, human_approval_required_at: 1000}
task_policy: {id: a, baseline_duration_seconds: 300, anomaly_ratio: 0.2, anomaly_min_duration_seconds: 60}
data_policy: {id: a, permissions: {a: [b]}}
monitoring: {id: a, workflow_deadline_seconds: 600}
alerts: {id: a, severities: [LOW], routing: {}}
""",
}


@pytest.mark.parametrize("name,content", list(BROKEN_CONFIGS.items()))
def test_invalid_policy_config_fails_explicitly(tmp_path, name, content) -> None:
    if content is None:
        path = tmp_path / "does-not-exist.yaml"
    else:
        path = tmp_path / f"{name}.yaml"
        path.write_text(content, encoding="utf-8")
    with pytest.raises(PolicyConfigError):
        load_policy_config(path)


def test_malformed_events_skipped_and_monitoring_survives(
    make_engine, policy, clock, event_store, timed_process, record_scenario
) -> None:
    engine, _, _ = make_engine("t11")
    store = event_store()
    store.append(_valid_loan_event(clock.now()))
    with store.path.open("a", encoding="utf-8") as handle:
        handle.write("{ this is not json\n")
        handle.write(json.dumps({"event_id": "x"}) + "\n")  # missing required fields
        handle.write("\n")  # blank line

    result, latency = timed_process(engine, store, clock.now())
    record_scenario("T11", False, result, latency)
    assert result.read_report.malformed_records == 2
    assert result.read_report.errors
    assert isinstance(result.new_findings, list)  # monitoring did not crash


def _valid_loan_event(now):
    from governance.event_schema import Event, EventType

    return Event(
        event_type=EventType.LOAN_REQUESTED,
        agent_id="loan-agent",
        run_id="r",
        task_id="t11",
        timestamp=now,
        evidence={"amount": 800},
    )
