from datetime import datetime

from app.core.config import settings
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

        response = await nomba_client.post(
            f"/accounts/virtual/{settings.NOMBA_SUB_ACCOUNT_ID}",
            json=payload,
        )
        return response["data"]

    async def expire_virtual_account(self, account_ref: str) -> bool:
        response = await nomba_client.request(
            "DELETE",
            f"/accounts/virtual/{account_ref}",
        )
        return response.get("data", {}).get("expired", False)

    async def lookup_virtual_account(self, bank_account_number: str) -> dict:
        response = await nomba_client.get(f"/accounts/virtual/{bank_account_number}")
        return response["data"]

    async def list_banks(self) -> list[dict]:
        response = await nomba_client.get("/transfers/banks")
        return response.get("data", [])

    async def lookup_bank_account(self, account_number: str, bank_code: str) -> dict:
        response = await nomba_client.post(
            "/transfers/bank/lookup",
            json={"accountNumber": account_number, "bankCode": bank_code},
        )
        return response["data"]

    async def transfer_to_bank(
        self,
        amount: float,
        account_number: str,
        account_name: str,
        bank_code: str,
        merchant_tx_ref: str,
        sender_name: str,
    ) -> dict:
        response = await nomba_client.request(
            "POST",
            "/v2/transfers/bank",
            json={
                "amount": amount,
                "accountNumber": account_number,
                "accountName": account_name,
                "bankCode": bank_code,
                "merchantTxRef": merchant_tx_ref,
                "senderName": sender_name,
            },
        )
        return response["data"]


nomba_accounts = NombaVirtualAccountService()
