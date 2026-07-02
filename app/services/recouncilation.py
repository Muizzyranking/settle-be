import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.db.redis import get_redis
from app.models.account import VirtualAccount
from app.models.collection import RecurringSchedule
from app.models.ledger import LedgerEntry, LedgerEntryType
from app.models.transaction import Transaction, TransactionStatus
from app.services.notifications.context import NotificationContext, NotificationType
from app.services.notifications.manager import notification_manager
from app.services.recurrence import compute_next_due_date

logger = logging.getLogger(__name__)

ACCOUNT_STATUS_CHANNEL_PREFIX = "settle:account:status:"

# statuses that count as "the period is fulfilled" for recurrence purposes
QUALIFYING_STATUSES = (
    TransactionStatus.EXACT,
    TransactionStatus.OVERPAID,
    TransactionStatus.UNMATCHED,
)


def _determine_status(
    amount: Decimal,
    expected_amount: Decimal | None,
) -> tuple[TransactionStatus, Decimal | None]:
    if expected_amount is None:
        return TransactionStatus.UNMATCHED, None

    difference = amount - expected_amount
    if difference == 0:
        return TransactionStatus.EXACT, Decimal("0")
    if difference > 0:
        return TransactionStatus.OVERPAID, difference
    return TransactionStatus.UNDERPAID, difference


async def reconcile_payment(payload: dict, raw_payload: str) -> None:
    """Entry point called as a background task from the webhook route."""
    async with AsyncSessionLocal() as db:
        try:
            await _process_payment(db, payload, raw_payload)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Reconciliation failed")


async def _process_payment(db: AsyncSession, payload: dict, raw_payload: str) -> None:
    event = payload.get("event")
    if event not in ("transfer.credit", "virtual_account.credit"):
        logger.info(f"Ignoring non-credit event: {event}")
        return

    data = payload.get("data", {})
    nomba_transaction_ref = data.get("transactionRef") or data.get("reference")
    nomba_account_ref = data.get("accountRef") or data.get("virtualAccountRef")
    amount = Decimal(str(data.get("amount", 0)))

    if not nomba_transaction_ref:
        logger.warning("Webhook payload missing transactionRef — skipping")
        return

    existing = await db.scalar(
        select(Transaction).where(
            Transaction.nomba_transaction_ref == nomba_transaction_ref
        )
    )
    if existing:
        logger.info(f"Transaction {nomba_transaction_ref} already processed — skipping")
        return

    virtual_account = await db.scalar(
        select(VirtualAccount).where(
            VirtualAccount.nomba_account_ref == nomba_account_ref,
            VirtualAccount.is_active == True,  # noqa: E712
        )
    )

    if not virtual_account:
        await _record_misdirected(
            db, data, nomba_transaction_ref, nomba_account_ref, amount, raw_payload
        )
        return

    expected_amount = (
        Decimal(str(virtual_account.expected_amount))
        if virtual_account.expected_amount
        else None
    )
    status, difference = _determine_status(amount, expected_amount)

    transaction = Transaction(
        virtual_account_id=virtual_account.id,
        nomba_transaction_ref=nomba_transaction_ref,
        nomba_account_ref=nomba_account_ref,
        amount=amount,
        currency=data.get("currency", "NGN"),
        sender_account_number=data.get("senderAccountNumber"),
        sender_account_name=data.get("senderAccountName"),
        sender_bank_name=data.get("senderBankName"),
        narration=data.get("narration"),
        status=status,
        expected_amount=expected_amount,
        difference=difference,
        raw_payload=raw_payload,
        paid_at=_parse_datetime(data.get("transactionDate") or data.get("createdAt")),
    )
    db.add(transaction)
    await db.flush()

    await _post_to_ledger(db, virtual_account, transaction, amount)

    if status in QUALIFYING_STATUSES:
        await _advance_recurrence(db, virtual_account)

    await db.flush()

    await _notify(virtual_account, transaction, status, amount, difference)
    await _publish_account_status(
        virtual_account, transaction, status, amount, difference
    )

    logger.info(
        f"Reconciled {nomba_transaction_ref} for account {nomba_account_ref} — {status}"
    )


async def _record_misdirected(
    db: AsyncSession,
    data: dict,
    nomba_transaction_ref: str,
    nomba_account_ref: str | None,
    amount: Decimal,
    raw_payload: str,
) -> None:
    logger.warning(
        f"No active virtual account for ref {nomba_account_ref} — recording as misdirected"
    )
    db.add(
        Transaction(
            nomba_transaction_ref=nomba_transaction_ref,
            nomba_account_ref=nomba_account_ref or "unknown",
            amount=amount,
            currency=data.get("currency", "NGN"),
            sender_account_number=data.get("senderAccountNumber"),
            sender_account_name=data.get("senderAccountName"),
            sender_bank_name=data.get("senderBankName"),
            narration=data.get("narration"),
            status=TransactionStatus.MISDIRECTED,
            raw_payload=raw_payload,
            paid_at=_parse_datetime(
                data.get("transactionDate") or data.get("createdAt")
            ),
        )
    )


