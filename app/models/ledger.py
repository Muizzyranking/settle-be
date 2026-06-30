import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import BaseModel

if TYPE_CHECKING:
    from app.models.account import VirtualAccount


class LedgerEntryType(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"


class LedgerEntry(BaseModel):
    __tablename__ = "ledger_entries"

    virtual_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("virtual_accounts.id"),
        nullable=False,
        index=True,
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    entry_type: Mapped[LedgerEntryType] = mapped_column(String(10), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    running_balance: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    virtual_account: Mapped["VirtualAccount"] = relationship(
        "VirtualAccount", back_populates="ledger_entries"
    )
