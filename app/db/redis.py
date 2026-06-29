from redis.asyncio import Redis

from app.core.config import settings

redis_client: Redis | None = None


async def init_redis():
    global redis_client
    redis_client = Redis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )


async def close_redis():
    if redis_client:
        await redis_client.aclose()


def get_redis() -> Redis:
    if redis_client is None:
        raise RuntimeError("Redis has not been initialised")
    return redis_client
