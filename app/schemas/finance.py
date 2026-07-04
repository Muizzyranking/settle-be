import uuid
from datetime import datetime

from pydantic import BaseModel


class DashboardStats(BaseModel):
    total_collections: int
    total_accounts: int
    total_transactions: int
    total_collected: float
    total_outstanding: float
    total_overdue_accounts: int
    recent_transactions: list[dict]


class WithdrawalRequest(BaseModel):
    amount: float
    bank_account_id: uuid.UUID
    note: str | None = None


class WithdrawalResponse(BaseModel):
    transaction_ref: str
    amount: float
    account_number: str
    account_name: str
    bank_name: str
    status: str
    initiated_at: datetime


class RefundRequest(BaseModel):
    virtual_account_id: uuid.UUID  # the overpaid account
    amount: float  # must not exceed the overpaid difference
    destination_account_number: str
    destination_bank_code: str
    note: str | None = None


class RefundResponse(BaseModel):
    transaction_ref: str
    amount: float
    destination_account_name: str
    destination_account_number: str
    status: str
    initiated_at: datetime
