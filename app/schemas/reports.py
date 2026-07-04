from datetime import datetime

from pydantic import BaseModel


class LedgerEntryOut(BaseModel):
    date: datetime
    type: str
    amount: float
    running_balance: float
    description: str | None

    model_config = {"from_attributes": True}


class StatementOut(BaseModel):
    customer_name: str
    customer_ref: str
    bank_account_number: str | None
    opening_balance: float
    closing_balance: float
    entries: list[LedgerEntryOut]


class ReconciliationSummary(BaseModel):
    period_from: datetime | None
    period_to: datetime | None
    total_accounts: int
    exact: int
    overpaid: int
    underpaid: int
    unpaid: int
    misdirected: int
    amount_expected: float
    amount_collected: float
    amount_outstanding: float
