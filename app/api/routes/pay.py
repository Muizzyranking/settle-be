import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.redis import get_redis
from app.models.account import VirtualAccount
from app.models.tenant import Tenant
from app.services.account_detail import derive_payment_status, get_account_balance
from app.services.recouncilation import ACCOUNT_STATUS_CHANNEL_PREFIX

router = APIRouter()


class PublicPaymentPageOut(BaseModel):
    customer_name: str
    bank_account_number: str | None
    bank_account_name: str | None
    bank_name: str | None
    expected_amount: float | None
    description: str | None
    payment_status: str
    next_due_date: datetime | None
    business_name: str


@router.get("/{account_id}", response_model=PublicPaymentPageOut)
async def payment_page(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    account = await db.scalar(
        select(VirtualAccount).where(
            VirtualAccount.id == account_id,
            VirtualAccount.is_active == True,  # noqa: E712
        )
    )
    if not account:
        raise HTTPException(status_code=404, detail="Payment page not found")

    tenant = await db.get(Tenant, account.tenant_id)
    balance = await get_account_balance(db, account.id)
    expected = float(account.expected_amount) if account.expected_amount else None

    return PublicPaymentPageOut(
        customer_name=account.customer_name,
        bank_account_number=account.bank_account_number,
        bank_account_name=account.bank_account_name,
        bank_name=account.bank_name,
        expected_amount=expected,
        description=account.description,
        payment_status=derive_payment_status(balance, expected),
        next_due_date=account.next_due_date,
        business_name=tenant.business_name if tenant else "",
    )


@router.get("/{account_id}/status/stream")
async def payment_status_stream(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Public SSE stream for the customer payment page. No auth required.
    The customer subscribes when they land on the payment page. The moment their
    transfer is reconciled, this stream pushes the result — exact, underpaid,
    overpaid — so the UI updates without polling.
    """
    account = await db.scalar(
        select(VirtualAccount).where(
            VirtualAccount.id == account_id,
            VirtualAccount.is_active == True,  # noqa: E712
        )
    )
    if not account:
        raise HTTPException(status_code=404, detail="Payment page not found")

    async def event_generator():
        redis = get_redis()
        pubsub = redis.pubsub()
        channel = f"{ACCOUNT_STATUS_CHANNEL_PREFIX}{account_id}"
        await pubsub.subscribe(channel)

        try:
            yield "retry: 3000\n\n"
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=30
                )
                if message and message["type"] == "message":
                    yield f"event: payment_update\ndata: {message['data']}\n\n"
                else:
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
