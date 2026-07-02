import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.account import VirtualAccount
from app.models.collection import Collection, RecurringSchedule
from app.models.ledger import LedgerEntry
from app.schemas.collection import RecurrenceIn


async def create_collection(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    name: str,
    description: str | None,
    expected_amount: float | None,
    recurrence: RecurrenceIn | None,
) -> Collection:
    collection = Collection(
        tenant_id=tenant_id,
        name=name,
        description=description,
        expected_amount=expected_amount,
    )
    db.add(collection)
    await db.flush()

    if recurrence:
        db.add(
            RecurringSchedule(
                collection_id=collection.id,
                frequency=recurrence.frequency,
                interval_days=recurrence.interval_days,
            )
        )
        await db.flush()
        await db.refresh(collection, attribute_names=["recurrence"])

    stmt = (
        select(Collection)
        .where(Collection.id == collection.id)
        .options(selectinload(Collection.recurrence))
    )
    result = await db.execute(stmt)
    collection = result.scalar_one()
    return collection


async def get_collection_stats(db: AsyncSession, collection: Collection) -> dict:
    accounts = (
        await db.scalars(
            select(VirtualAccount).where(VirtualAccount.collection_id == collection.id)
        )
    ).all()

    total_accounts = len(accounts)
    total_paid = total_unpaid = total_underpaid = total_overdue = 0
    amount_collected = 0.0

    now = datetime.now(timezone.utc)

    for account in accounts:
        balance = await db.scalar(
            select(LedgerEntry.running_balance)
            .where(LedgerEntry.virtual_account_id == account.id)
            .order_by(LedgerEntry.created_at.desc())
            .limit(1)
        )
        balance = float(balance) if balance else 0.0
        amount_collected += balance

        if account.expected_amount:
            expected = float(account.expected_amount)
            if balance >= expected:
                total_paid += 1
            elif balance > 0:
                total_underpaid += 1
            else:
                total_unpaid += 1

        if account.next_due_date and now > account.next_due_date:
            total_overdue += 1

    amount_expected = float(collection.expected_amount or 0) * total_accounts
    amount_outstanding = max(amount_expected - amount_collected, 0.0)

    return {
        "total_accounts": total_accounts,
        "total_paid": total_paid,
        "total_underpaid": total_underpaid,
        "total_unpaid": total_unpaid,
        "total_overdue": total_overdue,
        "amount_collected": amount_collected,
        "amount_outstanding": amount_outstanding,
    }
