"""Task-execution agent that records start, completion, and duration metadata.

Durations are simulated via an injected clock; automated tests never wait in
real time. A short duration is an anomaly signal for investigation, not proof
of malicious behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from governance.clock import Clock
from governance.event_schema import Event, EventType
from governance.event_store import JsonlEventStore
from governance.policy_loader import TaskPolicy


@dataclass
class TaskAgent:
    agent_id: str
    policy: TaskPolicy
    store: JsonlEventStore
    clock: Clock
    run_id: str
    _started: dict[str, datetime] = field(default_factory=dict)

    def _emit(
        self,
        event_type: EventType,
        task_id: str,
        action: str,
        timestamp: datetime,
        decision: str,
        evidence: dict[str, Any],
    ) -> Event:
        event = Event(
            event_type=event_type,
            agent_id=self.agent_id,
            run_id=self.run_id,
            task_id=task_id,
            timestamp=timestamp,
            action=action,
            resource="task_records",
            policy_id=self.policy.policy_id,
            decision=decision,
            correlation_id=task_id,
            evidence=evidence,
        )
        self.store.append(event)
        return event

    def execute_task(
        self,
        task_id: str,
        task_type: str,
        duration_seconds: float,
        status: str = "completed",
        input_metadata: dict[str, Any] | None = None,
        output_metadata: dict[str, Any] | None = None,
        reported_duration_seconds: float | None = None,
    ) -> tuple[Event, Event]:
        """Simulate executing a task lasting ``duration_seconds``.

        ``reported_duration_seconds`` optionally lets a caller record a
        self-reported duration that conflicts with the observed start/end
        timestamps; the monitor treats that as an inconsistency signal.
        """
        if duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative")
        start = self.clock.now()
        end = start + timedelta(seconds=duration_seconds)
        self._started[task_id] = start
        started_event = self._emit(
            EventType.TASK_STARTED,
            task_id,
            action="start_task",
            timestamp=start,
            decision="started",
            evidence={
                "task_type": task_type,
                "input": dict(input_metadata or {}),
            },
        )
        completed_event = self._emit(
            EventType.TASK_COMPLETED,
            task_id,
            action="complete_task",
            timestamp=end,
            decision=status,
            evidence={
                "task_type": task_type,
                "duration_seconds": (
                    reported_duration_seconds
                    if reported_duration_seconds is not None
                    else duration_seconds
                ),
                "observed_duration_seconds": duration_seconds,
                "start_timestamp": start.isoformat().replace("+00:00", "Z"),
                "end_timestamp": end.isoformat().replace("+00:00", "Z"),
                "status": status,
                "output": dict(output_metadata or {}),
            },
        )
        return started_event, completed_event