async def _post_to_ledger(
    db: AsyncSession,
    virtual_account: VirtualAccount,
    transaction: Transaction,
    amount: Decimal,
) -> None:
    last_entry = await db.scalar(
        select(LedgerEntry)
        .where(LedgerEntry.virtual_account_id == virtual_account.id)
        .order_by(LedgerEntry.created_at.desc())
        .limit(1)
    )
    current_balance = (
        Decimal(str(last_entry.running_balance)) if last_entry else Decimal("0")
    )
    new_balance = current_balance + amount

    db.add(
        LedgerEntry(
            virtual_account_id=virtual_account.id,
            transaction_id=transaction.id,
            entry_type=LedgerEntryType.CREDIT,
            amount=amount,
            running_balance=new_balance,
            description=f"Inbound transfer from {transaction.sender_account_name or 'unknown'}",
        )
    )


async def _advance_recurrence(
    db: AsyncSession, virtual_account: VirtualAccount
) -> None:
    """
    Only called for qualifying payment statuses (see QUALIFYING_STATUSES).
    Underpayment never advances next_due_date — the period stays open until a
    qualifying payment lands, per the spec.
    """
    if virtual_account.collection_id is None:
        return

    schedule = await db.scalar(
        select(RecurringSchedule).where(
            RecurringSchedule.collection_id == virtual_account.collection_id,
            RecurringSchedule.is_active == True,  # noqa: E712
        )
    )
    if not schedule:
        return

    now = datetime.now(timezone.utc)
    virtual_account.last_paid_at = now
    virtual_account.next_due_date = compute_next_due_date(
        now, schedule.frequency, schedule.interval_days
    )
    db.add(virtual_account)


async def _notify(
    virtual_account: VirtualAccount,
    transaction: Transaction,
    status: TransactionStatus,
    amount: Decimal,
    difference: Decimal | None,
) -> None:
    type_map: dict[TransactionStatus, NotificationType] = {
        TransactionStatus.EXACT: "payment_received",
        TransactionStatus.UNMATCHED: "payment_received",
        TransactionStatus.OVERPAID: "payment_overpaid",
        TransactionStatus.UNDERPAID: "payment_underpaid",
    }
    notification_type = type_map.get(status)
    if not notification_type:
        return

    title, message = _build_message(virtual_account, status, amount, difference)

    await notification_manager.notify(
        NotificationContext(
            tenant_id=virtual_account.tenant_id,
            type=notification_type,
            title=title,
            message=message,
            data={
                "transaction_id": str(transaction.id),
                "virtual_account_id": str(virtual_account.id),
                "customer_ref": virtual_account.customer_ref,
                "customer_name": virtual_account.customer_name,
                "amount": float(amount),
                "status": status.value,
            },
        )
    )


def _build_message(
    virtual_account: VirtualAccount,
    status: TransactionStatus,
    amount: Decimal,
    difference: Decimal | None,
) -> tuple[str, str]:
    name = virtual_account.customer_name
    if status == TransactionStatus.OVERPAID:
        return (
            "Overpayment received",
            f"{name} paid ₦{amount:,.2f} — ₦{abs(difference):,.2f} more than expected",
        )
    if status == TransactionStatus.UNDERPAID:
        return (
            "Underpayment received",
            f"{name} paid ₦{amount:,.2f} — ₦{abs(difference):,.2f} short of the expected amount",
        )
    return ("Payment received", f"{name} paid ₦{amount:,.2f}")


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


async def _publish_account_status(
    virtual_account: VirtualAccount,
    transaction: Transaction,
    status: TransactionStatus,
    amount: Decimal,
    difference: Decimal | None,
) -> None:
    """
    Publishes a payment status event to the account-scoped Redis channel so the
    customer's payment page receives a real-time update without polling.
    Failures are swallowed — the SSE stream is best-effort, reconciliation is not.
    """
    try:
        payload = json.dumps(
            {
                "status": status.value,
                "amount": float(amount),
                "expected_amount": float(transaction.expected_amount)
                if transaction.expected_amount
                else None,
                "difference": float(difference) if difference is not None else None,
                "transaction_id": str(transaction.id),
                "paid_at": transaction.paid_at.isoformat()
                if transaction.paid_at
                else None,
            }
        )
        redis = get_redis()
        await redis.publish(
            f"{ACCOUNT_STATUS_CHANNEL_PREFIX}{virtual_account.id}", payload
        )
    except Exception:
        logger.exception("Failed to publish account status event — non-critical")
