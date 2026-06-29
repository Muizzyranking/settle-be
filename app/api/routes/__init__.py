from fastapi import APIRouter

from app.api.routes import webhook

router = APIRouter()
router.include_router(webhook.router)
