"""Amazon SNS alert backend.

Publishes findings to a configured SNS topic using boto3 and the ambient AWS
credential chain (environment variables, shared config, or IAM role). The
topic ARN comes from the environment; nothing is hardcoded.

Important honesty guarantees:
  * A ``SUCCESS`` result means the SNS API *accepted* the publish request.
    It does not confirm that any subscriber (e.g. email) received it.
  * Transient API errors are retried with exponential backoff; persistent
    failures are reported as ``FAILED`` and never raise into the monitor.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from governance.event_schema import to_utc_iso
from notifications.base import DeliveryResult
from governance.findings import Finding


@dataclass
class SNSNotifier:
    topic_arn: str
    region: str | None = None
    max_attempts: int = 3
    backoff_seconds: float = 0.5
    client: Any = None
    sleep_fn: Callable[[float], None] = field(default=time.sleep, repr=False)
    name: str = "sns"

    def __post_init__(self) -> None:
        if not self.topic_arn:
            raise ValueError("SNS topic ARN must not be empty")

    def _get_client(self) -> Any:
        if self.client is None:
            import boto3

            self.client = boto3.client("sns", region_name=self.region or None)
        return self.client

    def send(self, finding: Finding) -> DeliveryResult:
        message = {
            "alert_type": "policy_violation_finding",
            "note": (
                "Publish accepted by SNS does not guarantee subscriber delivery; "
                "check the subscription's delivery logs to confirm receipt."
            ),
            "finding": finding.to_dict(),
        }
        last_error = "unknown error"
        for attempt in range(1, self.max_attempts + 1):
            try:
                client = self._get_client()
                response = client.publish(
                    TopicArn=self.topic_arn,
                    Subject=f"[{finding.severity.value}] {finding.rule_id} agent-governance-alert",
                    Message=json.dumps(message, indent=2, sort_keys=True),
                    MessageAttributes={
                        "severity": {"DataType": "String", "StringValue": finding.severity.value},
                        "rule_id": {"DataType": "String", "StringValue": finding.rule_id},
                        "finding_id": {"DataType": "String", "StringValue": finding.finding_id},
                    },
                )
                message_id = response.get("MessageId", "<no MessageId>")
                return DeliveryResult.success(
                    backend=self.name,
                    finding_id=finding.finding_id,
                    detail=(
                        f"SNS publish accepted (MessageId={message_id}); "
                        "subscriber delivery not confirmed by this result"
                    ),
                    attempts=attempt,
                )
            except Exception as exc:  # botocore errors vary by version; treat uniformly
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.max_attempts:
                    self.sleep_fn(self.backoff_seconds * (2 ** (attempt - 1)))
        return DeliveryResult.failed(
            backend=self.name,
            finding_id=finding.finding_id,
            detail=f"SNS publish failed after {self.max_attempts} attempts: {last_error}",
            attempts=self.max_attempts,
        )


def sns_notifier_from_env(**overrides: Any) -> SNSNotifier | None:
    """Build an SNSNotifier from environment variables, or None if unset."""
    topic_arn = os.environ.get("SNS_TOPIC_ARN", "").strip()
    if not topic_arn:
        return None
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    kwargs: dict[str, Any] = {"topic_arn": topic_arn, "region": region}
    kwargs.update(overrides)
    return SNSNotifier(**kwargs)
