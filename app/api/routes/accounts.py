import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentTenant, DBSession
from app.models.account import VirtualAccount
from app.schemas.account import (
    AccountDetailOut,
    AccountOut,
    BulkCreateAccountsRequest,
    BulkCreateAccountsResponse,
    BulkResultItem,
    CreateAccountRequest,
    UpdateAccountRequest,
)
from app.services.account_detail import build_account_detail
from app.services.account_provisioning import (
    AccountProvisioningError,
    DuplicateCustomerRefError,
    provision_account,
    suspend_account,
)

router = APIRouter()


@router.post("", response_model=AccountOut, status_code=201)
async def create_account(
    payload: CreateAccountRequest,
    db: DBSession,
    tenant: CurrentTenant,
):
    try:
        account = await provision_account(
            db,
            tenant_id=tenant.id,
            customer_name=payload.customer_name,
            customer_ref=payload.customer_ref,
            customer_email=payload.customer_email,
            customer_phone=payload.customer_phone,
            collection_id=payload.collection_id,
            expected_amount=payload.expected_amount,
            description=payload.description,
            expires_at=payload.expires_at,
        )
    except DuplicateCustomerRefError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AccountProvisioningError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return account


@router.post("/bulk", response_model=BulkCreateAccountsResponse, status_code=207)
async def bulk_create_accounts(
    payload: BulkCreateAccountsRequest,
    db: DBSession,
    tenant: CurrentTenant,
):
    results: list[BulkResultItem] = []

    for item in payload.accounts:
        try:
            account = await provision_account(
                db,
                tenant_id=tenant.id,
                customer_name=item.customer_name,
                customer_ref=item.customer_ref,
                customer_email=item.customer_email,
                customer_phone=item.customer_phone,
                collection_id=payload.collection_id,
                expected_amount=item.expected_amount,
                description=item.description,
            )
            results.append(
                BulkResultItem(
                    customer_ref=item.customer_ref,
                    status="success",
                    account=AccountOut.model_validate(account),
                )
            )
        except DuplicateCustomerRefError as exc:
            results.append(
                BulkResultItem(
                    customer_ref=item.customer_ref, status="error", error=str(exc)
                )
            )
        except AccountProvisioningError as exc:
            results.append(
                BulkResultItem(
                    customer_ref=item.customer_ref, status="error", error=exc.message
                )
            )

    succeeded = sum(1 for r in results if r.status == "success")
    return BulkCreateAccountsResponse(
        results=results,
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
    )


@router.get("", response_model=list[AccountOut])
async def list_accounts(
    db: DBSession,
    tenant: CurrentTenant,
    collection_id: uuid.UUID | None = None,
):
    query = select(VirtualAccount).where(VirtualAccount.tenant_id == tenant.id)
    if collection_id:
        query = query.where(VirtualAccount.collection_id == collection_id)
    accounts = await db.scalars(query)
    return accounts.all()


@router.get("/{account_id}", response_model=AccountDetailOut)
async def get_account(
    account_id: uuid.UUID,
    db: DBSession,
    tenant: CurrentTenant,
):
    account = await db.scalar(
        select(VirtualAccount).where(
            VirtualAccount.id == account_id, VirtualAccount.tenant_id == tenant.id
        )
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    detail = await build_account_detail(db, account)
    return AccountDetailOut(**AccountOut.model_validate(account).model_dump(), **detail)


@router.patch("/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: uuid.UUID,
    payload: UpdateAccountRequest,
    db: DBSession,
    tenant: CurrentTenant,
):
    account = await db.scalar(
        select(VirtualAccount).where(
            VirtualAccount.id == account_id, VirtualAccount.tenant_id == tenant.id
        )
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    db.add(account)
    return account


@router.delete("/{account_id}", status_code=204)
async def delete_account(
    account_id: uuid.UUID,
    db: DBSession,
    tenant: CurrentTenant,
):
    account = await db.scalar(
        select(VirtualAccount).where(
            VirtualAccount.id == account_id, VirtualAccount.tenant_id == tenant.id
        )
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        await suspend_account(db, account)
    except AccountProvisioningError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
