import hashlib
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_access_token,
    generate_api_key,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.auth_tokens import (
    EmailVerificationToken,
    GoogleOAuthCode,
    PasswordResetToken,
    RefreshToken,
)
from app.models.tenant import Tenant
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    UpdateProfileRequest,
    WebhookUrlRequest,
)
from app.services.email_service import email_service

EMAIL_VERIFY_EXPIRE_HOURS = 24
RESET_TOKEN_EXPIRE_HOURS = 1
GOOGLE_OAUTH_CODE_EXPIRE_MINUTES = 5


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def _issue_tokens(tenant: Tenant, db: AsyncSession) -> tuple[str, str]:
    access_token = create_access_token(
        subject=str(tenant.id), token_version=tenant.token_version
    )
    raw_refresh, refresh_hash = generate_refresh_token()
    db.add(
        RefreshToken(
            tenant_id=tenant.id,
            token_hash=refresh_hash,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    return access_token, raw_refresh


async def _create_verification_token(tenant: Tenant, db: AsyncSession) -> str:
    raw_token = secrets.token_urlsafe(32)
    db.add(
        EmailVerificationToken(
            tenant_id=tenant.id,
            token_hash=_hash_token(raw_token),
            expires_at=datetime.now(timezone.utc)
            + timedelta(hours=EMAIL_VERIFY_EXPIRE_HOURS),
        )
    )
    await db.flush()
    return raw_token


def _queue_verification_email(
    background_tasks: BackgroundTasks, tenant: Tenant, raw_token: str
) -> None:
    verify_url = f"{settings.FRONTEND_URL}/verify-email?token={raw_token}"
    background_tasks.add_task(
        email_service.send,
        to=tenant.email,
        subject="Verify your Settle account",
        template="verification",
        context={
            "name": tenant.first_name or tenant.business_name,
            "verify_url": verify_url,
        },
    )


def _queue_password_reset_email(
    background_tasks: BackgroundTasks, tenant: Tenant, raw_token: str
) -> None:
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={raw_token}"
    background_tasks.add_task(
        email_service.send,
        to=tenant.email,
        subject="Reset your Settle password",
        template="password_reset",
        context={
            "name": tenant.first_name or tenant.business_name,
            "reset_url": reset_url,
        },
    )


async def register_tenant(
    payload: RegisterRequest, db: AsyncSession, background_tasks: BackgroundTasks
) -> Tenant:
    existing = await db.scalar(select(Tenant).where(Tenant.email == payload.email))
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    tenant = Tenant(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        business_name=payload.business_name,
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone_number=payload.phone_number,
    )
    db.add(tenant)
    await db.flush()

    raw_token = await _create_verification_token(tenant, db)
    _queue_verification_email(background_tasks, tenant, raw_token)

    return tenant


async def authenticate_tenant(
    payload: LoginRequest, db: AsyncSession
) -> tuple[str, str, Tenant]:
    tenant = await db.scalar(select(Tenant).where(Tenant.email == payload.email))
    if not tenant or not verify_password(
        payload.password, tenant.hashed_password or ""
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not tenant.is_email_verified:
        raise HTTPException(
            status_code=403,
            detail="Email not verified. Check your inbox or request a new verification email.",
        )

    access_token, raw_refresh = await _issue_tokens(tenant, db)
    return access_token, raw_refresh, tenant


async def verify_email(token: str, db: AsyncSession) -> None:
    token_hash = _hash_token(token)
    record = await db.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash,
            EmailVerificationToken.is_used == False,  # noqa: E712
        )
    )
    if not record:
        raise HTTPException(
            status_code=400, detail="Invalid or already used verification link"
        )
    if record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Verification link has expired")

    tenant = await db.get(Tenant, record.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Account not found")

    tenant.is_email_verified = True
    record.is_used = True
    db.add(tenant)
    db.add(record)


async def resend_verification(
    email: str, db: AsyncSession, background_tasks: BackgroundTasks
) -> None:
    tenant = await db.scalar(select(Tenant).where(Tenant.email == email))
    if not tenant or tenant.is_email_verified:
        return

    # rate limit: check if a token was issued in the last 2 minutes
    recent = await db.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.tenant_id == tenant.id,
            EmailVerificationToken.is_used == False,  # noqa: E712
            EmailVerificationToken.created_at
            >= datetime.now(timezone.utc) - timedelta(minutes=2),
        )
    )
    if recent:
        raise HTTPException(
            status_code=429,
            detail="Please wait before requesting another verification email",
        )

    raw_token = await _create_verification_token(tenant, db)
    _queue_verification_email(background_tasks, tenant, raw_token)


# ---------------------------------------------------------------------------
# Password Reset
# ---------------------------------------------------------------------------


async def request_password_reset(
    email: str, db: AsyncSession, background_tasks: BackgroundTasks
) -> None:
    tenant = await db.scalar(select(Tenant).where(Tenant.email == email))
    if not tenant or not tenant.hashed_password:
        return

    raw_token = secrets.token_urlsafe(32)
    db.add(
        PasswordResetToken(
            tenant_id=tenant.id,
            token_hash=_hash_token(raw_token),
            expires_at=datetime.now(timezone.utc)
            + timedelta(hours=RESET_TOKEN_EXPIRE_HOURS),
        )
    )
    await db.flush()
    _queue_password_reset_email(background_tasks, tenant, raw_token)


