from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api.dependencies import get_current_user
from app.core.service_dependencies import NotificationServiceDep
from app.schemas_pydantic.notification import (
    NotificationChannel,
    NotificationListResponse,
    NotificationStatus,
    NotificationSubscription,
    SubscriptionUpdate,
    TestNotificationRequest,
)
from app.schemas_pydantic.user import User

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
        notification_service: NotificationServiceDep,
        status: NotificationStatus | None = Query(None),
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        current_user: User = Depends(get_current_user),
) -> NotificationListResponse:
    """Get user notifications with pagination"""
    return await notification_service.list_notifications(
        user_id=current_user.user_id,
        status=status,
        limit=limit,
        offset=offset
    )


@router.put("/{notification_id}/read", status_code=204)
async def mark_notification_read(
        notification_id: str,
        notification_service: NotificationServiceDep,
        current_user: User = Depends(get_current_user)
) -> Response:
    success = await notification_service.mark_as_read(
        notification_id=notification_id,
        user_id=current_user.user_id
    )

    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")

    return Response(status_code=204)


@router.post("/mark-all-read", status_code=204)
async def mark_all_read(
        notification_service: NotificationServiceDep,
        current_user: User = Depends(get_current_user)
) -> Response:
    """Mark all notifications as read"""
    await notification_service.mark_all_as_read(current_user.user_id)
    return Response(status_code=204)


@router.get("/subscriptions")
async def get_subscriptions(
        notification_service: NotificationServiceDep,
        current_user: User = Depends(get_current_user)
) -> dict[str, object]:
    """Get all notification subscriptions for current user"""
    subscriptions = await notification_service.get_subscriptions(current_user.user_id)
    return {"subscriptions": subscriptions}


@router.put("/subscriptions/{channel}")
async def update_subscription(
        channel: NotificationChannel,
        subscription: SubscriptionUpdate,
        notification_service: NotificationServiceDep,
        current_user: User = Depends(get_current_user)
) -> NotificationSubscription:
    updated_sub = await notification_service.update_subscription(
        user_id=current_user.user_id,
        channel=channel,
        enabled=subscription.enabled,
        webhook_url=subscription.webhook_url,
        slack_webhook=subscription.slack_webhook,
        notification_types=subscription.notification_types
    )

    return updated_sub


@router.post("/test")
async def send_test_notification(
        request: TestNotificationRequest,
        notification_service: NotificationServiceDep,
        current_user: User = Depends(get_current_user)
) -> dict[str, object]:
    notification = await notification_service.send_test_notification(
        user_id=current_user.user_id,
        request=request
    )

    return {
        "message": "Test notification sent successfully",
        "notification_id": str(notification.notification_id),
        "channel": notification.channel,
        "status": notification.status
    }


@router.get("/unread-count")
async def get_unread_count(
        notification_service: NotificationServiceDep,
        current_user: User = Depends(get_current_user)
) -> dict[str, int]:
    count = await notification_service.get_unread_count(current_user.user_id)

    return {"unread_count": count}


@router.delete("/{notification_id}")
async def delete_notification(
        notification_id: str,
        notification_service: NotificationServiceDep,
        current_user: User = Depends(get_current_user)
) -> dict[str, str]:
    """Delete a notification"""
    deleted = await notification_service.delete_notification(
        user_id=current_user.user_id,
        notification_id=notification_id
    )

    if not deleted:
        raise HTTPException(status_code=404, detail="Notification not found")

    return {"message": "Notification deleted"}
