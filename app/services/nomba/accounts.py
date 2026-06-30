from datetime import datetime

from app.services.nomba.client import nomba_client


class NombaVirtualAccountService:
    """
    Wraps every Nomba virtual-account-related endpoint behind a clean interface.
    Reconciliation and route code call these methods and never touch NombaClient
    or raw Nomba payload shapes directly.
    """

    async def create_virtual_account(
        self,
        account_ref: str,
        account_name: str,
        expected_amount: float | None = None,
        expiry_date: datetime | None = None,
        bvn: str | None = None,
    ) -> dict:
        payload = {
            "accountRef": account_ref,
            "accountName": account_name,
            "currency": "NGN",
        }
        if expected_amount is not None:
            payload["expectedAmount"] = expected_amount
        if expiry_date is not None:
            payload["expiryDate"] = expiry_date.strftime("%Y-%m-%d %H:%M:%S")
        if bvn is not None:
            payload["bvn"] = bvn

        response = await nomba_client.post("/accounts/virtual", json=payload)
        return response["data"]

    async def suspend_virtual_account(self, nomba_account_id: str) -> bool:
        response = await nomba_client.put(f"/accounts/suspend/{nomba_account_id}")
        return bool(response.get("data"))

    async def lookup_virtual_account(self, bank_account_number: str) -> dict:
        response = await nomba_client.get(f"/accounts/virtual/{bank_account_number}")
        return response["data"]


nomba_accounts = NombaVirtualAccountService()
