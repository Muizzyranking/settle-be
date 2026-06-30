import logging

from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.models.tenant import Tenant
from app.services.notifications.channels.base import BaseChannel
from app.services.notifications.context import NotificationContext

from .channels.email import EmailChannel
from .channels.in_app import InAppChannel
from .channels.webhook import WebhookChannel

logger = logging.getLogger(__name__)


class NotificationManager:
    """
    Single entry point for sending notifications.
    """

    CHANNELS: dict[str, type[BaseChannel]] = {
        "email": EmailChannel,
        "in_app": InAppChannel,
        "webhook": WebhookChannel,
    }

    async def notify(self, context: NotificationContext) -> None:
        async with AsyncSessionLocal() as db:
            tenant = await db.scalar(
                select(Tenant).where(Tenant.id == context.tenant_id)
            )

        if not tenant:
            logger.warning(f"notify() called for unknown tenant {context.tenant_id}")
            return

        await self._dispatch(context, tenant)

    async def _dispatch(self, context: NotificationContext, tenant: Tenant) -> None:
        for name, channel_cls in self.CHANNELS.items():
            channel = channel_cls()
            await self._safe_send(name, channel.send(context, tenant))

    @staticmethod
    async def _safe_send(channel_name: str, coro) -> None:
        try:
            await coro
        except Exception:
            logger.exception(f"Notification channel '{channel_name}' failed")


notification_manager = NotificationManager()
