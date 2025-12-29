from app.db.docs.admin_settings import (
    AuditLogDocument,
    ExecutionLimitsConfig,
    MonitoringSettingsConfig,
    SecuritySettingsConfig,
    SystemSettingsDocument,
)
from app.db.docs.dlq import DLQMessageDocument
from app.db.docs.event import (
    EventArchiveDocument,
    EventDocument,
    EventStoreDocument,
)
from app.db.docs.execution import ExecutionDocument, ResourceUsage
from app.db.docs.notification import (
    NotificationDocument,
    NotificationSubscriptionDocument,
)
from app.db.docs.replay import (
    ReplayConfig,
    ReplayFilter,
    ReplaySessionDocument,
)
from app.db.docs.resource import ResourceAllocationDocument
from app.db.docs.saga import SagaDocument
from app.db.docs.saved_script import SavedScriptDocument
from app.db.docs.user import UserDocument
from app.db.docs.user_settings import (
    EditorSettings,
    NotificationSettings,
    UserSettingsDocument,
    UserSettingsSnapshotDocument,
)

# All document classes that need to be initialized with Beanie
ALL_DOCUMENTS = [
    UserDocument,
    ExecutionDocument,
    SavedScriptDocument,
    NotificationDocument,
    NotificationSubscriptionDocument,
    UserSettingsDocument,
    UserSettingsSnapshotDocument,
    SagaDocument,
    DLQMessageDocument,
    EventDocument,
    EventStoreDocument,
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
    "ResourceUsage",
    # Saved Script
    "SavedScriptDocument",
    # Notification
    "NotificationDocument",
    "NotificationSubscriptionDocument",
    # User Settings
    "UserSettingsDocument",
    "UserSettingsSnapshotDocument",
    "NotificationSettings",
    "EditorSettings",
    # Saga
    "SagaDocument",
    # DLQ
    "DLQMessageDocument",
    # Event
    "EventDocument",
    "EventStoreDocument",
    "EventArchiveDocument",
    # Replay
    "ReplaySessionDocument",
    "ReplayConfig",
    "ReplayFilter",
    # Resource
    "ResourceAllocationDocument",
    # Admin Settings
    "SystemSettingsDocument",
    "AuditLogDocument",
    "ExecutionLimitsConfig",
    "SecuritySettingsConfig",
    "MonitoringSettingsConfig",
    # All documents list for Beanie init
    "ALL_DOCUMENTS",
]
