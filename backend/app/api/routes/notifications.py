from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api.dependencies import get_current_user
from app.schemas_pydantic.notification import (
    NotificationChannel,
    NotificationListResponse,
    NotificationStatus,
    NotificationSubscription,
    SubscriptionUpdate,
    TestNotificationRequest,
)
from app.schemas_pydantic.user import User
from app.services.notification_service import NotificationService, get_notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
        status: Optional[NotificationStatus] = Query(None),
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        current_user: User = Depends(get_current_user),
        notification_service: NotificationService = Depends(get_notification_service)
) -> NotificationListResponse:
    """Get user notifications with pagination"""
    return await notification_service.get_user_notifications_list(
        user_id=current_user.user_id,
        status=status,
        limit=limit,
        skip=offset
    )


@router.put("/{notification_id}/read", status_code=204)
async def mark_notification_read(
        notification_id: str,
        current_user: User = Depends(get_current_user),
        notification_service: NotificationService = Depends(get_notification_service)
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
        current_user: User = Depends(get_current_user),
        notification_service: NotificationService = Depends(get_notification_service)
) -> Response:
    """Mark all notifications as read"""
    await notification_service.mark_all_as_read(current_user.user_id)
    return Response(status_code=204)


@router.get("/subscriptions")
async def get_subscriptions(
        current_user: User = Depends(get_current_user),
        notification_service: NotificationService = Depends(get_notification_service)
) -> Dict[str, Any]:
    """Get all notification subscriptions for current user"""
    subscriptions = await notification_service.get_subscriptions(current_user.user_id)
    return {"subscriptions": subscriptions}


@router.put("/subscriptions/{channel}")
async def update_subscription(
        channel: NotificationChannel,
        subscription: SubscriptionUpdate,
        current_user: User = Depends(get_current_user),
        notification_service: NotificationService = Depends(get_notification_service)
) -> NotificationSubscription:
    sub = NotificationSubscription(
        user_id=current_user.user_id,
        channel=channel,
        **subscription.model_dump()
    )

    updated_sub = await notification_service.update_subscription(
        user_id=current_user.user_id,
        channel=channel,
        subscription=sub
    )

    return updated_sub


@router.post("/test")
async def send_test_notification(
        request: TestNotificationRequest,
        current_user: User = Depends(get_current_user),
        notification_service: NotificationService = Depends(get_notification_service)
) -> Dict[str, Any]:
    context = {
        "test": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_name": current_user.username,
        "execution_id": "test_123",
        "language": "python",
        "duration_seconds": 1.5,
        "output_lines": 10,
        "error_message": "This is a test error",
        "alert_type": "Test Alert",
        "details": "This is a test notification",
        "ip_address": "127.0.0.1"
    }

    notification = await notification_service.create_notification(
        user_id=current_user.user_id,
        notification_type=request.notification_type,
        channel=request.channel,
        context=context
    )

    if not notification:
        raise HTTPException(
            status_code=400,
            detail="Could not create test notification. Check your subscription settings."
        )

    success = await notification_service.send_notification(notification)

    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send test notification: {notification.error_message}"
        )

    return {
        "message": "Test notification sent successfully",
        "notification_id": str(notification.notification_id),
        "channel": notification.channel,
        "status": notification.status
    }


@router.get("/unread-count")
async def get_unread_count(
        current_user: User = Depends(get_current_user),
        notification_service: NotificationService = Depends(get_notification_service)
) -> Dict[str, int]:
    count = await notification_service.get_unread_count(current_user.user_id)

    return {"unread_count": count}


@router.delete("/{notification_id}")
async def delete_notification(
        notification_id: str,
        current_user: User = Depends(get_current_user),
        notification_service: NotificationService = Depends(get_notification_service)
) -> Dict[str, str]:
    """Delete a notification"""
    deleted = await notification_service.delete_notification(notification_id, current_user.user_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Notification not found")

    return {"message": "Notification deleted"}
