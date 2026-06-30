import logging

import httpx

from app.core.config import settings
from app.core.utils import get_seconds
from app.db.redis import get_redis

logger = logging.getLogger(__name__)

TOKEN_CACHE_KEY = "nomba:access_token"
TOKEN_LOCK_KEY = "nomba:access_token:lock"
TOKEN_TTL_SECONDS = get_seconds(minutes=55)
LOCK_TTL_SECONDS = 15  # max time one worker can hold the lock while fetching a token
LOCK_WAIT_RETRY_DELAY = 0.2
LOCK_WAIT_MAX_ATTEMPTS = 25  # ~5s total wait for another worker to finish issuing


class NombaAPIError(Exception):
    """Raised when Nomba returns a non-success response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Nomba API error {status_code}: {detail}")


class NombaClient:
    """
    Single entry point for every Nomba API call. Owns the OAuth token lifecycle —
    nothing else in the codebase should know how Nomba auth works.
    """

    def __init__(self) -> None:
        self._base_url = settings.NOMBA_BASE_URL

    async def _get_cached_token(self) -> str | None:
        redis = get_redis()
        return str(await redis.get(TOKEN_CACHE_KEY))

    async def _issue_token(self) -> str:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{self._base_url}/auth/token/issue",
                headers={
                    "Content-Type": "application/json",
                    "accountId": settings.NOMBA_ACCOUNT_ID,
                },
                json={
                    "grant_type": "client_credentials",
                    "client_id": settings.NOMBA_CLIENT_ID,
                    "client_secret": settings.NOMBA_CLIENT_SECRET,
                },
            )
        if response.status_code >= 400:
            raise NombaAPIError(response.status_code, response.text)

        token = response.json()["data"]["access_token"]

        redis = get_redis()
        await redis.set(TOKEN_CACHE_KEY, token, ex=TOKEN_TTL_SECONDS)
        return token

    async def _get_token(self) -> str:
        """
        Returns a valid access token, using the Redis cache when possible.
        """
        token = await self._get_cached_token()
        if token:
            return token

        redis = get_redis()
        acquired = await redis.set(TOKEN_LOCK_KEY, "1", ex=LOCK_TTL_SECONDS, nx=True)

        if acquired:
            try:
                return await self._issue_token()
            finally:
                await redis.delete(TOKEN_LOCK_KEY)

        # another worker is already issuing a token — wait for it
        import asyncio

        for _ in range(LOCK_WAIT_MAX_ATTEMPTS):
            await asyncio.sleep(LOCK_WAIT_RETRY_DELAY)
            token = await self._get_cached_token()
            if token:
                return token

        # fallback: lock holder died without releasing — issue directly
        logger.warning("Timed out waiting for Nomba token lock — issuing directly")
        return await self._issue_token()

    async def request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        params: dict | None = None,
        retry_on_auth_failure: bool = True,
    ) -> dict:
        """
        Makes an authenticated request to Nomba. Handles token attachment and a single
        retry if the cached token turns out to be stale (e.g. revoked early).
        """
        token = await self._get_token()

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(
                method,
                f"{self._base_url}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "accountId": settings.NOMBA_ACCOUNT_ID,
                    "Content-Type": "application/json",
                },
                json=json,
                params=params,
            )

        if response.status_code == 401 and retry_on_auth_failure:
            logger.info("Nomba token rejected — clearing cache and retrying once")
            redis = get_redis()
            await redis.delete(TOKEN_CACHE_KEY)
            return await self.request(
                method, path, json=json, params=params, retry_on_auth_failure=False
            )

        if response.status_code >= 400:
            raise NombaAPIError(response.status_code, response.text)

        return response.json()

    async def get(self, path: str, params: dict | None = None) -> dict:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, json: dict | None = None) -> dict:
        return await self.request("POST", path, json=json)

    async def put(self, path: str, json: dict | None = None) -> dict:
        return await self.request("PUT", path, json=json)


nomba_client = NombaClient()
