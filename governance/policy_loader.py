"""Loading and validation of the centralized policy configuration.

Agents and the monitor both consume this configuration; nothing is hardcoded
in individual agents. Missing or invalid configuration fails safely with an
explicit error at startup rather than falling back to permissive defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class PolicyConfigError(Exception):
    """Raised when the policy configuration is missing or invalid."""


@dataclass(frozen=True)
class LoanPolicy:
    policy_id: str
    currency: str
    auto_approval_max_exclusive: float
    human_approval_required_at: float

    def requires_human_approval(self, amount: float) -> bool:
        return amount >= self.human_approval_required_at

    def may_auto_approve(self, amount: float) -> bool:
        return amount < self.auto_approval_max_exclusive


@dataclass(frozen=True)
class TaskPolicy:
    policy_id: str
    baseline_duration_seconds: float
    anomaly_ratio: float
    anomaly_min_duration_seconds: float

    def is_short_duration_anomaly(self, duration_seconds: float) -> bool:
        return duration_seconds < self.anomaly_min_duration_seconds


@dataclass(frozen=True)
class DataPolicy:
    policy_id: str
    permissions: dict[str, list[str]]

    def allowed_resources(self, agent_id: str) -> list[str]:
        return list(self.permissions.get(agent_id, []))

    def is_allowed(self, agent_id: str, resource: str) -> bool:
        return resource in self.permissions.get(agent_id, [])


@dataclass(frozen=True)
class MonitoringPolicy:
    policy_id: str
    workflow_deadline_seconds: float
    escalate_expired_incomplete_workflows: bool = True


@dataclass(frozen=True)
class AlertPolicy:
    policy_id: str
    severities: list[str]
    routing: dict[str, list[str]]


@dataclass(frozen=True)
class PolicyConfig:
    version: int
    loan_policy: LoanPolicy
    task_policy: TaskPolicy
    data_policy: DataPolicy
    monitoring_policy: MonitoringPolicy
    alert_policy: AlertPolicy
    source_path: str = field(default="<unknown>")


def load_policy_config(path: str | Path) -> PolicyConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise PolicyConfigError(f"policy configuration not found: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PolicyConfigError(f"policy configuration is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise PolicyConfigError("policy configuration root must be a mapping")

    version = _require_int(raw, "version", minimum=1)
    loan = _parse_loan_policy(_require_section(raw, "loan_policy"))
    task = _parse_task_policy(_require_section(raw, "task_policy"))
    data = _parse_data_policy(_require_section(raw, "data_policy"))
    monitoring = _parse_monitoring_policy(_require_section(raw, "monitoring"))
    alerts = _parse_alert_policy(_require_section(raw, "alerts"))

    if loan.auto_approval_max_exclusive != loan.human_approval_required_at:
        raise PolicyConfigError(
            "loan_policy.auto_approval_max_exclusive must equal "
            "loan_policy.human_approval_required_at so the threshold is unambiguous"
        )
    if task.anomaly_min_duration_seconds >= task.baseline_duration_seconds:
        raise PolicyConfigError(
            "task_policy.anomaly_min_duration_seconds must be below the baseline"
        )
    if not 0 < task.anomaly_ratio < 1:
        raise PolicyConfigError("task_policy.anomaly_ratio must be between 0 and 1")

    return PolicyConfig(
        version=version,
        loan_policy=loan,
        task_policy=task,
        data_policy=data,
        monitoring_policy=monitoring,
        alert_policy=alerts,
        source_path=str(config_path),
    )


def _require_section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    section = raw.get(key)
    if not isinstance(section, dict):
        raise PolicyConfigError(f"missing or invalid required section: {key}")
    return section


def _require(section: dict[str, Any], key: str, section_name: str) -> Any:
    if key not in section:
        raise PolicyConfigError(f"{section_name}.{key} is required")
    return section[key]


def _require_str(section: dict[str, Any], key: str, section_name: str) -> str:
    value = _require(section, key, section_name)
    if not isinstance(value, str) or not value.strip():
        raise PolicyConfigError(f"{section_name}.{key} must be a non-empty string")
    return value


def _require_number(section: dict[str, Any], key: str, section_name: str) -> float:
    value = _require(section, key, section_name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyConfigError(f"{section_name}.{key} must be a number")
    return float(value)


def _require_int(raw: dict[str, Any], key: str, minimum: int) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PolicyConfigError(f"{key} must be an integer >= {minimum}")
    return value


def _parse_loan_policy(section: dict[str, Any]) -> LoanPolicy:
    name = "loan_policy"
    return LoanPolicy(
        policy_id=_require_str(section, "id", name),
        currency=_require_str(section, "currency", name),
        auto_approval_max_exclusive=_require_number(
            section, "auto_approval_max_exclusive", name
        ),
        human_approval_required_at=_require_number(
            section, "human_approval_required_at", name
        ),
    )


def _parse_task_policy(section: dict[str, Any]) -> TaskPolicy:
    name = "task_policy"
    return TaskPolicy(
        policy_id=_require_str(section, "id", name),
        baseline_duration_seconds=_require_number(
            section, "baseline_duration_seconds", name
        ),
        anomaly_ratio=_require_number(section, "anomaly_ratio", name),
        anomaly_min_duration_seconds=_require_number(
            section, "anomaly_min_duration_seconds", name
        ),
    )


def _parse_data_policy(section: dict[str, Any]) -> DataPolicy:
    name = "data_policy"
    permissions_raw = _require(section, "permissions", name)
    if not isinstance(permissions_raw, dict) or not permissions_raw:
        raise PolicyConfigError(f"{name}.permissions must be a non-empty mapping")
    permissions: dict[str, list[str]] = {}
    for agent_id, resources in permissions_raw.items():
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise PolicyConfigError(f"{name}.permissions keys must be non-empty strings")
        if not isinstance(resources, list) or not all(
            isinstance(item, str) and item.strip() for item in resources
        ):
            raise PolicyConfigError(
                f"{name}.permissions[{agent_id!r}] must be a list of resource names"
            )
        permissions[agent_id] = list(resources)
    return DataPolicy(policy_id=_require_str(section, "id", name), permissions=permissions)


def _parse_monitoring_policy(section: dict[str, Any]) -> MonitoringPolicy:
    name = "monitoring"
    return MonitoringPolicy(
        policy_id=_require_str(section, "id", name),
        workflow_deadline_seconds=_require_number(
            section, "workflow_deadline_seconds", name
        ),
        escalate_expired_incomplete_workflows=bool(
            section.get("escalate_expired_incomplete_workflows", True)
        ),
    )


def _parse_alert_policy(section: dict[str, Any]) -> AlertPolicy:
    name = "alerts"
    severities = _require(section, "severities", name)
    if not isinstance(severities, list) or not severities:
        raise PolicyConfigError(f"{name}.severities must be a non-empty list")
    routing = _require(section, "routing", name)
    if not isinstance(routing, dict):
        raise PolicyConfigError(f"{name}.routing must be a mapping")
    for severity in severities:
        backends = routing.get(severity)
        if not isinstance(backends, list) or not backends:
            raise PolicyConfigError(
                f"{name}.routing must define at least one backend for {severity}"
            )
    return AlertPolicy(
        policy_id=_require_str(section, "id", name),
        severities=[str(item) for item in severities],
        routing={str(key): [str(item) for item in value] for key, value in routing.items()},
    )