async def reset_password(token: str, new_password: str, db: AsyncSession) -> None:
    token_hash = _hash_token(token)
    record = await db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.is_used == False,  # noqa: E712
        )
    )
    if not record:
        raise HTTPException(
            status_code=400, detail="Invalid or already used reset link"
        )
    if record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Reset link has expired")

    tenant = await db.get(Tenant, record.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Account not found")

    tenant.hashed_password = hash_password(new_password)
    tenant.token_version += 1  # invalidate all existing sessions
    record.is_used = True
    db.add(tenant)
    db.add(record)


def build_google_auth_url() -> str:
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")

    params = urllib.parse.urlencode(
        {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "select_account",
        }
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"


async def handle_google_callback(code: str, db: AsyncSession) -> str:
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")

    async with httpx.AsyncClient(timeout=15) as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        if token_res.status_code != 200:
            return f"{settings.FRONTEND_URL}/login?error=google_failed"

        token_data = token_res.json()
        userinfo_res = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
        if userinfo_res.status_code != 200:
            return f"{settings.FRONTEND_URL}/login?error=google_failed"

        userinfo = userinfo_res.json()

    google_id = userinfo["id"]
    email = userinfo.get("email", "")
    first_name = userinfo.get("given_name", "")
    last_name = userinfo.get("family_name", "")

    tenant = await db.scalar(select(Tenant).where(Tenant.google_id == google_id))
    if not tenant:
        tenant = await db.scalar(select(Tenant).where(Tenant.email == email))
        if tenant:
            tenant.google_id = google_id
        else:
            tenant = Tenant(
                email=email,
                business_name=f"{first_name} {last_name}".strip() or email,
                first_name=first_name,
                last_name=last_name,
                google_id=google_id,
                is_email_verified=True,
            )
            db.add(tenant)
            await db.flush()

    tenant.is_email_verified = True
    db.add(tenant)
    await db.flush()

    raw_code = secrets.token_urlsafe(32)
    db.add(
        GoogleOAuthCode(
            tenant_id=tenant.id,
            code_hash=_hash_token(raw_code),
            expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=GOOGLE_OAUTH_CODE_EXPIRE_MINUTES),
        )
    )

    return f"{settings.FRONTEND_URL}/auth/google/callback?code={raw_code}"


async def exchange_google_code(code: str, db: AsyncSession) -> tuple[str, str, Tenant]:
    code_hash = _hash_token(code)
    record = await db.scalar(
        select(GoogleOAuthCode).where(
            GoogleOAuthCode.code_hash == code_hash,
            GoogleOAuthCode.is_used == False,  # noqa: E712
        )
    )
    if not record:
        raise HTTPException(
            status_code=400, detail="Invalid or already used OAuth code"
        )
    if record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="OAuth code has expired")

    record.is_used = True
    db.add(record)

    tenant = await db.get(Tenant, record.tenant_id)
    if not tenant or not tenant.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    access_token, raw_refresh = await _issue_tokens(tenant, db)
    return access_token, raw_refresh, tenant


async def refresh_tokens(
    payload: RefreshRequest, db: AsyncSession
) -> tuple[str, str, Tenant]:
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = await db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.is_revoked == False,  # noqa: E712
        )
    )
    if not stored:
        raise HTTPException(status_code=401, detail="Invalid or revoked refresh token")
    if stored.expires_at < datetime.now(timezone.utc):
        stored.is_revoked = True
        db.add(stored)
        raise HTTPException(status_code=401, detail="Refresh token expired")

    stored.is_revoked = True
    db.add(stored)

    tenant = await db.get(Tenant, stored.tenant_id)
    if not tenant or not tenant.is_active:
        raise HTTPException(status_code=401, detail="Tenant not found or inactive")

    access_token, raw_refresh = await _issue_tokens(tenant, db)
    return access_token, raw_refresh, tenant


async def logout_all_sessions(tenant: Tenant, db: AsyncSession) -> None:
    tenant.token_version += 1
    db.add(tenant)
    tokens = await db.scalars(
        select(RefreshToken).where(
            RefreshToken.tenant_id == tenant.id,
            RefreshToken.is_revoked == False,  # noqa: E712
        )
    )
    for t in tokens.all():
        t.is_revoked = True
        db.add(t)


def update_tenant_profile(
    payload: UpdateProfileRequest, tenant: Tenant, db: AsyncSession
) -> Tenant:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(tenant, field, value)
    db.add(tenant)
    return tenant


def issue_new_api_key(tenant: Tenant, db: AsyncSession) -> tuple[str, str]:
    """Used for both first-time generation and regeneration — old key is invalidated either way."""
    api_key_res = generate_api_key()
    prefix = api_key_res.api_key_prefix
    tenant.hashed_api_key = api_key_res.hashed_key
    tenant.api_key_prefix = prefix
    db.add(tenant)
    return api_key_res.raw_key, prefix


def update_webhook(
    payload: WebhookUrlRequest, tenant: Tenant, db: AsyncSession
) -> Tenant:
    tenant.webhook_url = payload.webhook_url
    if payload.webhook_secret is not None:
        tenant.webhook_secret = payload.webhook_secret
    db.add(tenant)
    return tenant
