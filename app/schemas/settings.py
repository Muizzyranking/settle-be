import uuid
from datetime import datetime

from pydantic import BaseModel


class AddBankAccountRequest(BaseModel):
    account_number: str
    bank_code: str
    is_default: bool = False


class BankAccountOut(BaseModel):
    id: uuid.UUID
    account_number: str
    account_name: str
    bank_code: str
    bank_name: str
    is_default: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class BankOut(BaseModel):
    name: str
    code: str
    logo: str | None = None


class BankLookupRequest(BaseModel):
    account_number: str
    bank_code: str


class BankLookupResponse(BaseModel):
    account_number: str
    account_name: str
