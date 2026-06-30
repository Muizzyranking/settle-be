import json
import logging

from app.db.database import AsyncSessionLocal
from app.db.redis import get_redis
from app.models import Tenant
from app.models.notification import Notification
from app.services.notifications.channels.base import BaseChannel
from app.services.notifications.context import NotificationContext

logger = logging.getLogger(__name__)

SSE_CHANNEL_PREFIX = "settle:notifications:stream:"


class InAppChannel(BaseChannel):
    """Writes the notification to the DB and publishes it on a Redis pub/sub channel
    so any open SSE connection for that tenant receives it immediately."""

    async def send(self, context: NotificationContext, tenant: Tenant) -> None:
        async with AsyncSessionLocal() as db:
            notification = Notification(
                tenant_id=context.tenant_id,
                type=context.type,
                title=context.title,
                message=context.message,
                data=context.data,
            )
            db.add(notification)
            await db.commit()
            await db.refresh(notification)

        redis = get_redis()
        payload = {
            "id": str(notification.id),
            "type": notification.type,
            "title": notification.title,
            "message": notification.message,
            "data": notification.data,
            "created_at": notification.created_at.isoformat(),
        }
        await redis.publish(
            f"{SSE_CHANNEL_PREFIX}{context.tenant_id}", json.dumps(payload)
        )
