"""Notification backends: local JSONL/terminal and Amazon SNS."""

from notifications.base import DeliveryResult, NotificationError, Notifier
from notifications.local_notifier import LocalNotifier
from notifications.sns_notifier import SNSNotifier, sns_notifier_from_env

__all__ = [
    "DeliveryResult",
    "NotificationError",
    "Notifier",
    "LocalNotifier",
    "SNSNotifier",
    "sns_notifier_from_env",
]
