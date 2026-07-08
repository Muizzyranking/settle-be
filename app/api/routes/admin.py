import asyncio

from fastapi import APIRouter, Depends, Header, HTTPException

from app.core.config import settings
from app.services.nomba.admin import nomba_admin

router = APIRouter()


async def _verify_admin_key(x_admin_key: str = Header(alias="x-admin-key")) -> None:
    if not settings.ADMIN_API_KEY:
        raise HTTPException(status_code=503, detail="Admin API key not configured")
    if x_admin_key != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")


@router.get("/parent-account")
async def admin_parent_account(_=Depends(_verify_admin_key)):
    balance = await nomba_admin.get_parent_account_balance()
    return {
        "account_id": settings.NOMBA_ACCOUNT_ID,
        "balance": balance,
    }


@router.get("/sub-account")
async def admin_sub_account(
    _=Depends(_verify_admin_key),
):
    sub_account_id = settings.NOMBA_SUB_ACCOUNT_ID
    balance, details = await asyncio.gather(
        nomba_admin.get_sub_account_balance(sub_account_id),
        nomba_admin.get_sub_account_details(sub_account_id),
    )
    return {
        "account_id": sub_account_id,
        "balance": balance,
        **details,
    }
