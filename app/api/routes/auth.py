from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentTenant, DBSession
from app.core.security import (
    create_access_token,
    generate_api_key,
    hash_password,
    verify_password,
)
from app.db.database import get_db
from app.models.tenant import Tenant
from app.schemas.auth import (
    LoginRequest,
    RegenerateApiKeyResponse,
    RegisterRequest,
    TenantPublic,
    TokenResponse,
    WebhookUrlRequest,
    WebhookUrlResponse,
)

router = APIRouter()


@router.post(
    "/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED
)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.scalar(select(Tenant).where(Tenant.email == payload.email))
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    api_key_response = generate_api_key()
    raw_key = api_key_response.raw_key
    hashed_key = api_key_response.hashed_key
    prefix = api_key_response.api_key_prefix

    tenant = Tenant(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        business_name=payload.business_name,
        hashed_api_key=hashed_key,
        api_key_prefix=prefix,
    )
    db.add(tenant)
    await db.flush()

    token = create_access_token(subject=str(tenant.id))
    return TokenResponse(
        access_token=token,
        tenant=TenantPublic.model_validate(tenant),
        api_key=raw_key,
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    tenant = await db.scalar(select(Tenant).where(Tenant.email == payload.email))
    if not tenant or not verify_password(payload.password, tenant.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(subject=str(tenant.id))
    return TokenResponse(access_token=token, tenant=TenantPublic.model_validate(tenant))


@router.post("/api-key/regenerate", response_model=RegenerateApiKeyResponse)
async def regenerate_api_key(
    db: DBSession,
    tenant: CurrentTenant,
):
    api_key_response = generate_api_key()
    prefix = api_key_response.api_key_prefix

    tenant.hashed_api_key = api_key_response.hashed_key
    tenant.api_key_prefix = api_key_response.api_key_prefix
    db.add(tenant)
    return RegenerateApiKeyResponse(
        api_key=api_key_response.raw_key, api_key_prefix=prefix
    )


@router.post("/logout-all")
async def logout_all(
    db: DBSession,
    tenant: CurrentTenant,
):
    tenant.token_version += 1
    db.add(tenant)
    return {"message": "All sessions invalidated"}


@router.patch("/webhook", response_model=WebhookUrlResponse)
async def set_webhook_url(
    payload: WebhookUrlRequest,
    db: DBSession,
    tenant: CurrentTenant,
):
    tenant.webhook_url = payload.webhook_url
    db.add(tenant)
    return WebhookUrlResponse(webhook_url=tenant.webhook_url)
