"""Loan-processing agent with enforced human-approval policy.

Policy (from config/policies.yaml):
  * amount <  INR 1,000 -> automatic approval permitted
  * amount >= INR 1,000 -> recorded human authorization mandatory before
    the approval may be finalized

The approval finalization path is the enforcement boundary: it refuses to
emit a finalized approval without authorization. `attempt_unauthorized_approval`
simulates a faulty agent that tries to bypass the boundary; the boundary still
blocks it and the attempt is recorded so the independent monitor can flag it.

`LegacyLoanAgent` is an isolated, fully simulated legacy-bug scenario: it
records an unauthorized approval outcome without any enforcement. It is never
connected to a real financial system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from governance.clock import Clock
from governance.event_schema import Event, EventType, utc_now
from governance.event_store import JsonlEventStore
from governance.policy_loader import LoanPolicy

CURRENCY_FIELD = "amount"


class ApprovalRequiredError(PermissionError):
    """Raised when an approval is attempted without mandatory authorization."""


@dataclass
class _WorkflowState:
    amount: float | None = None
    authorization_granted: bool = False
    authorization_requested: bool = False
    finalized: bool = False
    outcome: str | None = None


@dataclass
class LoanAgent:
    """Processes synthetic loan requests and records structured events."""

    agent_id: str
    policy: LoanPolicy
    store: JsonlEventStore
    clock: Clock
    run_id: str
    _workflows: dict[str, _WorkflowState] = field(default_factory=dict)

    def _state(self, task_id: str) -> _WorkflowState:
        return self._workflows.setdefault(task_id, _WorkflowState())

    def _emit(
        self,
        event_type: EventType,
        task_id: str,
        action: str,
        decision: str | None = None,
        resource: str | None = None,
        evidence: dict[str, Any] | None = None,
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
            evidence=evidence or {},
        )
        self.store.append(event)
        return event

    def request_loan(self, task_id: str, amount: float) -> Event:
        if amount < 0:
            raise ValueError("loan amount must be non-negative")
        state = self._state(task_id)
        state.amount = amount
        return self._emit(
            EventType.LOAN_REQUESTED,
            task_id,
            action="request_loan",
            decision="requested",
            resource="loan_applications",
            evidence={
                CURRENCY_FIELD: amount,
                "currency": self.policy.currency,
                "requires_human_approval": self.policy.requires_human_approval(amount),
            },
        )

    def request_human_approval(self, task_id: str) -> Event:
        state = self._state(task_id)
        if state.amount is None:
            raise RuntimeError("request_loan must be called first")
        state.authorization_requested = True
        return self._emit(
            EventType.HUMAN_APPROVAL_REQUESTED,
            task_id,
            action="request_human_approval",
            decision="pending",
            evidence={
                CURRENCY_FIELD: state.amount,
                "currency": self.policy.currency,
            },
        )

    def record_authorization_result(self, task_id: str, granted: bool) -> Event:
        state = self._state(task_id)
        if state.amount is None:
            raise RuntimeError("request_loan must be called first")
        state.authorization_granted = granted
        event_type = (
            EventType.HUMAN_APPROVAL_GRANTED if granted else EventType.HUMAN_APPROVAL_DENIED
        )
        return self._emit(
            event_type,
            task_id,
            action="record_human_authorization",
            decision="granted" if granted else "denied",
            evidence={CURRENCY_FIELD: state.amount, "currency": self.policy.currency},
        )

    def finalize_approval(self, task_id: str) -> Event:
        """Finalize an approval, enforcing the human-authorization policy.

        Emits ``loan.approved`` when authorized; emits ``loan.approval_blocked``
        and raises :class:`ApprovalRequiredError` otherwise. The enforcement
        boundary is never bypassed here.
        """
        state = self._state(task_id)
        if state.amount is None:
            raise RuntimeError("request_loan must be called first")
        if state.finalized:
            raise RuntimeError(f"workflow {task_id} already finalized")
        if self.policy.requires_human_approval(state.amount) and not state.authorization_granted:
            event = self._emit(
                EventType.LOAN_APPROVAL_BLOCKED,
                task_id,
                action="finalize_approval",
                decision="blocked",
                evidence={
                    CURRENCY_FIELD: state.amount,
                    "currency": self.policy.currency,
                    "reason": "missing_human_authorization",
                    "bypass_attempted": False,
                },
            )
            raise ApprovalRequiredError(
                f"loan of {state.amount} {self.policy.currency} requires human "
                "authorization before approval can be finalized"
            )
        state.finalized = True
        state.outcome = "approved"
        return self._emit(
            EventType.LOAN_APPROVED,
            task_id,
            action="finalize_approval",
            decision="approved",
            resource="loan_applications",
            evidence={
                CURRENCY_FIELD: state.amount,
                "currency": self.policy.currency,
                "human_authorization": (
                    "granted"
                    if self.policy.requires_human_approval(state.amount)
                    else "not_required"
                ),
            },
        )

    def reject(self, task_id: str, reason: str = "policy_decision") -> Event:
        state = self._state(task_id)
        if state.amount is None:
            raise RuntimeError("request_loan must be called first")
        state.finalized = True
        state.outcome = "rejected"
        return self._emit(
            EventType.LOAN_REJECTED,
            task_id,
            action="reject_loan",
            decision="rejected",
            resource="loan_applications",
            evidence={
                CURRENCY_FIELD: state.amount,
                "currency": self.policy.currency,
                "reason": reason,
            },
        )

    def auto_approve_if_eligible(self, task_id: str) -> Event | None:
        """Automatically approve small loans; request human approval otherwise."""
        state = self._state(task_id)
        if state.amount is None:
            raise RuntimeError("request_loan must be called first")
        if self.policy.may_auto_approve(state.amount):
            return self.finalize_approval(task_id)
        self.request_human_approval(task_id)
        return None

    def attempt_unauthorized_approval(self, task_id: str) -> Event:
        """Fault injection: a faulty agent tries to force finalization.

        The enforcement boundary still refuses; the blocked attempt (with
        ``bypass_attempted: true``) is recorded so the monitor can detect it.
        """
        state = self._state(task_id)
        if state.amount is None:
            raise RuntimeError("request_loan must be called first")
        if state.finalized:
            raise RuntimeError(f"workflow {task_id} already finalized")
        if self.policy.requires_human_approval(state.amount) and not state.authorization_granted:
            event = self._emit(
                EventType.LOAN_APPROVAL_BLOCKED,
                task_id,
                action="finalize_approval",
                decision="blocked",
                evidence={
                    CURRENCY_FIELD: state.amount,
                    "currency": self.policy.currency,
                    "reason": "missing_human_authorization",
                    "bypass_attempted": True,
                },
            )
            raise ApprovalRequiredError(
                "enforcement boundary blocked an unauthorized approval attempt"
            )
        return self.finalize_approval(task_id)


class LegacyLoanAgent(LoanAgent):
    """Isolated simulated legacy-bug scenario.

    Reproduces an old integration that recorded a final approval without
    consulting the authorization policy. There is no real enforcement
    connection and no real financial system; this class exists only so the
    monitor can be tested against historically-buggy event streams.
    """

    def legacy_record_approval_bypassing_policy(self, task_id: str) -> Event:
        state = self._state(task_id)
        if state.amount is None:
            raise RuntimeError("request_loan must be called first")
        state.finalized = True
        state.outcome = "approved"
        return self._emit(
            EventType.LOAN_APPROVED,
            task_id,
            action="legacy_finalize_approval",
            decision="approved",
            resource="loan_applications",
            evidence={
                CURRENCY_FIELD: state.amount,
                "currency": self.policy.currency,
                "human_authorization": "missing",
                "legacy_bug_simulation": True,
            },
        )
