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
from app.models.payout import Payout
from app.models.transaction import Transaction, TransactionStatus
from app.services.notifications.context import NotificationContext, NotificationType
from app.services.notifications.manager import notification_manager
from app.services.recurrence import compute_next_due_date

# map TransactionStatus to the virtual account's persisted payment_status
PAYMENT_STATUS_MAP: dict[TransactionStatus, str] = {
    TransactionStatus.EXACT: "exact",
    TransactionStatus.OVERPAID: "overpaid",
    TransactionStatus.UNDERPAID: "underpaid",
    TransactionStatus.UNMATCHED: "received",
}

logger = logging.getLogger(__name__)

ACCOUNT_STATUS_CHANNEL_PREFIX = "settle:account:status:"

# statuses that count as "the period is fulfilled" for recurrence purposes
QUALIFYING_STATUSES = (
    TransactionStatus.EXACT,
    TransactionStatus.OVERPAID,
    TransactionStatus.UNMATCHED,
)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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


async def reconcile_event(payload: dict, raw_payload: str) -> None:
    async with AsyncSessionLocal() as db:
        try:
            event_type = payload.get("event_type")
            handler = _EVENT_HANDLERS.get(event_type)
            if handler is None:
                logger.info(f"No handler registered for event_type={event_type} — skipping")
                return
            await handler(db, payload, raw_payload)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Reconciliation failed for %s", payload.get("event_type"))


async def _handle_payment_success(
    db: AsyncSession, payload: dict, raw_payload: str
) -> None:
    data = payload.get("data", {})
    txn = data.get("transaction", {})
    customer = data.get("customer", {})

    logger.info(
        f"Processing transaction: {txn.get('transactionId')} type={txn.get('type')}"
    )

    nomba_transaction_ref = txn.get("transactionId")
    nomba_account_ref = txn.get("aliasAccountReference")
    amount = Decimal(str(txn.get("transactionAmount", 0)))

    if not nomba_transaction_ref:
        logger.warning("Webhook payload missing transactionId — skipping")
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
        currency="NGN",
        sender_account_number=customer.get("accountNumber"),
        sender_account_name=customer.get("senderName"),
        sender_bank_name=customer.get("bankName"),
        narration=txn.get("narration"),
        status=status,
        expected_amount=expected_amount,
        difference=difference,
        raw_payload=raw_payload,
        paid_at=_parse_datetime(txn.get("time")),
    )
    db.add(transaction)
    await db.flush()

    await _post_to_ledger(db, virtual_account, transaction, amount)

    virtual_account.total_paid = float(
        Decimal(str(virtual_account.total_paid)) + amount
    )
    virtual_account.payment_status = PAYMENT_STATUS_MAP.get(status, "unpaid")
    db.add(virtual_account)

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


async def _handle_payout_success(
    db: AsyncSession, payload: dict, raw_payload: str
) -> None:
    data = payload.get("data", {})
    txn = data.get("transaction", {})

    merchant_tx_ref = txn.get("merchantTxRef")
    if not merchant_tx_ref:
        logger.warning("payout_success payload missing merchantTxRef — skipping")
        return

    payout = await db.scalar(
        select(Payout).where(Payout.transaction_ref == merchant_tx_ref)
    )
    if not payout:
        logger.warning(
            f"payout_success: no payout found for ref {merchant_tx_ref} — skipping"
        )
        return

    if payout.status == "paid":
        logger.info(f"Payout {merchant_tx_ref} already marked paid — skipping")
        return

    fee = Decimal(str(txn.get("fee", 0)))
    payout.status = "paid"
    payout.fee = float(fee)
    db.add(payout)
    logger.info(f"Payout {merchant_tx_ref} marked as paid (fee: {fee})")

    try:
        redis = get_redis()
        await redis.delete(f"settle:finance:overview:{payout.tenant_id}")
    except Exception:
        pass


async def _handle_payout_refund(
    db: AsyncSession, payload: dict, raw_payload: str
) -> None:
    data = payload.get("data", {})
    txn = data.get("transaction", {})

    merchant_tx_ref = txn.get("merchantTxRef")
    if not merchant_tx_ref:
        logger.warning("payout_refund payload missing merchantTxRef — skipping")
        return

    payout = await db.scalar(
        select(Payout).where(Payout.transaction_ref == merchant_tx_ref)
    )
    if not payout:
        logger.warning(
            f"payout_refund: no payout found for ref {merchant_tx_ref} — skipping"
        )
        return

    payout.status = "refunded"
    db.add(payout)
    logger.info(f"Payout {merchant_tx_ref} marked as refunded")

    try:
        redis = get_redis()
        await redis.delete(f"settle:finance:overview:{payout.tenant_id}")
    except Exception:
        pass


_EVENT_HANDLERS = {
    "payment_success": _handle_payment_success,
    "payout_success": _handle_payout_success,
    "payout_refund": _handle_payout_refund,
}


async def _record_misdirected(
    db: AsyncSession,
    data: dict,
    nomba_transaction_ref: str,
    nomba_account_ref: str | None,
    amount: Decimal,
    raw_payload: str,
) -> None:
    txn = data.get("transaction", {})
    customer = data.get("customer", {})

    logger.warning(
        f"No active virtual account for ref {nomba_account_ref} — recording as misdirected"
    )
    db.add(
        Transaction(
            nomba_transaction_ref=nomba_transaction_ref,
            nomba_account_ref=nomba_account_ref or "unknown",
            amount=amount,
            currency="NGN",
            sender_account_number=customer.get("accountNumber"),
            sender_account_name=customer.get("senderName"),
            sender_bank_name=customer.get("bankName"),
            narration=txn.get("narration"),
            status=TransactionStatus.MISDIRECTED,
            raw_payload=raw_payload,
            paid_at=_parse_datetime(txn.get("time")),
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
                "status": status.value if hasattr(status, "value") else status,
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
        assert difference is not None
        return (
            "Overpayment received",
            f"{name} paid ₦{amount:,.2f} — ₦{abs(difference):,.2f} more than expected",
        )
    if status == TransactionStatus.UNDERPAID:
        assert difference is not None
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
    try:
        payload = json.dumps(
            {
                "status": status.value if hasattr(status, "value") else status,
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
