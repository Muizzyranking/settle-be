import uuid

from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    business_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TenantPublic(BaseModel):
    id: uuid.UUID
    email: str
    business_name: str
    api_key_prefix: str | None = None

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant: TenantPublic
    api_key: str | None = None  # only present on register/regenerate, view-once


class RegenerateApiKeyResponse(BaseModel):
    api_key: str
    api_key_prefix: str


class WebhookUrlRequest(BaseModel):
    webhook_url: str


class WebhookUrlResponse(BaseModel):
    webhook_url: str | None
