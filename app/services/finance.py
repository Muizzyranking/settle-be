import json
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db.redis import get_redis
from app.models.account import VirtualAccount
from app.models.ledger import LedgerEntry
from app.models.payout import Payout
from app.models.tenant import Tenant, TenantBankAccount

logger = logging.getLogger(__name__)

CACHE_TTL = 60


async def get_cached_or_fetch(cache_key: str, fetch_fn, ttl: int = CACHE_TTL):
    redis = get_redis()
    cached = await redis.get(cache_key)
    if cached is not None:
        return json.loads(cached)

    result = await fetch_fn()
    await redis.setex(cache_key, ttl, json.dumps(result))
    return result


async def _get_recent_payouts(
    db: AsyncSession, tenant_id, limit: int = 20
) -> list[dict]:
    stmt = (
        select(Payout)
        .where(Payout.tenant_id == tenant_id)
        .order_by(Payout.requested_at.desc())
        .limit(limit)
    )
    rows = await db.scalars(stmt)
    return [
        {
            "id": str(p.id),
            "amount": float(p.amount),
            "fee": float(p.fee),
            "destination": p.destination_account_number,
            "status": p.status,
            "requested_at": p.requested_at.isoformat(),
        }
        for p in rows
    ]


async def _get_refund_candidates(
    db: AsyncSession, tenant_id
) -> tuple[list[dict], float]:
    stmt = (
        select(VirtualAccount)
        .options(joinedload(VirtualAccount.collection))
        .where(
            VirtualAccount.tenant_id == tenant_id,
            VirtualAccount.payment_status == "overpaid",
            VirtualAccount.expected_amount.isnot(None),
        )
    )
    accounts = await db.scalars(stmt)
    accounts = accounts.unique()

    candidates = []
    total_overpaid = 0.0

    for acc in accounts:
        expected = float(acc.expected_amount or "0")
        total_paid = float(acc.total_paid)
        overpaid = max(0.0, total_paid - expected)
        if overpaid <= 0:
            continue

        collection_name = acc.collection.name if acc.collection else ""
        candidates.append(
            {
                "account_id": str(acc.id),
                "customer_name": acc.customer_name,
                "collection_name": collection_name,
                "overpaid_amount": overpaid,
                "bank_account_number": acc.bank_account_number,
            }
        )
        total_overpaid += overpaid

    return candidates, total_overpaid


async def _get_total_collected(db: AsyncSession, tenant_id) -> float:
    account_ids = await db.scalars(
        select(VirtualAccount.id).where(VirtualAccount.tenant_id == tenant_id)
    )
    ids = account_ids.all()
    if not ids:
        return 0.0

    total = 0.0
    for aid in ids:
        bal = await db.scalar(
            select(LedgerEntry.running_balance)
            .where(LedgerEntry.virtual_account_id == aid)
            .order_by(LedgerEntry.created_at.desc())
            .limit(1)
        )
        total += float(bal) if bal is not None else 0.0
    return total


async def _get_available_balance(db: AsyncSession, tenant_id) -> float:
    collected = await _get_total_collected(db, tenant_id)

    withdrawn = await db.scalar(
        select(func.coalesce(func.sum(Payout.amount), 0)).where(
            Payout.tenant_id == tenant_id, Payout.status == "paid"
        )
    ) or 0.0

    refunded = await db.scalar(
        select(func.coalesce(func.sum(Payout.amount), 0)).where(
            Payout.tenant_id == tenant_id, Payout.status == "refunded"
        )
    ) or 0.0

    return float(collected) - float(withdrawn) + float(refunded)


async def _get_total_withdrawn(db: AsyncSession, tenant_id) -> float:
    total = await db.scalar(
        select(func.coalesce(func.sum(Payout.amount), 0)).where(
            Payout.tenant_id == tenant_id, Payout.status == "paid"
        )
    )
    return float(total or 0.0)


def _overview_cache_key(tenant_id) -> str:
    return f"settle:finance:overview:{tenant_id}"


async def build_finance_overview(db: AsyncSession, tenant: Tenant) -> dict:
    cache_key = _overview_cache_key(tenant.id)

    async def fetch():
        bank_account_rows = await db.scalars(
            select(TenantBankAccount).where(TenantBankAccount.tenant_id == tenant.id)
        )
        saved_bank_accounts = [
            {
                "id": str(b.id),
                "bank_name": b.bank_name,
                "bank_code": b.bank_code,
                "account_number": b.account_number,
                "account_name": b.account_name,
                "is_default": b.is_default,
            }
            for b in bank_account_rows
        ]

        recent_payouts = await _get_recent_payouts(db, tenant.id)
        refund_candidates, refundable_overpayments = await _get_refund_candidates(
            db, tenant.id
        )
        available_balance = await _get_available_balance(db, tenant.id)
        total_withdrawn = await _get_total_withdrawn(db, tenant.id)

        return {
            "available_balance": available_balance,
            "pending_settlement": 0.0,
            "total_withdrawn": total_withdrawn,
            "refundable_overpayments": refundable_overpayments,
            "saved_bank_accounts": saved_bank_accounts,
            "recent_payouts": recent_payouts,
            "refund_candidates": refund_candidates,
        }

    return await get_cached_or_fetch(cache_key, fetch)


async def build_payouts_list(db: AsyncSession, tenant: Tenant) -> list[dict]:
    return await _get_recent_payouts(db, tenant.id, limit=50)
