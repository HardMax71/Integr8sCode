from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Query, Response

from app.api.dependencies import current_user
from app.domain.enums import NotificationChannel, NotificationStatus
from app.domain.notification import DomainSubscriptionUpdate
from app.domain.user import User
from app.schemas_pydantic.notification import (
    DeleteNotificationResponse,
    NotificationListResponse,
    NotificationSubscription,
    SubscriptionsResponse,
    SubscriptionUpdate,
    UnreadCountResponse,
)
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"], route_class=DishkaRoute)


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    user: Annotated[User, Depends(current_user)],
    notification_service: FromDishka[NotificationService],
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
    result = await notification_service.list_notifications(
        user_id=user.user_id,
        status=status,
        limit=limit,
        offset=offset,
        include_tags=include_tags,
        exclude_tags=exclude_tags,
        tag_prefix=tag_prefix,
    )
    return NotificationListResponse.model_validate(result)


@router.put("/{notification_id}/read", status_code=204)
async def mark_notification_read(
    notification_id: str,
    user: Annotated[User, Depends(current_user)],
    notification_service: FromDishka[NotificationService],
) -> Response:
    """Mark a single notification as read."""
    await notification_service.mark_as_read(notification_id=notification_id, user_id=user.user_id)
    return Response(status_code=204)


@router.post("/mark-all-read", status_code=204)
async def mark_all_read(
    user: Annotated[User, Depends(current_user)],
    notification_service: FromDishka[NotificationService],
) -> Response:
    """Mark all notifications as read."""
    await notification_service.mark_all_as_read(user.user_id)
    return Response(status_code=204)


@router.get("/subscriptions", response_model=SubscriptionsResponse)
async def get_subscriptions(
    user: Annotated[User, Depends(current_user)],
    notification_service: FromDishka[NotificationService],
) -> SubscriptionsResponse:
    """Get all notification channel subscriptions for the authenticated user."""
    result = await notification_service.get_subscriptions(user.user_id)
    return SubscriptionsResponse.model_validate(result)


@router.put("/subscriptions/{channel}", response_model=NotificationSubscription)
async def update_subscription(
    channel: NotificationChannel,
    subscription: SubscriptionUpdate,
    user: Annotated[User, Depends(current_user)],
    notification_service: FromDishka[NotificationService],
) -> NotificationSubscription:
    """Update subscription settings for a notification channel."""
    update_data = DomainSubscriptionUpdate(**subscription.model_dump())
    updated_sub = await notification_service.update_subscription(
        user_id=user.user_id,
        channel=channel,
        update_data=update_data,
    )
    return NotificationSubscription.model_validate(updated_sub)


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    user: Annotated[User, Depends(current_user)],
    notification_service: FromDishka[NotificationService],
) -> UnreadCountResponse:
    """Get the count of unread notifications."""
    count = await notification_service.get_unread_count(user.user_id)
    return UnreadCountResponse(unread_count=count)


@router.delete("/{notification_id}", response_model=DeleteNotificationResponse)
async def delete_notification(
    notification_id: str,
    user: Annotated[User, Depends(current_user)],
    notification_service: FromDishka[NotificationService],
) -> DeleteNotificationResponse:
    """Delete a notification."""
    await notification_service.delete_notification(user_id=user.user_id, notification_id=notification_id)
    return DeleteNotificationResponse(message="Notification deleted")
