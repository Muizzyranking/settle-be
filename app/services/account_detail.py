from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import VirtualAccount
from app.models.ledger import LedgerEntry
from app.services.recurrence import get_due_status


async def get_account_balance(db: AsyncSession, account_id) -> float:
    balance = await db.scalar(
        select(LedgerEntry.running_balance)
        .where(LedgerEntry.virtual_account_id == account_id)
        .order_by(LedgerEntry.created_at.desc())
        .limit(1)
    )
    return float(balance) if balance else 0.0


def derive_payment_status(balance: float, expected_amount: float | None) -> str:
    if expected_amount is None:
        return "unmatched" if balance == 0 else "received"
    if balance == 0:
        return "unpaid"
    if balance < expected_amount:
        return "underpaid"
    if balance > expected_amount:
        return "overpaid"
    return "exact"


async def build_account_detail(db: AsyncSession, account: VirtualAccount) -> dict:
    balance = await get_account_balance(db, account.id)
    expected = float(account.expected_amount) if account.expected_amount else None
    due_status = get_due_status(account.last_paid_at, account.next_due_date)

    return {
        "total_paid": balance,
        "balance": balance,
        "payment_status": derive_payment_status(balance, expected),
        "due_status": due_status.to_dict() if due_status else None,
    }
