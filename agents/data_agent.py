"""Data-access agent with enforced resource permissions.

Permissions are enforced at the data-access boundary (this agent refuses
unauthorized reads), not only in the monitoring layer. The event stream
distinguishes: access requested, access denied, access granted, data read
completed.

`LegacyDataAgent` is an isolated simulated legacy-bug scenario that records
an unauthorized successful read without enforcement. No real datasets or
restricted resources are ever touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from governance.clock import Clock
from governance.event_schema import Event, EventType
from governance.event_store import JsonlEventStore
from governance.policy_loader import DataPolicy


class AccessDeniedError(PermissionError):
    """Raised when an agent attempts to read a resource it may not access."""


@dataclass
class DataAccessAgent:
    agent_id: str
    policy: DataPolicy
    store: JsonlEventStore
    clock: Clock
    run_id: str
    _granted: set[str] = field(default_factory=set)

    def _emit(
        self,
        event_type: EventType,
        task_id: str,
        action: str,
        resource: str,
        decision: str,
        evidence: dict[str, Any],
    ) -> Event:
        event = Event(
            event_type=event_type,
            agent_id=self.agent_id,
            run_id=self.run_id,
            task_id=task_id,
            timestamp=self.clock.now(),
            action=action,
            resource=resource,
            policy_id=self.policy.policy_id,
            decision=decision,
            correlation_id=task_id,
            evidence=evidence,
        )
        self.store.append(event)
        return event

    def request_access(self, task_id: str, resource: str) -> Event:
        return self._emit(
            EventType.DATA_ACCESS_REQUESTED,
            task_id,
            action="request_access",
            resource=resource,
            decision="requested",
            evidence={"permitted": self.policy.is_allowed(self.agent_id, resource)},
        )

    def read_dataset(
        self,
        task_id: str,
        resource: str,
        row_count: int = 100,
        purpose: str = "analytics",
    ) -> list[Event]:
        """Request and (if permitted) read a synthetic dataset.

        Permission is checked here at the boundary. An unauthorized request
        emits ``data.access_denied`` and raises :class:`AccessDeniedError`;
        no read event is recorded.
        """
        events = [self.request_access(task_id, resource)]
        if not self.policy.is_allowed(self.agent_id, resource):
            events.append(
                self._emit(
                    EventType.DATA_ACCESS_DENIED,
                    task_id,
                    action="enforce_permissions",
                    resource=resource,
                    decision="denied",
                    evidence={
                        "reason": "resource_not_permitted_for_agent",
                        "allowed_resources": self.policy.allowed_resources(self.agent_id),
                    },
                )
            )
            raise AccessDeniedError(
                f"agent {self.agent_id!r} may not access resource {resource!r}"
            )
        self._granted.add(resource)
        events.append(
            self._emit(
                EventType.DATA_ACCESS_GRANTED,
                task_id,
                action="enforce_permissions",
                resource=resource,
                decision="granted",
                evidence={"purpose": purpose},
            )
        )
        events.append(
            self._emit(
                EventType.DATA_READ_COMPLETED,
                task_id,
                action="read_dataset",
                resource=resource,
                decision="completed",
                evidence={"purpose": purpose, "rows_read": row_count, "synthetic": True},
            )
        )
        return events


class LegacyDataAgent(DataAccessAgent):
    """Isolated simulated legacy-bug scenario.

    Records a granted access and a completed read for a resource the agent
    has no permission for, bypassing the boundary check entirely. Used only
    to generate historical-style event streams for the monitor.
    """

    def legacy_read_without_enforcement(
        self, task_id: str, resource: str, row_count: int = 100
    ) -> list[Event]:
        events = [self.request_access(task_id, resource)]
        events.append(
            self._emit(
                EventType.DATA_ACCESS_GRANTED,
                task_id,
                action="legacy_enforce_permissions",
                resource=resource,
                decision="granted",
                evidence={"legacy_bug_simulation": True},
            )
        )
        events.append(
            self._emit(
                EventType.DATA_READ_COMPLETED,
                task_id,
                action="legacy_read_dataset",
                resource=resource,
                decision="completed",
                evidence={
                    "rows_read": row_count,
                    "synthetic": True,
                    "legacy_bug_simulation": True,
                },
            )
        )
        return events
