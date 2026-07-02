from fastapi import APIRouter

from app.api.routes import accounts, auth, collections, pay, transactions, webhook

router = APIRouter()
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
router.include_router(collections.router, prefix="/collections", tags=["collections"])
router.include_router(pay.router, prefix="/pay", tags=["payment"])
router.include_router(
    transactions.router, prefix="/transactions", tags=["transactions"]
)
router.include_router(webhook.router)
