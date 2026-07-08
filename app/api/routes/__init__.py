from fastapi import APIRouter

from app.api.routes import (
    accounts,
    admin,
    auth,
    collections,
    dashboard,
    finance,
    notifications,
    pay,
    reports,
    settings,
    transactions,
    webhook,
)

router = APIRouter()
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
router.include_router(admin.router, prefix="/admin", tags=["admin"])
router.include_router(collections.router, prefix="/collections", tags=["collections"])
router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
router.include_router(finance.router, prefix="/finance", tags=["finance"])
router.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)
router.include_router(pay.router, prefix="/pay", tags=["payment"])
router.include_router(reports.router, prefix="/reports", tags=["reports"])
router.include_router(settings.router, prefix="/settings", tags=["settings"])
router.include_router(
    transactions.router, prefix="/transactions", tags=["transactions"]
)
router.include_router(webhook.router)
