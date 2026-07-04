from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import CurrentTenant, DBSession
from app.models.account import VirtualAccount
from app.models.collection import Collection
from app.models.ledger import LedgerEntry
from app.models.transaction import Transaction
from app.schemas.finance import DashboardStats

router = APIRouter()


@router.get("", response_model=DashboardStats)
async def dashboard(
    db: DBSession,
    tenant: CurrentTenant,
):
    now = datetime.now(timezone.utc)

    total_collections = await db.scalar(
        select(func.count(Collection.id)).where(
            Collection.tenant_id == tenant.id,
            Collection.is_active == True,  # noqa: E712
        )
    )

    tenant_account_ids = (
        await db.scalars(
            select(VirtualAccount.id).where(VirtualAccount.tenant_id == tenant.id)
        )
    ).all()

    total_accounts = len(tenant_account_ids)

    total_transactions = (
        await db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.virtual_account_id.in_(tenant_account_ids)
            )
        )
        or 0
    )

    # total collected = sum of all latest running balances per account
    total_collected = 0.0
    total_outstanding = 0.0
    total_overdue_accounts = 0

    accounts = (
        await db.scalars(
            select(VirtualAccount).where(VirtualAccount.tenant_id == tenant.id)
        )
    ).all()

    for account in accounts:
        balance_row = await db.scalar(
            select(LedgerEntry.running_balance)
            .where(LedgerEntry.virtual_account_id == account.id)
            .order_by(LedgerEntry.created_at.desc())
            .limit(1)
        )
        balance = float(balance_row) if balance_row else 0.0
        total_collected += balance

        if account.expected_amount:
            shortfall = float(account.expected_amount) - balance
            if shortfall > 0:
                total_outstanding += shortfall

        if account.next_due_date and now > account.next_due_date:
            total_overdue_accounts += 1

    # 10 most recent transactions across all accounts
    recent_txns = (
        await db.scalars(
            select(Transaction)
            .where(Transaction.virtual_account_id.in_(tenant_account_ids))
            .order_by(Transaction.created_at.desc())
            .limit(10)
        )
    ).all()

    recent = [
        {
            "id": str(t.id),
            "amount": float(t.amount),
            "status": t.status.value,
            "sender_name": t.sender_account_name,
            "paid_at": t.paid_at.isoformat() if t.paid_at else None,
        }
        for t in recent_txns
    ]

    return DashboardStats(
        total_collections=total_collections or 0,
        total_accounts=total_accounts,
        total_transactions=total_transactions,
        total_collected=total_collected,
        total_outstanding=total_outstanding,
        total_overdue_accounts=total_overdue_accounts,
        recent_transactions=recent,
    )
