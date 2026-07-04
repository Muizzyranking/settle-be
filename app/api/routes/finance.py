import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentTenant, DBSession, get_current_tenant
from app.db.database import get_db
from app.models.account import VirtualAccount
from app.models.ledger import LedgerEntry
from app.models.tenant import Tenant, TenantBankAccount
from app.schemas.finance import (
    RefundRequest,
    RefundResponse,
    WithdrawalRequest,
    WithdrawalResponse,
)
from app.services.nomba.accounts import nomba_accounts
from app.services.nomba.client import NombaAPIError

router = APIRouter()


@router.post("/withdraw", response_model=WithdrawalResponse)
async def withdraw(
    payload: WithdrawalRequest,
    db: DBSession,
    tenant: CurrentTenant,
):
    bank_account = await db.scalar(
        select(TenantBankAccount).where(
            TenantBankAccount.id == payload.bank_account_id,
            TenantBankAccount.tenant_id == tenant.id,
        )
    )
    if not bank_account:
        raise HTTPException(status_code=404, detail="Bank account not found")

    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")

    merchant_tx_ref = f"SETTLE-WD-{secrets.token_hex(8).upper()}"

    try:
        result = await nomba_accounts.transfer_to_bank(
            amount=payload.amount,
            account_number=bank_account.account_number,
            account_name=bank_account.account_name,
            bank_code=bank_account.bank_code,
            merchant_tx_ref=merchant_tx_ref,
            sender_name=tenant.business_name,
        )
    except NombaAPIError as exc:
        raise HTTPException(
            status_code=502, detail=f"Transfer failed: {exc.detail}"
        ) from exc

    return WithdrawalResponse(
        transaction_ref=result.get("id", merchant_tx_ref),
        amount=payload.amount,
        account_number=bank_account.account_number,
        account_name=bank_account.account_name,
        bank_name=bank_account.bank_name,
        status=result.get("status", "PENDING"),
        initiated_at=datetime.now(timezone.utc),
    )


@router.post("/refund", response_model=RefundResponse)
async def refund(
    payload: RefundRequest,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    account = await db.scalar(
        select(VirtualAccount).where(
            VirtualAccount.id == payload.virtual_account_id,
            VirtualAccount.tenant_id == tenant.id,
        )
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    balance_row = await db.scalar(
        select(LedgerEntry.running_balance)
        .where(LedgerEntry.virtual_account_id == account.id)
        .order_by(LedgerEntry.created_at.desc())
        .limit(1)
    )
    balance = float(balance_row) if balance_row else 0.0
    expected = float(account.expected_amount) if account.expected_amount else None

    if expected is None:
        raise HTTPException(
            status_code=400,
            detail="Account has no expected amount — cannot determine overpayment",
        )

    overpaid_by = balance - expected
    if overpaid_by <= 0:
        raise HTTPException(
            status_code=400, detail="Account is not overpaid — no refund applicable"
        )

    if payload.amount > overpaid_by:
        raise HTTPException(
            status_code=400,
            detail=f"Refund amount exceeds overpayment of ₦{overpaid_by:,.2f}",
        )

    try:
        lookup = await nomba_accounts.lookup_bank_account(
            payload.destination_account_number, payload.destination_bank_code
        )
    except NombaAPIError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not verify destination account: {exc.detail}",
        ) from exc

    merchant_tx_ref = f"SETTLE-RF-{secrets.token_hex(8).upper()}"

    try:
        result = await nomba_accounts.transfer_to_bank(
            amount=payload.amount,
            account_number=payload.destination_account_number,
            account_name=lookup["accountName"],
            bank_code=payload.destination_bank_code,
            merchant_tx_ref=merchant_tx_ref,
            sender_name=tenant.business_name,
        )
    except NombaAPIError as exc:
        raise HTTPException(
            status_code=502, detail=f"Refund transfer failed: {exc.detail}"
        ) from exc

    return RefundResponse(
        transaction_ref=result.get("id", merchant_tx_ref),
        amount=payload.amount,
        destination_account_name=lookup["accountName"],
        destination_account_number=payload.destination_account_number,
        status=result.get("status", "PENDING"),
        initiated_at=datetime.now(timezone.utc),
    )
