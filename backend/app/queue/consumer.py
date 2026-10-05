import asyncio
import json
import logging
import time
from app.core.config import settings
from app.queue.client import redis_client, check_redis_health
from app.queue.metrics import (
    jobs_consumed_total,
    worker_active_jobs,
)

logger = logging.getLogger("queue_consumer")

QUEUE_NAME = "latext:scheduled:queue"


async def run_worker_task(payload_str: str, process_callback, sem: asyncio.Semaphore):
    """
    Spawns worker processing flow, updates active task counts, and releases backpressure semaphore.
    """
    t3 = time.time()
    try:
        worker_active_jobs.inc()
        jobs_consumed_total.inc()
        
        data = json.loads(payload_str)
        sm_id = data.get("scheduled_message_id")
        if not sm_id:
            logger.error(f"Job payload missing 'scheduled_message_id': {payload_str}")
            return

        data["t3"] = t3
        data["t4"] = time.time()
        logger.info(f"Popped job {sm_id} from queue. Commencing worker processing.")
        await process_callback(sm_id, payload_data=data)
        
    except Exception as e:
        logger.error(f"Error executing worker task for payload {payload_str}: {e}", exc_info=True)
    finally:
        worker_active_jobs.dec()
        sem.release()


async def run_worker_batch_task(payload_strs: list[str], process_batch_callback, sem: asyncio.Semaphore):
    """
    Spawns batch worker processing flow, updates active task counts, and releases backpressure semaphore.
    """
    t3 = time.time()
    try:
        worker_active_jobs.inc(len(payload_strs))
        jobs_consumed_total.inc(len(payload_strs))
        
        payloads = []
        for payload_str in payload_strs:
            try:
                data = json.loads(payload_str)
                data["t3"] = t3
                data["t4"] = time.time()
                payloads.append(data)
            except Exception as pe:
                logger.error(f"Failed to parse payload {payload_str}: {pe}")

        if payloads:
            logger.info(f"Popped batch of {len(payloads)} jobs. Commencing batch worker processing.")
            await process_batch_callback(payloads)
            
    except Exception as e:
        logger.error(f"Error executing worker batch task: {e}", exc_info=True)
    finally:
        worker_active_jobs.dec(len(payload_strs))
        for _ in range(len(payload_strs)):
            sem.release()


async def start_consumer(process_callback, stop_event: asyncio.Event = None, process_batch_callback = None):
    """
    Polls the Redis list queue with blpop or batch lpop.
    Limits active tasks to WORKER_CONCURRENCY for backpressure.
    """
    logger.info("Initializing Redis queue consumer...")
    logger.info(f"Worker Concurrency (Backpressure limit): {settings.WORKER_CONCURRENCY}")

    import os
    batch_size = int(os.getenv("WORKER_BATCH_SIZE", "1"))
    if process_batch_callback is None:
        batch_size = 1

    from app.queue.metrics import redis_dequeue_latency, queue_depth
    sem = asyncio.Semaphore(settings.WORKER_CONCURRENCY)

    while stop_event is None or not stop_event.is_set():
        # Check Redis connection health first
        is_healthy = await check_redis_health()
        if not is_healthy:
            logger.warning("Redis connection lost. Consumer sleeping for 3 seconds before retry...")
            await asyncio.sleep(3)
            continue

        # Acquire a concurrency slot (backpressure point)
        await sem.acquire()
        acquired_slots = 1

        while acquired_slots < batch_size:
            if sem.locked():
                break
            if sem._value > 0:
                await sem.acquire()
                acquired_slots += 1
            else:
                break

        try:
            payloads_str = []

            # Dequeue up to acquired_slots from Redis
            dequeue_start = time.time()
            if acquired_slots > 1:
                results = await redis_client.lpop(QUEUE_NAME, count=acquired_slots)
                if results:
                    payloads_str = [r.decode("utf-8") if isinstance(r, bytes) else r for r in results]

            if not payloads_str:
                result = await redis_client.blpop(QUEUE_NAME, timeout=2)
                if result:
                    payloads_str = [result[1].decode("utf-8") if isinstance(result[1], bytes) else result[1]]

            redis_dequeue_latency.observe(time.time() - dequeue_start)
            
            # Observe queue depth
            q_len = await redis_client.llen(QUEUE_NAME)
            queue_depth.set(q_len)

            if not payloads_str:
                for _ in range(acquired_slots):
                    sem.release()
                continue

            # Release unused acquired slots
            excess = acquired_slots - len(payloads_str)
            for _ in range(excess):
                sem.release()

            if len(payloads_str) > 1 and process_batch_callback is not None:
                asyncio.create_task(run_worker_batch_task(payloads_str, process_batch_callback, sem))
            else:
                asyncio.create_task(run_worker_task(payloads_str[0], process_callback, sem))
            
        except Exception as e:
            logger.error(f"Exception in Redis consumer polling loop: {e}", exc_info=True)
            for _ in range(acquired_slots):
                sem.release()
            await asyncio.sleep(2)
