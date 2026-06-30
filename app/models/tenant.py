import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import BaseModel

if TYPE_CHECKING:
    from app.models.account import VirtualAccount
    from app.models.collection import Collection
    from app.models.notification import Notification


class Tenant(BaseModel):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    business_name: Mapped[str] = mapped_column(String(255), nullable=False)

    hashed_api_key: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    api_key_prefix: Mapped[str | None] = mapped_column(String(12), nullable=True)

    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

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
