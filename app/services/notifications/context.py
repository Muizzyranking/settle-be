import uuid
from dataclasses import dataclass, field
from typing import Literal

NotificationType = Literal[
    "payment_received",
    "payment_underpaid",
    "payment_overpaid",
    "payment_misdirected",
]


@dataclass
class NotificationContext:
    tenant_id: uuid.UUID
    type: NotificationType
    title: str
    message: str
    data: dict = field(default_factory=dict)
