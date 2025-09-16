from __future__ import annotations

from typing import Dict, List

from app.domain.notification import (
    DomainNotification,
    DomainNotificationListResult,
    DomainNotificationSubscription,
)
from app.schemas_pydantic.notification import (
    NotificationListResponse,
    NotificationResponse,
    NotificationSubscription,
    SubscriptionsResponse,
)


class NotificationApiMapper:
    @staticmethod
    def to_response(n: DomainNotification) -> NotificationResponse:
        return NotificationResponse(
            notification_id=n.notification_id,
            channel=n.channel,
            status=n.status,
            subject=n.subject,
            body=n.body,
            action_url=n.action_url,
            created_at=n.created_at,
            read_at=n.read_at,
            severity=n.severity,
            tags=n.tags,
        )

    @staticmethod
    def list_result_to_response(result: DomainNotificationListResult) -> NotificationListResponse:
        return NotificationListResponse(
            notifications=[NotificationApiMapper.to_response(x) for x in result.notifications],
            total=result.total,
            unread_count=result.unread_count,
        )

    @staticmethod
    def subscription_to_pydantic(s: DomainNotificationSubscription) -> NotificationSubscription:
        return NotificationSubscription(
            user_id=s.user_id,
            channel=s.channel,
            enabled=s.enabled,
            severities=s.severities,
            include_tags=s.include_tags,
            exclude_tags=s.exclude_tags,
            webhook_url=s.webhook_url,
            slack_webhook=s.slack_webhook,
            quiet_hours_enabled=s.quiet_hours_enabled,
            quiet_hours_start=s.quiet_hours_start,
            quiet_hours_end=s.quiet_hours_end,
            timezone=s.timezone,
            batch_interval_minutes=s.batch_interval_minutes,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )

    @staticmethod
    def subscriptions_dict_to_response(subs: Dict[str, DomainNotificationSubscription]) -> SubscriptionsResponse:
        py_subs: List[NotificationSubscription] = [
            NotificationApiMapper.subscription_to_pydantic(s) for s in subs.values()
        ]
        return SubscriptionsResponse(subscriptions=py_subs)
