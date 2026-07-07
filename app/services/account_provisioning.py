import re
import secrets
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Collection
from app.models.account import VirtualAccount
from app.models.collection import RecurringSchedule
from app.services.nomba.accounts import nomba_accounts
from app.services.nomba.client import NombaAPIError
from app.services.notifications.notifications import notify_customer_payment_link
from app.services.recurrence import compute_next_due_date


class AccountProvisioningError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class DuplicateCustomerRefError(Exception):
    pass


async def _generate_unique_customer_ref(
    db: AsyncSession, tenant_id: uuid.UUID, max_attempts: int = 5
) -> str:
    """Generate a short, unique, tenant-scoped customer reference."""
    for _ in range(max_attempts):
        suffix = "".join(
            secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6)
        )
        candidate = f"CUST-{suffix}"

        exists = await db.scalar(
            select(VirtualAccount).where(
                VirtualAccount.tenant_id == tenant_id,
                VirtualAccount.customer_ref == candidate,
            )
        )
        if not exists:
            return candidate

    raise AccountProvisioningError(
        "Could not generate a unique customer_ref after multiple attempts"
    )


def build_nomba_account_ref(tenant_id: uuid.UUID, customer_ref: str) -> str:
    """
    Deterministic, unique across tenants.
    """
    short_tenant = str(tenant_id).split("-")[0]
    short_ref = customer_ref[:13].replace(" ", "-")
    short_unique = uuid.uuid4().hex[:8]
    ref = f"settle-{short_tenant}-{short_ref}-{short_unique}"
    if len(ref) < 16:
        ref = ref.ljust(16, "0")
    return ref[:64]


def _sanitize_account_name(name: str) -> str:
    """
    Clean a name so it is safe for bank APIs.
    - Strip whitespace
    - Remove brackets, emojis, and control characters
    - Allow letters, numbers, spaces, and common punctuation (- . / &)
    - Collapse multiple spaces
    """
    if not name:
        return "Customer"

    cleaned = name.strip()
    cleaned = re.sub(r"[\[\]{}<>]", "", cleaned)
    cleaned = re.sub(r"[^\w\s\-\.\/&]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "Customer"


async def provision_account(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_name: str,
    customer_ref: str | None = None,
    customer_email: str | None = None,
    customer_phone: str | None = None,
    collection_id: uuid.UUID | None = None,
    expected_amount: float | None = None,
    description: str | None = None,
    expires_at: datetime | None = None,
) -> VirtualAccount:
    if customer_ref is None:
        customer_ref = await _generate_unique_customer_ref(db, tenant_id)
    else:
        existing = await db.scalar(
            select(VirtualAccount).where(
                VirtualAccount.tenant_id == tenant_id,
                VirtualAccount.customer_ref == customer_ref,
            )
        )
        if existing:
            raise DuplicateCustomerRefError(
                f"customer_ref '{customer_ref}' already exists for this tenant"
            )
    safe_name = _sanitize_account_name(customer_name)

    resolved_expected_amount = expected_amount
    if resolved_expected_amount is None and collection_id is not None:
        collection = await db.scalar(
            select(Collection).where(
                Collection.id == collection_id,
                Collection.tenant_id == tenant_id,
            )
        )
        if collection and collection.expected_amount is not None:
            resolved_expected_amount = float(collection.expected_amount)

    schedule = None
    if collection_id is not None:
        schedule = await db.scalar(
            select(RecurringSchedule).where(
                RecurringSchedule.collection_id == collection_id,
                RecurringSchedule.is_active == True,  # noqa: E712
            )
        )

    nomba_account_ref = build_nomba_account_ref(tenant_id, customer_ref)

    try:
        nomba_data = await nomba_accounts.create_virtual_account(
            account_ref=nomba_account_ref,
            account_name=safe_name,
            expected_amount=expected_amount,
            expiry_date=expires_at,
        )
    except NombaAPIError as exc:
        raise AccountProvisioningError(
            f"Nomba account provisioning failed: {exc.detail}"
        ) from exc

    now = datetime.now(timezone.utc)
    next_due_date = (
        compute_next_due_date(now, schedule.frequency, schedule.interval_days)
        if schedule
        else None
    )

    account = VirtualAccount(
        tenant_id=tenant_id,
        collection_id=collection_id,
        customer_name=safe_name,
        customer_ref=customer_ref,
        customer_email=customer_email,
        customer_phone=customer_phone,
        nomba_account_ref=nomba_account_ref,
        bank_account_number=nomba_data.get("bankAccountNumber"),
        bank_account_name=nomba_data.get("bankAccountName"),
        bank_name=nomba_data.get("bankName"),
        expected_amount=Decimal(str(resolved_expected_amount))
        if expected_amount is not None
        else None,
        description=description,
        expires_at=expires_at,
        next_due_date=next_due_date,
    )
    db.add(account)
    await db.flush()
    if customer_email:
        await notify_customer_payment_link(
            tenant_id=tenant_id,
            customer_name=safe_name,
            customer_email=customer_email,
            account_id=str(account.id),
            bank_account_number=account.bank_account_number,
            bank_name=account.bank_name,
            expected_amount=expected_amount,
            description=description,
        )
    return account


async def suspend_account(db: AsyncSession, account: VirtualAccount) -> None:
    """
    Suspends on Nomba first — only marks inactive locally if that succeeds, so we
    never have a local record claiming suspended while Nomba still accepts transfers.
    """
    try:
        await nomba_accounts.expire_virtual_account(
            account.bank_account_number or account.nomba_account_ref
        )
    except NombaAPIError as exc:
        raise AccountProvisioningError(
            f"Nomba suspension failed: {exc.detail}"
        ) from exc

    account.is_active = False
    db.add(account)
