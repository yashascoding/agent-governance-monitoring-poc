"""Unit tests for policy configuration loading and validation (T11 partial)."""

from __future__ import annotations

from pathlib import Path

import pytest

from governance.policy_loader import PolicyConfigError, load_policy_config

VALID_YAML = """
version: 1
loan_policy:
  id: POL-LOAN-001
  currency: INR
  auto_approval_max_exclusive: 1000
  human_approval_required_at: 1000
task_policy:
  id: POL-TASK-001
  baseline_duration_seconds: 300
  anomaly_ratio: 0.2
  anomaly_min_duration_seconds: 60
data_policy:
  id: POL-DATA-001
  permissions:
    loan-agent: [loan_applications]
monitoring:
  id: POL-MON-001
  workflow_deadline_seconds: 600
alerts:
  id: POL-ALERT-001
  severities: [CRITICAL, HIGH, MEDIUM, LOW]
  routing:
    CRITICAL: [local]
    HIGH: [local]
    MEDIUM: [local]
    LOW: [local]
"""


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "policies.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_valid_config_loads(tmp_path: Path) -> None:
    config = load_policy_config(_write(tmp_path, VALID_YAML))
    assert config.loan_policy.requires_human_approval(1000)
    assert not config.loan_policy.requires_human_approval(999.99)
    assert config.loan_policy.may_auto_approve(800)
    assert config.task_policy.is_short_duration_anomaly(10)
    assert not config.task_policy.is_short_duration_anomaly(300)
    assert config.data_policy.is_allowed("loan-agent", "loan_applications")
    assert not config.data_policy.is_allowed("data-agent", "loan_applications")


def test_shipped_config_is_valid(policy) -> None:
    assert policy.loan_policy.human_approval_required_at == 1000
    assert policy.data_policy.is_allowed("data-agent", "public_test_data")


def test_missing_file_fails_safely(tmp_path: Path) -> None:
    with pytest.raises(PolicyConfigError, match="not found"):
        load_policy_config(tmp_path / "missing.yaml")


def test_invalid_yaml_fails_safely(tmp_path: Path) -> None:
    with pytest.raises(PolicyConfigError, match="not valid YAML"):
        load_policy_config(_write(tmp_path, "version: [unclosed"))


def test_missing_section_fails_safely(tmp_path: Path) -> None:
    broken = VALID_YAML.replace("loan_policy:", "other_policy:")
    with pytest.raises(PolicyConfigError, match="loan_policy"):
        load_policy_config(_write(tmp_path, broken))


def test_wrong_type_fails_safely(tmp_path: Path) -> None:
    broken = VALID_YAML.replace("baseline_duration_seconds: 300", "baseline_duration_seconds: fast")
    with pytest.raises(PolicyConfigError, match="baseline_duration_seconds"):
        load_policy_config(_write(tmp_path, broken))


def test_threshold_mismatch_fails_safely(tmp_path: Path) -> None:
    broken = VALID_YAML.replace("human_approval_required_at: 1000", "human_approval_required_at: 500")
    with pytest.raises(PolicyConfigError, match="unambiguous"):
        load_policy_config(_write(tmp_path, broken))


def test_invalid_routing_fails_safely(tmp_path: Path) -> None:
    broken = VALID_YAML.replace("    CRITICAL: [local]\n", "")
    with pytest.raises(PolicyConfigError, match="routing"):
        load_policy_config(_write(tmp_path, broken))
