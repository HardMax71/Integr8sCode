from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.dependencies import AuthService
from app.api.rate_limit import check_rate_limit
from app.infrastructure.mappers.notification_api_mapper import NotificationApiMapper
from app.schemas_pydantic.notification import (
    DeleteNotificationResponse,
    NotificationChannel,
    NotificationListResponse,
    NotificationStatus,
    NotificationSubscription,
    SubscriptionsResponse,
    SubscriptionUpdate,
    UnreadCountResponse,
)
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"], route_class=DishkaRoute)


@router.get("", response_model=NotificationListResponse, dependencies=[Depends(check_rate_limit)])
async def get_notifications(
        request: Request,
        notification_service: FromDishka[NotificationService],
        auth_service: FromDishka[AuthService],
        status: NotificationStatus | None = Query(None),
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
) -> NotificationListResponse:
    current_user = await auth_service.get_current_user(request)
    result = await notification_service.list_notifications(
        user_id=current_user.user_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return NotificationApiMapper.list_result_to_response(result)


@router.put("/{notification_id}/read", status_code=204, dependencies=[Depends(check_rate_limit)])
async def mark_notification_read(
        notification_id: str,
        notification_service: FromDishka[NotificationService],
        request: Request,
        auth_service: FromDishka[AuthService]
) -> Response:
    current_user = await auth_service.get_current_user(request)
    _ = await notification_service.mark_as_read(
        notification_id=notification_id,
        user_id=current_user.user_id
    )

    return Response(status_code=204)


@router.post("/mark-all-read", status_code=204)
async def mark_all_read(
        notification_service: FromDishka[NotificationService],
        request: Request,
        auth_service: FromDishka[AuthService]
) -> Response:
    current_user = await auth_service.get_current_user(request)
    """Mark all notifications as read"""
    await notification_service.mark_all_as_read(current_user.user_id)
    return Response(status_code=204)


@router.get("/subscriptions", response_model=SubscriptionsResponse)
async def get_subscriptions(
        notification_service: FromDishka[NotificationService],
        request: Request,
        auth_service: FromDishka[AuthService]
) -> SubscriptionsResponse:
    current_user = await auth_service.get_current_user(request)
    subscriptions_dict = await notification_service.get_subscriptions(current_user.user_id)
    return NotificationApiMapper.subscriptions_dict_to_response(subscriptions_dict)


@router.put("/subscriptions/{channel}", response_model=NotificationSubscription)
async def update_subscription(
        channel: NotificationChannel,
        subscription: SubscriptionUpdate,
        notification_service: FromDishka[NotificationService],
        request: Request,
        auth_service: FromDishka[AuthService]
) -> NotificationSubscription:
    current_user = await auth_service.get_current_user(request)
    updated_sub = await notification_service.update_subscription(
        user_id=current_user.user_id,
        channel=channel,
        enabled=subscription.enabled,
        webhook_url=subscription.webhook_url,
        slack_webhook=subscription.slack_webhook,
        notification_types=subscription.notification_types
    )
    return NotificationApiMapper.subscription_to_pydantic(updated_sub)


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
        notification_service: FromDishka[NotificationService],
        request: Request,
        auth_service: FromDishka[AuthService]
) -> UnreadCountResponse:
    current_user = await auth_service.get_current_user(request)
    count = await notification_service.get_unread_count(current_user.user_id)

    return UnreadCountResponse(unread_count=count)


@router.delete("/{notification_id}", response_model=DeleteNotificationResponse)
async def delete_notification(
        notification_id: str,
        notification_service: FromDishka[NotificationService],
        request: Request,
        auth_service: FromDishka[AuthService]
) -> DeleteNotificationResponse:
    current_user = await auth_service.get_current_user(request)
    """Delete a notification"""
    _ = await notification_service.delete_notification(
        user_id=current_user.user_id,
        notification_id=notification_id
    )
    return DeleteNotificationResponse(message="Notification deleted")
