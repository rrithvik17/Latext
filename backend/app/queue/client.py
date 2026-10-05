import logging
import redis.asyncio as aioredis
from app.core.config import settings

logger = logging.getLogger("queue_client")

# Initialize connection pool with standard limits
pool = aioredis.ConnectionPool.from_url(
    settings.REDIS_URL,
    max_connections=50,
    decode_responses=True
)

redis_client = aioredis.Redis(connection_pool=pool)


async def check_redis_health() -> bool:
    """
    Pings the Redis instance to verify active connectivity.
    """
    try:
        await redis_client.ping()
        return True
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        return False
