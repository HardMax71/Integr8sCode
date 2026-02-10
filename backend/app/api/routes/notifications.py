from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Query, Request, Response

from app.domain.enums import NotificationChannel, NotificationStatus
from app.schemas_pydantic.notification import (
    DeleteNotificationResponse,
    NotificationListResponse,
    NotificationResponse,
    NotificationSubscription,
    SubscriptionsResponse,
    SubscriptionUpdate,
    UnreadCountResponse,
)
from app.services.auth_service import AuthService
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"], route_class=DishkaRoute)


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    request: Request,
    notification_service: FromDishka[NotificationService],
    auth_service: FromDishka[AuthService],
    status: Annotated[NotificationStatus | None, Query()] = None,
    include_tags: Annotated[list[str] | None, Query(description="Only notifications with any of these tags")] = None,
    exclude_tags: Annotated[list[str] | None, Query(description="Exclude notifications with any of these tags")] = None,
    tag_prefix: Annotated[
        str | None, Query(description="Only notifications having a tag starting with this prefix")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NotificationListResponse:
    """List notifications for the authenticated user."""
    current_user = await auth_service.get_current_user(request)
    result = await notification_service.list_notifications(
        user_id=current_user.user_id,
        status=status,
        limit=limit,
        offset=offset,
        include_tags=include_tags,
        exclude_tags=exclude_tags,
        tag_prefix=tag_prefix,
    )
    return NotificationListResponse(
        notifications=[NotificationResponse.model_validate(n) for n in result.notifications],
        total=result.total,
        unread_count=result.unread_count,
    )


@router.put("/{notification_id}/read", status_code=204)
async def mark_notification_read(
    notification_id: str,
    notification_service: FromDishka[NotificationService],
    request: Request,
    auth_service: FromDishka[AuthService],
) -> Response:
    """Mark a single notification as read."""
    current_user = await auth_service.get_current_user(request)
    await notification_service.mark_as_read(notification_id=notification_id, user_id=current_user.user_id)
    return Response(status_code=204)


@router.post("/mark-all-read", status_code=204)
async def mark_all_read(
    notification_service: FromDishka[NotificationService], request: Request, auth_service: FromDishka[AuthService]
) -> Response:
    """Mark all notifications as read."""
    current_user = await auth_service.get_current_user(request)
    await notification_service.mark_all_as_read(current_user.user_id)
    return Response(status_code=204)


@router.get("/subscriptions", response_model=SubscriptionsResponse)
async def get_subscriptions(
    notification_service: FromDishka[NotificationService], request: Request, auth_service: FromDishka[AuthService]
) -> SubscriptionsResponse:
    """Get all notification channel subscriptions for the authenticated user."""
    current_user = await auth_service.get_current_user(request)
    subscriptions_dict = await notification_service.get_subscriptions(current_user.user_id)
    return SubscriptionsResponse(
        subscriptions=[NotificationSubscription.model_validate(s) for s in subscriptions_dict.values()]
    )


@router.put("/subscriptions/{channel}", response_model=NotificationSubscription)
async def update_subscription(
    channel: NotificationChannel,
    subscription: SubscriptionUpdate,
    notification_service: FromDishka[NotificationService],
    request: Request,
    auth_service: FromDishka[AuthService],
) -> NotificationSubscription:
    """Update subscription settings for a notification channel."""
    current_user = await auth_service.get_current_user(request)
    updated_sub = await notification_service.update_subscription(
        user_id=current_user.user_id,
        channel=channel,
        enabled=subscription.enabled,
        webhook_url=subscription.webhook_url,
        slack_webhook=subscription.slack_webhook,
        severities=subscription.severities,
        include_tags=subscription.include_tags,
        exclude_tags=subscription.exclude_tags,
    )
    return NotificationSubscription.model_validate(updated_sub)


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    notification_service: FromDishka[NotificationService], request: Request, auth_service: FromDishka[AuthService]
) -> UnreadCountResponse:
    """Get the count of unread notifications."""
    current_user = await auth_service.get_current_user(request)
    count = await notification_service.get_unread_count(current_user.user_id)

    return UnreadCountResponse(unread_count=count)


@router.delete("/{notification_id}", response_model=DeleteNotificationResponse)
async def delete_notification(
    notification_id: str,
    notification_service: FromDishka[NotificationService],
    request: Request,
    auth_service: FromDishka[AuthService],
) -> DeleteNotificationResponse:
    """Delete a notification."""
    current_user = await auth_service.get_current_user(request)
    await notification_service.delete_notification(user_id=current_user.user_id, notification_id=notification_id)
    return DeleteNotificationResponse(message="Notification deleted")
