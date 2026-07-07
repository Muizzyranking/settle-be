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
    virtual_account_id: uuid.UUID
    amount: float
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


class SavedBankAccountOut(BaseModel):
    id: uuid.UUID
    bank_name: str
    bank_code: str
    account_number: str
    account_name: str
    is_default: bool

    model_config = {"from_attributes": True}


class FinancePayoutOut(BaseModel):
    id: uuid.UUID
    amount: float
    fee: float
    destination: str
    status: str
    requested_at: datetime

    model_config = {"from_attributes": True}


class RefundCandidateOut(BaseModel):
    account_id: uuid.UUID
    customer_name: str
    collection_name: str
    overpaid_amount: float
    bank_account_number: str | None


class FinanceOverviewOut(BaseModel):
    available_balance: float
    pending_settlement: float
    total_withdrawn: float
    refundable_overpayments: float
    saved_bank_accounts: list[SavedBankAccountOut]
    recent_payouts: list[FinancePayoutOut]
    refund_candidates: list[RefundCandidateOut]
