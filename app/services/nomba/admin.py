import logging

from app.services.nomba.client import nomba_client

logger = logging.getLogger(__name__)


class NombaAdminService:
    """
    Wraps Nomba account-related admin endpoints behind a clean interface.
    """

    async def get_parent_account_balance(self) -> dict:
        response = await nomba_client.get("/v1/accounts/balance")
        return response["data"]

    async def get_sub_account_balance(self, sub_account_id: str) -> dict:
        response = await nomba_client.get(
            f"/v1/accounts/{sub_account_id}/balance"
        )
        return response["data"]

    async def get_sub_account_details(self, sub_account_id: str) -> dict:
        response = await nomba_client.get(
            "/v1/accounts/sub-account-details",
            params={"accountId": sub_account_id},
        )
        return response["data"]


nomba_admin = NombaAdminService()
