import json
import logging
import time
from app.core.config import settings
from app.queue.client import redis_client
from app.queue.metrics import jobs_retried_total

logger = logging.getLogger("queue_retry")

RETRY_SET_NAME = "latext:scheduled:retry"
QUEUE_NAME = "latext:scheduled:queue"


def get_retry_delay(attempt_count: int) -> int:
    """
    Computes delay seconds based on attempt count:
    - Attempt 1: 0 (immediate retry)
    - Attempt 2: Base Delay (default 10s)
    - Attempt 3: 3x Base Delay (default 30s)
    - Attempt 4: Max Delay (default 90s)
    """
    if attempt_count <= 1:
        return 0
    elif attempt_count == 2:
        return settings.RETRY_BASE_DELAY_SECONDS
    elif attempt_count == 3:
        return settings.RETRY_BASE_DELAY_SECONDS * 3
    else:
        return settings.MAX_RETRY_DELAY_SECONDS


async def schedule_retry(scheduled_message_id: str, attempt_count: int) -> bool:
    """
    Schedules a message job for retry in the Redis sorted set.
    """
    delay = get_retry_delay(attempt_count)
    run_at = time.time() + delay
    payload = json.dumps({"scheduled_message_id": str(scheduled_message_id)})
    
    try:
        # Add to sorted set with run_at timestamp as score
        await redis_client.zadd(RETRY_SET_NAME, {payload: run_at})
        jobs_retried_total.inc()
        logger.info(f"Scheduled retry for job {scheduled_message_id} in {delay}s (Attempt #{attempt_count})")
        return True
    except Exception as e:
        logger.error(f"Failed to schedule retry for job {scheduled_message_id}: {e}")
        return False


async def check_and_enqueue_retries():
    """
    Checks the sorted set for due retries, pops them, and enqueues to the main list.
    """
    now = time.time()
    try:
        # Retrieve all due jobs (score <= current epoch timestamp)
        due_jobs = await redis_client.zrangebyscore(RETRY_SET_NAME, 0, now)
        if due_jobs:
            logger.info(f"Discovered {len(due_jobs)} due retry tasks in Redis.")
            for payload in due_jobs:
                # Atomically remove from retry set to prevent double execution
                removed = await redis_client.zrem(RETRY_SET_NAME, payload)
                if removed:
                    await redis_client.rpush(QUEUE_NAME, payload)
                    logger.info(f"Moved retry job back to active queue list: {payload}")
    except Exception as e:
        logger.error(f"Error checking/moving retries in Redis: {e}")


async def publish_to_dlq(scheduled_message_id, failure_reason: str) -> bool:
    """
    Publishes a failed job payload to the Redis DLQ.
    Once successful, updates the ScheduledMessage status in PostgreSQL to FAILED.
    """
    import uuid
    from app.models.scheduled_message import ScheduledMessage
    from app.core.database import SessionLocal
    from sqlalchemy import select
    
    DLQ_NAME = "latext:scheduled:dead-letter"
    sm_id = uuid.UUID(str(scheduled_message_id))
    payload = json.dumps({
        "scheduled_message_id": str(sm_id),
        "failure_reason": failure_reason,
        "timestamp": time.time()
    })
    
    try:
        # 1. RPUSH to Redis DLQ
        await redis_client.rpush(DLQ_NAME, payload)
        
        # 2. Update PostgreSQL state to FAILED now that DLQ publication succeeded
        async with SessionLocal() as db:
            async with db.begin():
                stmt = select(ScheduledMessage).where(ScheduledMessage.id == sm_id)
                res = await db.execute(stmt)
                scheduled = res.scalars().first()
                if scheduled:
                    scheduled.status = "FAILED"
                    scheduled.failure_reason = failure_reason
        logger.info(f"Successfully published job {sm_id} to DLQ and marked as FAILED in DB.")
        return True
    except Exception as e:
        logger.error(f"Failed to publish job {sm_id} to Redis DLQ: {e}")
        return False
