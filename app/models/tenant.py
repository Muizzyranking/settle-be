import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import BaseModel

if TYPE_CHECKING:
    from app.models.account import VirtualAccount
    from app.models.auth_tokens import RefreshToken
    from app.models.collection import Collection
    from app.models.notification import Notification


class Tenant(BaseModel):
    __tablename__ = "tenants"

    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    # nullable — Google-only accounts have no password
    hashed_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # profile — optional at signup, completable in settings
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    business_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    hashed_api_key: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    api_key_prefix: Mapped[str | None] = mapped_column(String(12), nullable=True)

    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    is_email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    google_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    collections: Mapped[list["Collection"]] = relationship(
        "Collection", back_populates="tenant", cascade="all, delete-orphan"
    )
    accounts: Mapped[list["VirtualAccount"]] = relationship(
        "VirtualAccount", back_populates="tenant", cascade="all, delete-orphan"
    )
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification", back_populates="tenant", cascade="all, delete-orphan"
    )
    bank_accounts: Mapped[list["TenantBankAccount"]] = relationship(
        "TenantBankAccount", back_populates="tenant", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken", back_populates="tenant", cascade="all, delete-orphan"
    )


class TenantBankAccount(BaseModel):
    __tablename__ = "tenant_bank_accounts"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )

    account_number: Mapped[str] = mapped_column(String(20), nullable=False)
    account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    bank_code: Mapped[str] = mapped_column(String(20), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="bank_accounts")
