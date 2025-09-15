from dataclasses import asdict, fields

from app.domain.notification import (
    DomainNotification,
    DomainNotificationSubscription,
)


class NotificationMapper:
    """Map Notification domain models to/from MongoDB documents."""

    # DomainNotification
    @staticmethod
    def to_mongo_document(notification: DomainNotification) -> dict:
        return asdict(notification)

    @staticmethod
    def to_update_dict(notification: DomainNotification) -> dict:
        doc = asdict(notification)
        doc.pop("notification_id", None)
        return doc

    @staticmethod
    def from_mongo_document(doc: dict) -> DomainNotification:
        allowed = {f.name for f in fields(DomainNotification)}
        filtered = {k: v for k, v in doc.items() if k in allowed}
        return DomainNotification(**filtered)

    # DomainNotificationSubscription
    @staticmethod
    def subscription_to_mongo_document(subscription: DomainNotificationSubscription) -> dict:
        return asdict(subscription)

    @staticmethod
    def subscription_from_mongo_document(doc: dict) -> DomainNotificationSubscription:
        allowed = {f.name for f in fields(DomainNotificationSubscription)}
        filtered = {k: v for k, v in doc.items() if k in allowed}
        return DomainNotificationSubscription(**filtered)
