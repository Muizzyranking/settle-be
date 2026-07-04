import uuid

from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    business_name: str
    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None


class UpdateProfileRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None
    business_name: str | None = None
    business_address: str | None = None
    business_type: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TenantPublic(BaseModel):
    id: uuid.UUID
    email: str
    business_name: str
    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None
    business_address: str | None = None
    business_type: str | None = None
    api_key_prefix: str | None = None
    webhook_url: str | None = None

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    tenant: TenantPublic
    api_key: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class RegenerateApiKeyResponse(BaseModel):
    api_key: str
    api_key_prefix: str


class WebhookUrlRequest(BaseModel):
    webhook_url: str
    webhook_secret: str | None = None


class WebhookUrlResponse(BaseModel):
    webhook_url: str | None
    has_secret: bool = False
