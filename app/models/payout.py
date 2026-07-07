import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import BaseModel


class Payout(BaseModel):
    __tablename__ = "payouts"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    fee: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    destination_account_number: Mapped[str] = mapped_column(String(20), nullable=False)
    destination_account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    destination_bank_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    transaction_ref: Mapped[str] = mapped_column(String(255), nullable=False)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
