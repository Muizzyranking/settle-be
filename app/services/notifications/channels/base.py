from abc import ABC, abstractmethod

from app.models import Tenant
from app.services.notifications.context import NotificationContext


class BaseChannel(ABC):
    @abstractmethod
    async def send(self, context: NotificationContext, tenant: Tenant): ...
