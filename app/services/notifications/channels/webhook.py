import logging

import httpx

from app.services.notifications.channels.base import BaseChannel
from app.services.notifications.context import NotificationContext

logger = logging.getLogger(__name__)

FORWARD_TIMEOUT = 10


class WebhookChannel(BaseChannel):
    """Forwards the notification context to the tenant's registered webhook_url.
    Only invoked when the tenant has one configured — see _channels_for in manager.py."""

    async def send(self, context: NotificationContext, tenant) -> None:
        webhook_url = tenant.webhook_url
        if not webhook_url:
            logger.info(
                f"Tenant {tenant.id} has no webhook_url; skipping webhook notification"
            )
            return
        body = {
            "event": f"settle.{context.type}",
            "data": context.data,
        }
        try:
            async with httpx.AsyncClient(timeout=FORWARD_TIMEOUT) as client:
                response = await client.post(webhook_url, json=body)
                response.raise_for_status()
        except httpx.TimeoutException:
            logger.warning(f"Webhook notification timed out for {webhook_url}")
        except httpx.HTTPStatusError as exc:
            logger.warning(
                f"Webhook notification failed for {webhook_url} — {exc.response.status_code}"
            )
