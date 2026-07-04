import logging

from app.models import Tenant
from app.services.email_service import email_service
from app.services.notifications.channels.base import BaseChannel
from app.services.notifications.context import NotificationContext

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE = "notification"


class EmailChannel(BaseChannel):
    """Sends via Resend. No-ops quietly if RESEND_API_KEY isn't configured —
    lets the hackathon build run without email wired up yet."""

    async def send(self, context: NotificationContext, tenant: Tenant) -> None:

        to_email = context.data.get("to_email") or tenant.email

        if not to_email:
            logger.warning(
                f"Tenant {tenant.id} has no email address; skipping email notification"
            )
            return

        template = context.data.get("template", DEFAULT_TEMPLATE)
        template_context = {
            "title": context.title,
            "message": context.message,
            **{
                k: v
                for k, v in context.data.items()
                if k
                not in (
                    "template",
                    "to_email",
                )
            },
        }

        await email_service.send(
            to=to_email,
            subject=context.title,
            template=template,
            context=template_context,
        )
