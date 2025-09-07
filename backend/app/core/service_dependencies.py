from dishka import FromDishka

from app.db.repositories import (
    UserRepository,
)
from app.db.repositories.admin.admin_events_repository import AdminEventsRepository
from app.db.repositories.admin.admin_settings_repository import AdminSettingsRepository
from app.db.repositories.admin.admin_user_repository import AdminUserRepository
from app.db.repositories.dlq_repository import DLQRepository

# Repositories (request-scoped)
UserRepositoryDep = FromDishka[UserRepository]
DLQRepositoryDep = FromDishka[DLQRepository]
AdminEventsRepositoryDep = FromDishka[AdminEventsRepository]
AdminSettingsRepositoryDep = FromDishka[AdminSettingsRepository]
AdminUserRepositoryDep = FromDishka[AdminUserRepository]
