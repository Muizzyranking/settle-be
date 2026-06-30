from fastapi import APIRouter

from app.api.routes import accounts, auth, collections, webhook

router = APIRouter()
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
router.include_router(collections.router, prefix="/collections", tags=["collections"])
router.include_router(webhook.router)
