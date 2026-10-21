"""Optional CloudTrail reader for corroborating agent activity (extension).

Scope and honest limitations:
  * This reads *management* events from CloudTrail's LookupEvents API using the
    ambient (least-privilege) AWS identity. It is read-only.
  * CloudTrail does NOT record the application-specific Python events this POC
    emits (loan decisions, task durations, data reads). Those must be logged by
    the application itself, as this project does into the JSONL event store.
  * *Data* events (e.g. S3 object-level GETs, DynamoDB item reads) are not on by
    default and can incur additional cost; they must be enabled separately via
    CloudTrail data-event selectors. This reader does not enable anything.

Returns normalized dictionaries. Never raises into the monitor: on any failure
it returns an empty list and records the error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class CloudTrailReader:
    region: str | None = None
    client: Any = None
    name: str = "cloudtrail"

    def _get_client(self) -> Any:
        if self.client is None:
            import boto3

            self.client = boto3.client("cloudtrail", region_name=self.region or None)
        return self.client

    def lookup_management_events(
        self,
        start_time: datetime,
        end_time: datetime,
        max_events: int = 50,
        event_attribute_key: str | None = None,
        event_attribute_value: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Return (normalized_events, error). ``error`` is None on success."""
        if start_time.tzinfo is None or end_time.tzinfo is None:
            return [], "start_time and end_time must be timezone-aware"
        kwargs: dict[str, Any] = {
            "StartTime": start_time.astimezone(timezone.utc),
            "EndTime": end_time.astimezone(timezone.utc),
            "MaxResults": max(1, min(max_events, 50)),
        }
        if event_attribute_key and event_attribute_value:
            kwargs["LookupAttributes"] = [
                {"AttributeKey": event_attribute_key, "AttributeValue": event_attribute_value}
            ]
        try:
            response = self._get_client().lookup_events(**kwargs)
        except Exception as exc:
            return [], f"{type(exc).__name__}: {exc}"
        normalized = [self._normalize(record) for record in response.get("Events", [])]
        return normalized, None

    @staticmethod
    def _normalize(record: dict[str, Any]) -> dict[str, Any]:
        raw = record.get("CloudTrailEvent")
        return {
            "source": "cloudtrail",
            "event_id": record.get("EventId"),
            "event_name": record.get("EventName"),
            "event_time": (
                record["EventTime"].isoformat()
                if isinstance(record.get("EventTime"), datetime)
                else None
            ),
            "username": record.get("Username"),
            "raw_event": raw,
        }
