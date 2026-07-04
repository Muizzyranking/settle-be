import hashlib
import hmac
import json
import uuid

import httpx
from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.api.deps import CurrentTenant, DBSession
from app.core.config import settings
from app.models.tenant import TenantBankAccount
from app.schemas.settings import (
    AddBankAccountRequest,
    BankAccountOut,
    BankLookupRequest,
    BankLookupResponse,
    BankOut,
)
from app.services.nomba.accounts import nomba_accounts
from app.services.nomba.client import NombaAPIError

router = APIRouter()

MAX_BANK_ACCOUNTS = settings.MAX_BANK_ACCOUNTS


@router.get("/banks", response_model=list[BankOut])
async def list_banks(_: CurrentTenant):
    banks = await nomba_accounts.list_banks()
    return [BankOut(name=b["name"], code=b["code"], logo=b.get("logo")) for b in banks]


@router.post("/banks/lookup", response_model=BankLookupResponse)
async def lookup_bank_account(
    payload: BankLookupRequest,
    _: CurrentTenant,
):
    try:
        data = await nomba_accounts.lookup_bank_account(
            payload.account_number, payload.bank_code
        )
    except NombaAPIError as exc:
        raise HTTPException(
            status_code=400, detail=f"Bank lookup failed: {exc.detail}"
        ) from exc
    return BankLookupResponse(
        account_number=data["accountNumber"],
        account_name=data["accountName"],
    )


@router.get("/bank-accounts", response_model=list[BankAccountOut])
async def list_bank_accounts(
    db: DBSession,
    tenant: CurrentTenant,
):
    results = await db.scalars(
        select(TenantBankAccount)
        .where(TenantBankAccount.tenant_id == tenant.id)
        .order_by(
            TenantBankAccount.is_default.desc(), TenantBankAccount.created_at.asc()
        )
    )
    return results.all()


@router.post("/bank-accounts", response_model=BankAccountOut, status_code=201)
async def add_bank_account(
    payload: AddBankAccountRequest,
    db: DBSession,
    tenant: CurrentTenant,
):
    count = await db.scalar(
        select(func.count()).where(TenantBankAccount.tenant_id == tenant.id)
    )
    if (count or 0) >= MAX_BANK_ACCOUNTS:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum of {MAX_BANK_ACCOUNTS} saved bank accounts reached",
        )

    # look up account name via Nomba to verify and populate account_name
    try:
        lookup = await nomba_accounts.lookup_bank_account(
            payload.account_number, payload.bank_code
        )
    except NombaAPIError as exc:
        raise HTTPException(
            status_code=400, detail=f"Could not verify bank account: {exc.detail}"
        ) from exc

    # look up bank name from the bank list
    banks = await nomba_accounts.list_banks()
    bank_name = next(
        (b["name"] for b in banks if b["code"] == payload.bank_code), payload.bank_code
    )

    # if marking as default, unset existing default
    if payload.is_default:
        existing_defaults = await db.scalars(
            select(TenantBankAccount).where(
                TenantBankAccount.tenant_id == tenant.id,
                TenantBankAccount.is_default == True,  # noqa: E712
            )
        )
        for acct in existing_defaults.all():
            acct.is_default = False
            db.add(acct)

    bank_account = TenantBankAccount(
        tenant_id=tenant.id,
        account_number=payload.account_number,
        account_name=lookup["accountName"],
        bank_code=payload.bank_code,
        bank_name=bank_name,
        is_default=payload.is_default,
    )
    db.add(bank_account)
    await db.flush()
    return bank_account


@router.patch("/bank-accounts/{account_id}/set-default", response_model=BankAccountOut)
async def set_default_bank_account(
    account_id: uuid.UUID,
    db: DBSession,
    tenant: CurrentTenant,
):
    target = await db.scalar(
        select(TenantBankAccount).where(
            TenantBankAccount.id == account_id,
            TenantBankAccount.tenant_id == tenant.id,
        )
    )
    if not target:
        raise HTTPException(status_code=404, detail="Bank account not found")

    existing_defaults = await db.scalars(
        select(TenantBankAccount).where(
            TenantBankAccount.tenant_id == tenant.id,
            TenantBankAccount.is_default == True,  # noqa: E712
        )
    )
    for acct in existing_defaults.all():
        acct.is_default = False
        db.add(acct)

    target.is_default = True
    db.add(target)
    return target


@router.delete("/bank-accounts/{account_id}", status_code=204)
async def delete_bank_account(
    account_id: uuid.UUID,
    db: DBSession,
    tenant: CurrentTenant,
):
    target = await db.scalar(
        select(TenantBankAccount).where(
            TenantBankAccount.id == account_id,
            TenantBankAccount.tenant_id == tenant.id,
        )
    )
    if not target:
        raise HTTPException(status_code=404, detail="Bank account not found")
    await db.delete(target)


@router.post("/webhook/test")
async def test_webhook(
    tenant: CurrentTenant,
):
    """
    Sends a test payload to the tenant's registered webhook URL, signed with their
    webhook_secret (if set). Use this to verify your webhook endpoint is working.
    """
    if not tenant.webhook_url:
        raise HTTPException(status_code=400, detail="No webhook URL configured")

    test_payload = {
        "event": "settle.webhook.test",
        "data": {
            "message": "This is a test webhook from Settle.",
            "tenant_id": str(tenant.id),
            "business_name": tenant.business_name,
        },
    }
    payload_str = json.dumps(test_payload, separators=(",", ":"))

    headers = {"Content-Type": "application/json"}
    if tenant.webhook_secret:
        sig = hmac.new(
            tenant.webhook_secret.encode(), payload_str.encode(), hashlib.sha256
        ).hexdigest()
        headers["X-Settle-Signature"] = sig

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(
                tenant.webhook_url, content=payload_str, headers=headers
            )
        return {
            "delivered": res.status_code < 400,
            "status_code": res.status_code,
            "webhook_url": tenant.webhook_url,
            "signed": bool(tenant.webhook_secret),
        }
    except httpx.TimeoutException:
        return {
            "delivered": False,
            "error": "timeout",
            "webhook_url": tenant.webhook_url,
        }
    except Exception as exc:
        return {
            "delivered": False,
            "error": str(exc),
            "webhook_url": tenant.webhook_url,
        }
