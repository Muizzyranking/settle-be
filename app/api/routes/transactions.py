import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import CurrentTenant, DBSession
from app.models.account import VirtualAccount
from app.models.transaction import Transaction, TransactionStatus
from app.schemas.transaction import TransactionListResponse, TransactionOut
from app.services.receipt import generate_receipt

router = APIRouter()


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    db: DBSession,
    tenant: CurrentTenant,
    page: int = 1,
    limit: int = 20,
    status: TransactionStatus | None = None,
    account_id: uuid.UUID | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
):
    tenant_account_ids = await db.scalars(
        select(VirtualAccount.id).where(VirtualAccount.tenant_id == tenant.id)
    )
    tenant_account_ids = list(tenant_account_ids.all())

    query = select(Transaction).where(
        Transaction.virtual_account_id.in_(tenant_account_ids)
    )

    if status:
        query = query.where(Transaction.status == status)
    if account_id:
        query = query.where(Transaction.virtual_account_id == account_id)
    if from_date:
        query = query.where(Transaction.paid_at >= from_date)
    if to_date:
        query = query.where(Transaction.paid_at <= to_date)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    results = await db.scalars(
        query.order_by(Transaction.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )

    return TransactionListResponse(
        data=[TransactionOut.model_validate(t) for t in results.all()],
        total=total or 0,
        page=page,
        limit=limit,
    )


@router.get("/misdirected", response_model=list[TransactionOut])
async def list_misdirected(
    db: DBSession,
    _: CurrentTenant,
):
    # misdirected transactions have no virtual_account_id — we can't scope them
    # to a tenant via a join, so we return all misdirected for now and flag this
    # as a known v1 limitation in the docs (only one Nomba account serves all tenants)
    results = await db.scalars(
        select(Transaction)
        .where(Transaction.status == TransactionStatus.MISDIRECTED)
        .order_by(Transaction.created_at.desc())
    )
    return [TransactionOut.model_validate(t) for t in results.all()]


@router.get("/{transaction_id}", response_model=TransactionOut)
async def get_transaction(
    transaction_id: uuid.UUID,
    db: DBSession,
    tenant: CurrentTenant,
):
    transaction = await db.get(Transaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # verify it belongs to this tenant
    if transaction.virtual_account_id:
        account = await db.get(VirtualAccount, transaction.virtual_account_id)
        if not account or account.tenant_id != tenant.id:
            raise HTTPException(status_code=404, detail="Transaction not found")

    return TransactionOut.model_validate(transaction)


@router.get("/accounts/{account_id}/transactions/{transaction_id}/receipt")
async def download_receipt(
    account_id: uuid.UUID,
    transaction_id: uuid.UUID,
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

    transaction = await db.get(Transaction, transaction_id)
    if not transaction or transaction.virtual_account_id != account_id:
        raise HTTPException(status_code=404, detail="Transaction not found")

    pdf_bytes = generate_receipt(
        tenant=tenant, account=account, transaction=transaction
    )

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=receipt-{transaction_id}.pdf"
        },
    )
