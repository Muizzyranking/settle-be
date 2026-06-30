import logging

import httpx

from app.core.config import settings
from app.models import Tenant
from app.services.notifications.channels.base import BaseChannel
from app.services.notifications.context import NotificationContext

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


class EmailChannel(BaseChannel):
    """Sends via Resend. No-ops quietly if RESEND_API_KEY isn't configured —
    lets the hackathon build run without email wired up yet."""

    async def send(self, context: NotificationContext, tenant: Tenant) -> None:
        if not settings.RESEND_API_KEY:
            return

        to_email = tenant.email

        if not to_email:
            logger.warning(
                f"Tenant {tenant.id} has no email address; skipping email notification"
            )
            return

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    RESEND_API_URL,
                    headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                    json={
                        "from": settings.EMAIL_FROM,
                        "to": [to_email],
                        "subject": context.title,
                        "html": f"<p>{context.message}</p>",
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning(f"Email notification failed for {to_email}: {exc}")
