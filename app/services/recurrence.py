from datetime import datetime, timezone

from dateutil.relativedelta import relativedelta

from app.models.collection import RecurrenceFrequency


def compute_next_due_date(
    from_date: datetime,
    frequency: RecurrenceFrequency,
    interval_days: int | None = None,
) -> datetime:
    """
    Pure function — no DB access. Computes the next due date from a given anchor date
    (either created_at on first provisioning, or last_paid_at after a qualifying payment).

    Uses relativedelta for weekly/monthly so calendar months behave correctly
    (Jan 31 -> Feb 28/29, not an overflow into March).
    """
    if frequency == RecurrenceFrequency.WEEKLY:
        return from_date + relativedelta(weeks=1)
    if frequency == RecurrenceFrequency.MONTHLY:
        return from_date + relativedelta(months=1)
    if frequency == RecurrenceFrequency.CUSTOM:
        if not interval_days:
            raise ValueError("interval_days is required for custom frequency")
        return from_date + relativedelta(days=interval_days)
    raise ValueError(f"Unknown frequency: {frequency}")


class DueStatus:
    __slots__ = (
        "last_paid_at",
        "next_due_date",
        "is_overdue",
        "days_overdue",
        "days_until_due",
    )

    def __init__(
        self,
        last_paid_at: datetime | None,
        next_due_date: datetime | None,
        is_overdue: bool,
        days_overdue: int | None,
        days_until_due: int | None,
    ):
        self.last_paid_at = last_paid_at
        self.next_due_date = next_due_date
        self.is_overdue = is_overdue
        self.days_overdue = days_overdue
        self.days_until_due = days_until_due

    def to_dict(self) -> dict:
        return {
            "last_paid_at": self.last_paid_at,
            "next_due_date": self.next_due_date,
            "is_overdue": self.is_overdue,
            "days_overdue": self.days_overdue,
            "days_until_due": self.days_until_due,
        }


def get_due_status(
    last_paid_at: datetime | None, next_due_date: datetime | None
) -> DueStatus | None:
    """
    Derived at read time, never persisted. Returns None if the account has no recurrence
    (next_due_date is NULL), so callers can render `due_status: null` directly.
    """
    if next_due_date is None:
        return None

    now = datetime.now(timezone.utc)
    is_overdue = now > next_due_date

    return DueStatus(
        last_paid_at=last_paid_at,
        next_due_date=next_due_date,
        is_overdue=is_overdue,
        days_overdue=(now - next_due_date).days if is_overdue else None,
        days_until_due=(next_due_date - now).days if not is_overdue else None,
    )
