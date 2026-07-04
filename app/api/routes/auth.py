from fastapi import APIRouter, BackgroundTasks, status
from fastapi.responses import RedirectResponse

from app.api.deps import CurrentTenant, DBSession
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegenerateApiKeyResponse,
    RegisterRequest,
    TenantPublic,
    TokenResponse,
    UpdateProfileRequest,
    WebhookUrlRequest,
    WebhookUrlResponse,
)
from app.services import auth_service

router = APIRouter()


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    db: DBSession,
    background_tasks: BackgroundTasks,
):
    tenant = await auth_service.register_tenant(payload, db, background_tasks)
    return {
        "message": "Registration successful. Please check your email to verify your account.",
        "email": tenant.email,
    }


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: DBSession):
    access_token, raw_refresh, tenant = await auth_service.authenticate_tenant(
        payload, db
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        tenant=TenantPublic.model_validate(tenant),
    )


@router.post("/verify-email")
async def verify_email(token: str, db: DBSession):
    await auth_service.verify_email(token, db)
    return {"message": "Email verified successfully. You can now log in."}


@router.post("/resend-verification")
async def resend_verification(
    email: str, background_tasks: BackgroundTasks, db: DBSession
):
    await auth_service.resend_verification(email, db, background_tasks)
    return {
        "message": "If that email exists and is unverified, a new link has been sent."
    }


@router.post("/forgot-password")
async def forgot_password(email: str, background_tasks: BackgroundTasks, db: DBSession):
    await auth_service.request_password_reset(email, db, background_tasks)
    return {"message": "If that email is registered, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(token: str, new_password: str, db: DBSession):
    await auth_service.reset_password(token, new_password, db)
    return {
        "message": "Password reset successful. Please log in with your new password."
    }


@router.get("/google")
async def google_login():
    """Redirects the browser to Google's OAuth consent screen."""
    return RedirectResponse(auth_service.build_google_auth_url())


@router.get("/google/callback")
async def google_callback(code: str, db: DBSession):
    """
    Google redirects here after the user approves. We exchange the code for
    user info, find or create the tenant, then issue a short-lived one-time
    code and redirect to the frontend, which exchanges it via /google/exchange —
    real tokens never touch the URL bar.
    """
    redirect_url = await auth_service.handle_google_callback(code, db)
    return RedirectResponse(redirect_url)


@router.post("/google/exchange", response_model=TokenResponse)
async def google_exchange(code: str, db: DBSession):
    """FE sends the one-time code from the URL param; we swap it for real tokens."""
    access_token, raw_refresh, tenant = await auth_service.exchange_google_code(
        code, db
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        tenant=TenantPublic.model_validate(tenant),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(payload: RefreshRequest, db: DBSession):
    access_token, raw_refresh, tenant = await auth_service.refresh_tokens(payload, db)
    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        tenant=TenantPublic.model_validate(tenant),
    )


@router.post("/logout-all")
async def logout_all(db: DBSession, tenant: CurrentTenant):
    await auth_service.logout_all_sessions(tenant, db)
    return {"message": "All sessions invalidated"}


@router.get("/me", response_model=TenantPublic)
async def get_me(tenant: CurrentTenant):
    return TenantPublic.model_validate(tenant)


@router.patch("/profile", response_model=TenantPublic)
async def update_profile(
    payload: UpdateProfileRequest, db: DBSession, tenant: CurrentTenant
):
    tenant = auth_service.update_tenant_profile(payload, tenant, db)
    return TenantPublic.model_validate(tenant)


@router.post("/api-key/generate", response_model=RegenerateApiKeyResponse)
async def generate_api_key_endpoint(db: DBSession, tenant: CurrentTenant):
    """Generates an API key on explicit request only — not auto-created at registration."""
    raw_key, prefix = auth_service.issue_new_api_key(tenant, db)
    return RegenerateApiKeyResponse(api_key=raw_key, api_key_prefix=prefix)


@router.post("/api-key/regenerate", response_model=RegenerateApiKeyResponse)
async def regenerate_api_key(db: DBSession, tenant: CurrentTenant):
    """Replaces an existing API key. Old key is immediately invalidated."""
    raw_key, prefix = auth_service.issue_new_api_key(tenant, db)
    return RegenerateApiKeyResponse(api_key=raw_key, api_key_prefix=prefix)


@router.patch("/webhook", response_model=WebhookUrlResponse)
async def set_webhook(payload: WebhookUrlRequest, db: DBSession, tenant: CurrentTenant):
    tenant = auth_service.update_webhook(payload, tenant, db)
    return WebhookUrlResponse(
        webhook_url=tenant.webhook_url, has_secret=bool(tenant.webhook_secret)
    )
