from app.db.docs.admin_settings import (
    AuditLogDocument,
    SystemSettingsDocument,
)
from app.db.docs.dlq import DLQMessageDocument
from app.db.docs.event import (
    EventArchiveDocument,
    EventDocument,
)
from app.db.docs.execution import ExecutionDocument
from app.db.docs.notification import (
    NotificationDocument,
    NotificationSubscriptionDocument,
)
from app.db.docs.replay import (
    ReplaySessionDocument,
)
from app.db.docs.resource import ResourceAllocationDocument
from app.db.docs.saga import SagaDocument
from app.db.docs.saved_script import SavedScriptDocument
from app.db.docs.user import UserDocument
from app.db.docs.user_settings import UserSettingsDocument

# All document classes that need to be initialized with Beanie
ALL_DOCUMENTS = [
    UserDocument,
    ExecutionDocument,
    SavedScriptDocument,
    NotificationDocument,
    NotificationSubscriptionDocument,
    UserSettingsDocument,
    SagaDocument,
    DLQMessageDocument,
    EventDocument,
    EventArchiveDocument,
    ReplaySessionDocument,
    ResourceAllocationDocument,
    SystemSettingsDocument,
    AuditLogDocument,
]

__all__ = [
    # User
    "UserDocument",
    # Execution
    "ExecutionDocument",
    # Saved Script
    "SavedScriptDocument",
    # Notification
    "NotificationDocument",
    "NotificationSubscriptionDocument",
    # User Settings
    "UserSettingsDocument",
    # Saga
    "SagaDocument",
    # DLQ
    "DLQMessageDocument",
    # Event
    "EventDocument",
    "EventArchiveDocument",
    # Replay
    "ReplaySessionDocument",
    # Resource
    "ResourceAllocationDocument",
    # Admin Settings
    "SystemSettingsDocument",
    "AuditLogDocument",
    # All documents list for Beanie init
    "ALL_DOCUMENTS",
]
