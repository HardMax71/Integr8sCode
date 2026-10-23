from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Query, Response

from app.api.dependencies import current_user
from app.db.docs import UserDocument
from app.domain.enums import NotificationStatus
from app.schemas_pydantic.notification import (
    DeleteNotificationResponse,
    NotificationListResponse,
    UnreadCountResponse,
)
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"], route_class=DishkaRoute)


@router.get("")
async def get_notifications(
    user: Annotated[UserDocument, Depends(current_user)],
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
    user: Annotated[UserDocument, Depends(current_user)],
    notification_service: FromDishka[NotificationService],
) -> Response:
    """Mark a single notification as read."""
    await notification_service.mark_as_read(notification_id=notification_id, user_id=user.user_id)
    return Response(status_code=204)


@router.post("/mark-all-read", status_code=204)
async def mark_all_read(
    user: Annotated[UserDocument, Depends(current_user)],
    notification_service: FromDishka[NotificationService],
) -> Response:
    """Mark all notifications as read."""
    await notification_service.mark_all_as_read(user.user_id)
    return Response(status_code=204)


@router.get("/unread-count")
async def get_unread_count(
    user: Annotated[UserDocument, Depends(current_user)],
    notification_service: FromDishka[NotificationService],
) -> UnreadCountResponse:
    """Get the count of unread notifications."""
    count = await notification_service.get_unread_count(user.user_id)
    return UnreadCountResponse(unread_count=count)


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: str,
    user: Annotated[UserDocument, Depends(current_user)],
    notification_service: FromDishka[NotificationService],
) -> DeleteNotificationResponse:
    """Delete a notification."""
    await notification_service.delete_notification(user_id=user.user_id, notification_id=notification_id)
    return DeleteNotificationResponse(message="Notification deleted")
