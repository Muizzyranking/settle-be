import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token, hash_api_key
from app.db.database import get_db
from app.models.tenant import Tenant

DBSession = Annotated[AsyncSession, Depends(get_db)]


bearer_scheme = HTTPBearer(
    scheme_name="Bearer",
    description="JWT access token for dashboard authentication",
    auto_error=False,
)


async def get_current_tenant(
    db: DBSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    x_settle_key: Annotated[str | None, Header(description="Developer API key")] = None,
) -> Tenant:
    """
    Resolves a Tenant from either a JWT bearer token (dashboard) or an API key
    (developer access). Both paths converge here — downstream routes never care
    which one was used.
    """
    if x_settle_key:
        return await _resolve_from_api_key(x_settle_key, db)

    if credentials and credentials.scheme == "Bearer":
        return await _resolve_from_jwt(credentials.credentials, db)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing Authorization or X-Settle-Key header",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _resolve_from_jwt(token: str, db: AsyncSession) -> Tenant:
    try:
        data = decode_access_token(token)
        tenant_id = uuid.UUID(data["sub"])
        token_version = data.get("tv", 0)
    except (jwt.PyJWTError, ValueError, KeyError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    tenant = await db.get(Tenant, tenant_id)
    if not tenant or not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tenant not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if tenant.token_version != token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been invalidated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return tenant


async def _resolve_from_api_key(raw_key: str, db: AsyncSession) -> Tenant:
    hashed = hash_api_key(raw_key)
    tenant = await db.scalar(select(Tenant).where(Tenant.hashed_api_key == hashed))
    if not tenant or not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return tenant


CurrentTenant = Annotated[Tenant, Depends(get_current_tenant)]
