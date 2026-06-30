import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import BaseModel

if TYPE_CHECKING:
    from app.models.account import VirtualAccount


class TransactionStatus(StrEnum):
    EXACT = "exact"
    OVERPAID = "overpaid"
    UNDERPAID = "underpaid"
    UNMATCHED = "unmatched"
    MISDIRECTED = "misdirected"


class Transaction(BaseModel):
    __tablename__ = "transactions"

    virtual_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("virtual_accounts.id"), nullable=True, index=True
    )

    nomba_transaction_ref: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    nomba_account_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="NGN", nullable=False)
    sender_account_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sender_account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    narration: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[TransactionStatus] = mapped_column(
        String(20), default=TransactionStatus.UNMATCHED, nullable=False
    )
    expected_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    difference: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)

    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    virtual_account: Mapped["VirtualAccount"] = relationship(
        "VirtualAccount", back_populates="transactions"
    )
