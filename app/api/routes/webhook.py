import base64
import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.services.recouncilation import reconcile_payment

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def verify_nomba_signature(payload: dict, signature: str, timestamp: str) -> bool:
    """
    Verify Nomba webhook signature using HMAC-SHA256.
    """
    try:
        m = payload["data"]["merchant"]
        t = payload["data"]["transaction"]

        s = ":".join(
            [
                payload["event_type"],
                payload["requestId"],
                m["userId"],
                m["walletId"],
                t["transactionId"],
                t["type"],
                t["time"],
                t.get("responseCode", ""),
                timestamp,
            ]
        )

        digest = hmac.new(
            settings.NOMBA_WEBHOOK_SECRET.encode("utf-8"),
            s.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        expected = base64.b64encode(digest).decode("utf-8")
        return hmac.compare_digest(expected, signature)

    except (KeyError, TypeError) as e:
        logger.error(f"Malformed payload for signature verification: {e}")
        return False


@router.post("/nomba")
async def nomba_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    nomba_signature: str | None = Header(default=None, alias="nomba-signature"),
    nomba_timestamp: str | None = Header(default=None, alias="nomba-timestamp"),
):
    """
    Nomba webhook endpoint.
    """
    body = await request.body()

    logger.info("=== NOMBA WEBHOOK RECEIVED ===")
    logger.info(f"Headers: signature={nomba_signature}, timestamp={nomba_timestamp}")

    try:
        payload = json.loads(body)
        logger.info(
            f"event_type={payload.get('event_type')}, requestId={payload.get('requestId')}"
        )
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON body: {body.decode()}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from e

    if settings.NOMBA_WEBHOOK_SECRET and nomba_signature and nomba_timestamp:
        if not verify_nomba_signature(payload, nomba_signature, nomba_timestamp):
            logger.warning("Invalid Nomba webhook signature")
            raise HTTPException(status_code=401, detail="Invalid signature")
    else:
        logger.warning(
            "Skipping signature verification — missing secret, signature, or timestamp"
        )

    background_tasks.add_task(
        reconcile_payment, payload=payload, raw_payload=body.decode()
    )

    return JSONResponse(
        content={
            "status": "received",
            "event_type": payload.get("event_type"),
            "requestId": payload.get("requestId"),
        },
        status_code=200,
    )


@router.get("/health")
async def webhook_health():
    """Health check for the webhook endpoint."""
    return {"status": "ok", "webhook": "nomba"}
