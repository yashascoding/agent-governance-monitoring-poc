"""Tests for terminal styling helpers and the colored local alert output."""

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone

import console
from governance.findings import Finding, FindingStatus, Severity
from notifications.local_notifier import LocalNotifier

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _finding(severity: Severity = Severity.CRITICAL) -> Finding:
    return Finding(
        rule_id="RULE-LOAN-001",
        agent_id="loan-agent",
        task_id="loan-bypass",
        severity=severity,
        status=FindingStatus.OPEN,
        detected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        expected_behaviour="expected",
        observed_behaviour="observed",
        supporting_event_ids=["event-1"],
        explanation="explanation",
        recommended_response="response",
        key_evidence={"amount": 1500.0},
    )


class TestSupportsColor:
    def test_non_tty_stream_is_not_colored(self):
        assert console.supports_color(io.StringIO()) is False

    def test_tty_stream_is_colored(self):
        stream = io.StringIO()
        stream.isatty = lambda: True  # type: ignore[method-assign]
        assert console.supports_color(stream) is True

    def test_no_color_environment_variable_disables_color(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        stream = io.StringIO()
        stream.isatty = lambda: True  # type: ignore[method-assign]
        assert console.supports_color(stream) is False

    def test_force_color_environment_variable_enables_color(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("FORCE_COLOR", "1")
        assert console.supports_color(io.StringIO()) is True


class TestStyling:
    def test_style_wraps_text_when_enabled(self):
        assert console.style("x", console.RED, enabled=True) == f"{console.RED}x{console.RESET}"

    def test_style_is_a_noop_when_disabled(self):
        assert console.style("x", console.RED, enabled=False) == "x"

    def test_severity_uses_a_distinct_color_per_level(self):
        colors = {
            console.severity_color(level)
            for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
        }
        assert len(colors) == 4

    def test_severity_falls_back_for_unknown_level(self):
        assert console.severity_color("WEIRD") == console.WHITE

    def test_strip_ansi_removes_escape_sequences(self):
        colored = console.style("hello", console.BOLD + console.RED, enabled=True)
        assert console.strip_ansi(colored) == "hello"

    def test_strip_ansi_leaves_plain_text_untouched(self):
        assert console.strip_ansi("plain text") == "plain text"


class TestLocalNotifierOutput:
    def test_alert_file_never_contains_ansi_sequences(self, tmp_path):
        alerts = tmp_path / "alerts.jsonl"
        notifier = LocalNotifier(alerts, echo=False, color=True)
        notifier.send(_finding())
        raw = alerts.read_text(encoding="utf-8")
        assert not ANSI_RE.search(raw)
        record = json.loads(raw.strip())
        assert record["finding"]["rule_id"] == "RULE-LOAN-001"
        assert record["delivery"]["status"] == "SUCCESS"

    def test_colored_echo_contains_ansi_sequences(self, tmp_path, capsys):
        notifier = LocalNotifier(tmp_path / "alerts.jsonl", echo=True, color=True)
        notifier.send(_finding())
        captured = capsys.readouterr()
        assert ANSI_RE.search(captured.err)

    def test_plain_echo_contains_no_ansi_sequences(self, tmp_path, capsys):
        notifier = LocalNotifier(tmp_path / "alerts.jsonl", echo=True, color=False)
        notifier.send(_finding())
        captured = capsys.readouterr()
        assert not ANSI_RE.search(captured.err)
        assert "RULE-LOAN-001" in captured.err
        assert "CRITICAL" in captured.err

    def test_echo_includes_observed_and_recommended_response(self, tmp_path, capsys):
        notifier = LocalNotifier(tmp_path / "alerts.jsonl", echo=True, color=False)
        notifier.send(_finding())
        captured = capsys.readouterr()
        assert "observed" in captured.err
        assert "response" in captured.err
        assert "response" in captured.err
