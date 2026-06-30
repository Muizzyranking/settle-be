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
        data = payload.get("data", {})
        merchant = data.get("merchant", {})
        transaction = data.get("transaction", {})

        event_type = payload.get("event_type", "")
        request_id = payload.get("requestId", "")
        user_id = merchant.get("userId", "")
        wallet_id = merchant.get("walletId", "")
        transaction_id = transaction.get("transactionId", "")
        transaction_type = transaction.get("type", "")
        transaction_time = transaction.get("time", "")
        response_code = transaction.get("responseCode", "")

        # Handle "null" string as empty per Nomba docs
        if response_code == "null":
            response_code = ""

        # Construct the exact hashing payload as specified by Nomba
        hashing_payload = (
            f"{event_type}:{request_id}:{user_id}:{wallet_id}:"
            f"{transaction_id}:{transaction_type}:{transaction_time}:"
            f"{response_code}:{timestamp}"
        )

        logger.info(f"::: payload to hash --> [{hashing_payload}] :::")

        # Generate HMAC-SHA256 signature
        digest = hmac.new(
            settings.NOMBA_WEBHOOK_SECRET.encode("utf-8"),
            hashing_payload.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        expected_signature = base64.b64encode(digest).decode("utf-8")

        logger.info(f"Generated signature [{expected_signature}]")
        logger.info(f"Expected signature  [{signature}]")

        is_valid = hmac.compare_digest(expected_signature.lower(), signature.lower())

        if is_valid:
            logger.info(">>>>>>> Signatures match <<<<<<<<<")
        else:
            logger.warning("<<<<<<<<< Signatures did not match >>>>>>>>>")

        return is_valid

    except Exception as e:
        logger.error(f"Error verifying signature: {e}")
        return False


def _verify_signature(payload: bytes, signature: str) -> bool:
    expected = hmac.new(
        settings.NOMBA_WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/nomba2")
async def nomba_webhook2(
    request: Request,
    background_tasks: BackgroundTasks,
    nomba_signature: str | None = Header(default=None),
):
    raw_body = await request.body()

    if settings.NOMBA_WEBHOOK_SECRET and nomba_signature:
        print("endter")
        if not _verify_signature(raw_body, nomba_signature):
            logger.warning("Invalid Nomba webhook signature")
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from e

    background_tasks.add_task(
        reconcile_payment, payload=payload, raw_payload=raw_body.decode()
    )
    return {"status": "received"}


@router.post("/nomba")
async def nomba_webhook(
    request: Request,
    nomba_signature: str = Header(None, alias="nomba-signature"),
    nomba_sig_value: str = Header(None, alias="nomba-sig-value"),
    nomba_signature_algorithm: str = Header(None, alias="nomba-signature-algorithm"),
    nomba_signature_version: str = Header(None, alias="nomba-signature-version"),
    nomba_timestamp: str = Header(None, alias="nomba-timestamp"),
):
    """
    webhook endpoint for Nomba.
    """
    body = await request.body()

    logger.info("=" * 50)
    logger.info("=== NOMBA WEBHOOK RECEIVED ===")
    logger.info("=" * 50)

    # Log all headers for debugging
    logger.info("--- Headers ---")
    logger.info(f"nomba-signature:             {nomba_signature}")
    logger.info(f"nomba-sig-value:             {nomba_sig_value}")
    logger.info(f"nomba-signature-algorithm:   {nomba_signature_algorithm}")
    logger.info(f"nomba-signature-version:     {nomba_signature_version}")
    logger.info(f"nomba-timestamp:             {nomba_timestamp}")

    # Parse the payload
    try:
        payload = json.loads(body)
        logger.info("--- Parsed Payload ---")
        logger.info(f"event_type:  {payload.get('event_type')}")
        logger.info(f"requestId:   {payload.get('requestId')}")
        logger.info(f"Full payload: {json.dumps(payload, indent=2)}")
    except json.JSONDecodeError as e:
        logger.warning(f"Raw body (not valid JSON): {body.decode()}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from e

    if nomba_signature:
        is_valid = verify_nomba_signature(payload, nomba_signature, nomba_timestamp)
        if not is_valid:
            logger.warning("Webhook signature verification failed!")
            # raise HTTPException(status_code=401, detail="Invalid signature")

    logger.info("=== END WEBHOOK ===")

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
