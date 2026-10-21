"""Integration tests for the demo scenarios and the live watch mode."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import main
from demo import build_context, live_workload_steps, run_deadline_demo
from governance.clock import SystemClock
from governance.event_store import JsonlEventStore
from governance.policy_loader import load_policy_config

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "config" / "policies.yaml"


class TestDeadlineDemo:
    def test_stalled_workflow_is_pending_before_the_deadline_and_critical_after(
        self, tmp_path, policy
    ):
        ctx = build_context(tmp_path / "deadline", policy)
        result = run_deadline_demo(ctx)

        pending = [
            f for f in result.new_findings if f.status.value == "PENDING_INVESTIGATION"
        ]
        escalated = [
            f for f in result.new_findings if f.severity.value == "CRITICAL"
        ]

        assert len(pending) == 1, "an in-flight workflow must not be accused"
        assert pending[0].severity.value == "LOW"
        assert len(escalated) == 1, "an expired workflow must escalate"
        assert escalated[0].status.value == "OPEN"

    def test_both_findings_refer_to_the_same_workflow(self, tmp_path, policy):
        ctx = build_context(tmp_path / "deadline", policy)
        result = run_deadline_demo(ctx)
        assert {f.task_id for f in result.new_findings} == {"loan-stalled"}

    def test_pending_finding_is_never_reported_as_a_violation(self, tmp_path, policy):
        ctx = build_context(tmp_path / "deadline", policy)
        result = run_deadline_demo(ctx)
        open_findings = [f for f in result.new_findings if f.status.value == "OPEN"]
        assert all(f.severity.value == "CRITICAL" for f in open_findings)


class TestDemoExpectations:
    def test_normal_demo_produces_no_open_findings(self, tmp_path, policy):
        ctx = build_context(tmp_path / "normal", policy)
        from demo import run_normal_demo

        result = run_normal_demo(ctx)
        assert main._check_demo_expectations("normal", result) == 0

    def test_faulty_demo_produces_findings(self, tmp_path, policy):
        from demo import run_faulty_demo

        ctx = build_context(tmp_path / "faulty", policy)
        result = run_faulty_demo(ctx)
        assert main._check_demo_expectations("faulty", result) == 0

    def test_deadline_demo_satisfies_its_own_expectations(self, tmp_path, policy):
        ctx = build_context(tmp_path / "deadline", policy)
        result = run_deadline_demo(ctx)
        assert main._check_demo_expectations("deadline", result) == 0


class TestLiveWorkload:
    def test_workload_covers_compliant_and_violating_behaviour(self, tmp_path, policy):
        store = JsonlEventStore(tmp_path / "events.jsonl", run_id="test-run")
        steps = live_workload_steps(policy, store, SystemClock())
        labels = " ".join(label for label, _ in steps).lower()
        assert "compliant" in labels
        assert "violation" in labels
        assert "blocked" in labels

    def test_workload_emits_no_findings_for_compliant_steps_only(self, tmp_path, policy):
        store = JsonlEventStore(tmp_path / "events.jsonl", run_id="test-run")
        steps = live_workload_steps(policy, store, SystemClock())
        for label, action in steps:
            if not label.startswith("compliant"):
                continue
            action()
        from governance.findings import FindingStore
        from governance.monitor import MonitoringEngine

        finding_store = FindingStore(tmp_path / "findings.jsonl")
        engine = MonitoringEngine(policy, finding_store, clock=SystemClock())
        outcome = engine.process_store(store)
        assert outcome.new_findings == [], "compliant steps must not raise findings"


class TestWatchMode:
    def test_watch_mode_runs_end_to_end_and_writes_artefacts(self, tmp_path, capsys):
        args = argparse.Namespace(
            policy=POLICY_PATH,
            out=tmp_path / "watch",
            pace=0.05,
            interval=0.05,
            quiet=0.05,
            no_color=True,
        )
        exit_code = main.cmd_watch(args)
        captured = capsys.readouterr()

        assert exit_code == 0
        assert (tmp_path / "watch" / "events.jsonl").exists()
        assert (tmp_path / "watch" / "findings.jsonl").exists()
        assert (tmp_path / "watch" / "alerts.jsonl").exists()

        findings = [
            json.loads(line)
            for line in (tmp_path / "watch" / "findings.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        rules = {finding["rule_id"] for finding in findings}
        assert "RULE-LOAN-002" in rules
        assert "RULE-DATA-002" in rules

    def test_watch_mode_raises_no_finding_for_compliant_workflows(self, tmp_path, capsys):
        args = argparse.Namespace(
            policy=POLICY_PATH,
            out=tmp_path / "watch",
            pace=0.05,
            interval=0.05,
            quiet=0.05,
            no_color=True,
        )
        main.cmd_watch(args)
        capsys.readouterr()

        findings = [
            json.loads(line)
            for line in (tmp_path / "watch" / "findings.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        affected = {finding["task_id"] for finding in findings}
        assert "loan-small" not in affected
        assert "loan-large" not in affected
        assert "task-normal" not in affected


class TestPolicyFixtureSanity:
    def test_policy_file_loads(self):
        policy = load_policy_config(POLICY_PATH)
        assert policy.version == 1
