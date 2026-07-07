import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class CreateAccountRequest(BaseModel):
    customer_name: str
    customer_ref: str | None = None
    customer_email: EmailStr | None = None
    customer_phone: str | None = None
    collection_id: uuid.UUID | None = None
    expected_amount: float | None = None
    description: str | None = None
    expires_at: datetime | None = None


class UpdateAccountRequest(BaseModel):
    customer_email: EmailStr | None = None
    customer_phone: str | None = None
    expected_amount: float | None = None
    description: str | None = None


class DueStatusOut(BaseModel):
    last_paid_at: datetime | None
    next_due_date: datetime | None
    is_overdue: bool
    days_overdue: int | None
    days_until_due: int | None


class AccountOut(BaseModel):
    id: uuid.UUID
    customer_name: str
    customer_ref: str
    customer_email: str | None
    customer_phone: str | None
    bank_account_number: str | None
    bank_account_name: str | None
    bank_name: str | None
    expected_amount: float | None
    description: str | None
    is_active: bool
    next_due_date: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AccountDetailOut(AccountOut):
    total_paid: float
    balance: float
    payment_status: str
    due_status: DueStatusOut | None


class BulkAccountItem(BaseModel):
    customer_name: str
    customer_ref: str
    customer_email: EmailStr | None = None
    customer_phone: str | None = None
    expected_amount: float | None = None
    description: str | None = None


class BulkCreateAccountsRequest(BaseModel):
    collection_id: uuid.UUID | None = None
    accounts: list[BulkAccountItem]


class BulkResultItem(BaseModel):
    customer_ref: str
    status: str  # "success" | "error"
    account: AccountOut | None = None
    error: str | None = None


class BulkCreateAccountsResponse(BaseModel):
    results: list[BulkResultItem]
    total: int
    succeeded: int
    failed: int
