import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.transaction import TransactionStatus


class TransactionOut(BaseModel):
    id: uuid.UUID
    virtual_account_id: uuid.UUID | None
    nomba_transaction_ref: str
    amount: float
    currency: str
    sender_account_number: str | None
    sender_account_name: str | None
    sender_bank_name: str | None
    narration: str | None
    status: TransactionStatus
    expected_amount: float | None
    difference: float | None
    paid_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TransactionListResponse(BaseModel):
    data: list[TransactionOut]
    total: int
    page: int
    limit: int
