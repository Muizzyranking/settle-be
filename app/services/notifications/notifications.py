import uuid

from app.services.notifications.context import NotificationContext
from app.services.notifications.manager import NotificationChannel, notification_manager


async def notify_customer_payment_link(
    tenant_id: uuid.UUID,
    customer_name: str,
    customer_email: str,
    account_id: str,
    bank_account_number: str | None,
    bank_name: str | None,
    expected_amount: float | None,
    description: str | None,
) -> None:
    """Sends the customer an email with their dedicated payment account details."""
    amount_line = f"₦{expected_amount:,.2f}" if expected_amount else "any amount"
    bank_line = (
        f"{bank_account_number} ({bank_name})"
        if bank_account_number
        else "being prepared"
    )

    context = NotificationContext(
        type="payment_link",
        tenant_id=tenant_id,
        title="Your Payment Account is Ready",
        message=(
            f"Hello {customer_name}, your dedicated payment account has been set up. "
            f"Use the account number below to make your transfer."
        ),
        data={
            "template": "payment_link",
            "to_email": customer_email,
            "customer_name": customer_name,
            "account_id": account_id,
            "bank_line": bank_line,
            "amount_line": amount_line,
            "description": description,
        },
    )

    await notification_manager.notify(context, channels=NotificationChannel.EMAIL)
