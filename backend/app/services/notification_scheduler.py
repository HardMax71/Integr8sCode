import logging

from app.db.repositories.notification_repository import NotificationRepository
from app.services.notification_service import NotificationService


class NotificationScheduler:
    """Stateless scheduler service that processes due notifications.

    APScheduler manages the timer (interval trigger) in the DI provider.
    This class contains only the business logic for finding and delivering
    due notifications — no loops, no lifecycle, no state.
    """

    def __init__(
        self,
        notification_repository: NotificationRepository,
        notification_service: NotificationService,
        logger: logging.Logger,
    ) -> None:
        self.repository = notification_repository
        self.service = notification_service
        self.logger = logger

    async def process_due_notifications(self, batch_size: int = 50) -> int:
        """Find and deliver all notifications whose scheduled_for <= now.

        Called by APScheduler on a fixed interval. Each invocation is
        a single-shot batch: query DB for due items, deliver each, return.

        Returns the number of notifications successfully delivered.
        """
        due = await self.repository.find_due_notifications(limit=batch_size)
        if not due:
            return 0

        self.logger.info(f"Found {len(due)} due scheduled notifications")

        delivered = 0
        for notification in due:
            try:
                await self.service._deliver_notification(notification)
                delivered += 1
            except Exception as e:
                self.logger.error(
                    f"Failed to deliver scheduled notification {notification.notification_id}: {e}",
                    exc_info=True,
                )

        self.logger.info(f"Delivered {delivered}/{len(due)} scheduled notifications")
        return delivered
