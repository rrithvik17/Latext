import json
import logging
import time
from app.queue.client import redis_client
from app.queue.metrics import (
    jobs_enqueued_total,
    scheduled_jobs_enqueued,
    redis_enqueue_latency,
    scheduled_to_enqueue_latency,
    scheduler_enqueue_latency,
)

logger = logging.getLogger("queue_producer")

QUEUE_NAME = "latext:scheduled:queue"


async def enqueue_job(scheduled_message_id: str, t0: float = None, t1: float = None) -> bool:
    """
    Serializes and enqueues a scheduled message job ID onto the Redis list.
    Includes profiling timestamps t0 (scheduled), t1 (discovered), and t2 (enqueued).
    """
    t2 = time.time()
    payload_data = {
        "scheduled_message_id": str(scheduled_message_id)
    }
    if t0 is not None:
        payload_data["t0"] = t0
    if t1 is not None:
        payload_data["t1"] = t1
    payload_data["t2"] = t2

    payload = json.dumps(payload_data)
    try:
        await redis_client.rpush(QUEUE_NAME, payload)
        jobs_enqueued_total.inc()
        scheduled_jobs_enqueued.inc()
        
        # Observe enqueuing latency metrics
        if t1 is not None:
            redis_enqueue_latency.observe(t2 - t1)
            scheduler_enqueue_latency.observe(t2 - t1)
        if t0 is not None:
            scheduled_to_enqueue_latency.observe(t2 - t0)

        logger.info(f"Successfully enqueued job to Redis: {scheduled_message_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to enqueue job {scheduled_message_id} to Redis: {e}")
        return False
