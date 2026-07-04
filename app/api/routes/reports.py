import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentTenant, DBSession
from app.models.account import VirtualAccount
from app.models.ledger import LedgerEntry
from app.models.transaction import Transaction, TransactionStatus
from app.schemas.reports import LedgerEntryOut, ReconciliationSummary, StatementOut

router = APIRouter()


@router.get("/accounts/{account_id}/statement", response_model=StatementOut)
async def get_statement(
    account_id: uuid.UUID,
    db: DBSession,
    tenant: CurrentTenant,
):
    account = await db.scalar(
        select(VirtualAccount).where(
            VirtualAccount.id == account_id,
            VirtualAccount.tenant_id == tenant.id,
        )
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    entries = (
        await db.scalars(
            select(LedgerEntry)
            .where(LedgerEntry.virtual_account_id == account_id)
            .order_by(LedgerEntry.created_at.asc())
        )
    ).all()

    closing_balance = float(entries[-1].running_balance) if entries else 0.0

    return StatementOut(
        customer_name=account.customer_name,
        customer_ref=account.customer_ref,
        bank_account_number=account.bank_account_number,
        opening_balance=0.0,
        closing_balance=closing_balance,
        entries=[
            LedgerEntryOut(
                date=e.created_at,
                type=e.entry_type,
                amount=float(e.amount),
                running_balance=float(e.running_balance),
                description=e.description,
            )
            for e in entries
        ],
    )


@router.get("/reconciliation", response_model=ReconciliationSummary)
async def reconciliation_report(
    db: DBSession,
    tenant: CurrentTenant,
    collection_id: uuid.UUID | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
):
    account_query = select(VirtualAccount).where(VirtualAccount.tenant_id == tenant.id)
    if collection_id:
        account_query = account_query.where(
            VirtualAccount.collection_id == collection_id
        )

    accounts = (await db.scalars(account_query)).all()
    account_ids = [a.id for a in accounts]

    txn_query = select(Transaction).where(
        Transaction.virtual_account_id.in_(account_ids)
    )
    if from_date:
        txn_query = txn_query.where(Transaction.paid_at >= from_date)
    if to_date:
        txn_query = txn_query.where(Transaction.paid_at <= to_date)

    transactions = (await db.scalars(txn_query)).all()

    status_counts = {s: 0 for s in TransactionStatus}
    for t in transactions:
        status_counts[t.status] = status_counts.get(t.status, 0) + 1

    amount_collected = sum(
        float(t.amount)
        for t in transactions
        if t.status != TransactionStatus.MISDIRECTED
    )
    amount_expected = sum(
        float(a.expected_amount) for a in accounts if a.expected_amount
    )

    # accounts with no transactions are "unpaid"
    paid_account_ids = {t.virtual_account_id for t in transactions}
    unpaid = sum(1 for a in accounts if a.id not in paid_account_ids)

    return ReconciliationSummary(
        period_from=from_date,
        period_to=to_date,
        total_accounts=len(accounts),
        exact=status_counts.get(TransactionStatus.EXACT, 0),
        overpaid=status_counts.get(TransactionStatus.OVERPAID, 0),
        underpaid=status_counts.get(TransactionStatus.UNDERPAID, 0),
        unpaid=unpaid,
        misdirected=status_counts.get(TransactionStatus.MISDIRECTED, 0),
        amount_expected=amount_expected,
        amount_collected=amount_collected,
        amount_outstanding=max(amount_expected - amount_collected, 0.0),
    )


@router.get("/reconciliation/export")
async def export_reconciliation(
    db: DBSession,
    tenant: CurrentTenant,
    collection_id: uuid.UUID | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
):
    account_query = select(VirtualAccount).where(VirtualAccount.tenant_id == tenant.id)
    if collection_id:
        account_query = account_query.where(
            VirtualAccount.collection_id == collection_id
        )
    accounts = (await db.scalars(account_query)).all()
    account_map = {a.id: a for a in accounts}
    account_ids = list(account_map.keys())

    txn_query = select(Transaction).where(
        Transaction.virtual_account_id.in_(account_ids)
    )
    if from_date:
        txn_query = txn_query.where(Transaction.paid_at >= from_date)
    if to_date:
        txn_query = txn_query.where(Transaction.paid_at <= to_date)
    transactions = (await db.scalars(txn_query)).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "customer_name",
            "customer_ref",
            "bank_account_number",
            "expected_amount",
            "amount_paid",
            "status",
            "difference",
            "sender_name",
            "sender_bank",
            "paid_at",
        ]
    )

    for t in transactions:
        account = account_map.get(t.virtual_account_id)
        writer.writerow(
            [
                account.customer_name if account else "",
                account.customer_ref if account else "",
                account.bank_account_number if account else "",
                float(t.expected_amount) if t.expected_amount else "",
                float(t.amount),
                t.status.value,
                float(t.difference) if t.difference is not None else "",
                t.sender_account_name or "",
                t.sender_bank_name or "",
                t.paid_at.isoformat() if t.paid_at else "",
            ]
        )

    output.seek(0)
    filename = f"settle-reconciliation-{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
