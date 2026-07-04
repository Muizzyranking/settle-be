import asyncio
import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentTenant, DBSession, get_current_tenant
from app.core.security import decode_access_token
from app.db.database import get_db
from app.db.redis import get_redis
from app.models.notification import Notification
from app.models.tenant import Tenant
from app.schemas.notification import NotificationListResponse, NotificationOut
from app.services.notifications.channels.in_app import SSE_CHANNEL_PREFIX

router = APIRouter()


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    db: DBSession,
    tenant: CurrentTenant,
    page: int = 1,
    limit: int = 20,
    is_read: bool | None = None,
):
    query = select(Notification).where(Notification.tenant_id == tenant.id)
    if is_read is not None:
        query = query.where(Notification.is_read == is_read)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    unread_count = await db.scalar(
        select(func.count()).where(
            Notification.tenant_id == tenant.id,
            Notification.is_read == False,  # noqa: E712
        )
    )
    results = await db.scalars(
        query.order_by(Notification.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )

    return NotificationListResponse(
        data=[NotificationOut.model_validate(n) for n in results.all()],
        total=total or 0,
        unread_count=unread_count or 0,
    )


@router.patch("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    notification = await db.get(Notification, notification_id)
    if not notification or notification.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Notification not found")

    notification.is_read = True
    db.add(notification)
    return NotificationOut.model_validate(notification)


@router.patch("/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    await db.execute(
        update(Notification)
        .where(Notification.tenant_id == tenant.id, Notification.is_read == False)  # noqa: E712
        .values(is_read=True)
    )
    return {"message": "All notifications marked as read"}


@router.get("/stream")
async def notification_stream(token: str = Query(...)):
    """
    SSE stream. EventSource can't set headers so we accept the JWT as a query param.
    Subscribes to the tenant's Redis pub/sub channel and streams events as they arrive.
    """
    try:
        data = decode_access_token(token)
        tenant_id = data["sub"]
    except (jwt.PyJWTError, KeyError) as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    async def event_generator():
        redis = get_redis()
        pubsub = redis.pubsub()
        channel = f"{SSE_CHANNEL_PREFIX}{tenant_id}"
        await pubsub.subscribe(channel)

        try:
            yield "retry: 3000\n\n"
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=30
                )
                if message and message["type"] == "message":
                    yield f"event: notification\ndata: {message['data']}\n\n"
                else:
                    # keep-alive to prevent proxy/load-balancer timeouts
                    yield ": keep-alive\n\n"
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
