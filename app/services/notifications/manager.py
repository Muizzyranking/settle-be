import logging
from enum import StrEnum

from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.models.tenant import Tenant
from app.services.notifications.channels.base import BaseChannel
from app.services.notifications.context import NotificationContext

from .channels.email import EmailChannel
from .channels.in_app import InAppChannel
from .channels.webhook import WebhookChannel

logger = logging.getLogger(__name__)


class NotificationChannel(StrEnum):
    EMAIL = "email"
    IN_APP = "in_app"
    WEBHOOK = "webhook"


ChannelSelector = NotificationChannel | list[NotificationChannel] | None


class NotificationManager:
    """
    Single entry point for sending notifications.
    """

    CHANNELS: dict[NotificationChannel, type[BaseChannel]] = {
        NotificationChannel.EMAIL: EmailChannel,
        NotificationChannel.IN_APP: InAppChannel,
        NotificationChannel.WEBHOOK: WebhookChannel,
    }

    async def notify(
        self, context: NotificationContext, channels: ChannelSelector = None
    ) -> None:
        async with AsyncSessionLocal() as db:
            tenant = await db.scalar(
                select(Tenant).where(Tenant.id == context.tenant_id)
            )

        if not tenant:
            logger.warning(f"notify() called for unknown tenant {context.tenant_id}")
            return

        await self._dispatch(context, tenant, self._get_channels(channels))

    def _get_channels(
        self, channels: ChannelSelector
    ) -> dict[NotificationChannel, type[BaseChannel]]:
        if channels is None:
            return self.CHANNELS
        requested = channels if isinstance(channels, list) else [channels]

        resolved: dict[NotificationChannel, type[BaseChannel]] = {}
        for name in requested:
            if name not in self.CHANNELS:
                logger.warning(f"Unknown notification channel requested: {name}")
                continue
            resolved[name] = self.CHANNELS[name]

        return resolved

    async def _dispatch(
        self,
        context: NotificationContext,
        tenant: Tenant,
        channels: dict[NotificationChannel, type[BaseChannel]],
    ) -> None:
        for name, channel_cls in channels.items():
            channel = channel_cls()
            coro = channel.send(context, tenant)
            await self._safe_send(name, coro)

    @staticmethod
    async def _safe_send(channel_name: str, coro) -> None:
        try:
            await coro
        except Exception:
            logger.exception(f"Notification channel '{channel_name}' failed")


notification_manager = NotificationManager()
