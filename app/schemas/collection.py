import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.collection import RecurrenceFrequency


class RecurrenceIn(BaseModel):
    frequency: RecurrenceFrequency
    interval_days: int | None = None


class RecurrenceOut(BaseModel):
    frequency: RecurrenceFrequency
    interval_days: int | None

    model_config = {"from_attributes": True}


class CreateCollectionRequest(BaseModel):
    name: str
    description: str | None = None
    expected_amount: float | None = None
    recurrence: RecurrenceIn | None = None


class CollectionOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    expected_amount: float | None
    recurrence: RecurrenceOut | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CollectionStats(CollectionOut):
    total_accounts: int
    total_paid: int
    total_underpaid: int
    total_unpaid: int
    total_overdue: int
    amount_collected: float
    amount_outstanding: float
