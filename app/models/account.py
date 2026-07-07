import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import BaseModel

if TYPE_CHECKING:
    from app.models.collection import Collection
    from app.models.ledger import LedgerEntry
    from app.models.tenant import Tenant
    from app.models.transaction import Transaction


class VirtualAccount(BaseModel):
    __tablename__ = "virtual_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_ref", name="uq_tenant_customer_ref"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collections.id"), nullable=True, index=True
    )

    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    nomba_account_ref: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    bank_account_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bank_account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    expected_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    total_paid: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    payment_status: Mapped[str] = mapped_column(String(20), default="unpaid", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # recurrence (inherited from collection.recurrence, NULL if collection has none)
    last_paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="accounts")
    collection: Mapped["Collection | None"] = relationship(
        "Collection", back_populates="accounts"
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", back_populates="virtual_account", cascade="all, delete-orphan"
    )
    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(
        "LedgerEntry", back_populates="virtual_account", cascade="all, delete-orphan"
    )
