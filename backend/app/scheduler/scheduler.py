import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import FastAPI, Response, status
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import select, and_
from sqlalchemy.sql import func

from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.models.scheduled_message import ScheduledMessage
from app.queue.producer import enqueue_job
from app.queue.retry import check_and_enqueue_retries
from app.queue.client import check_redis_health
from app.queue.metrics import (
    scheduler_poll_total,
    scheduler_poll_duration,
    scheduled_jobs_discovered,
)

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] scheduler: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout
)
logger = logging.getLogger("scheduler")

# Configs from environment
POLL_INTERVAL = int(os.getenv("SCHEDULER_POLL_INTERVAL_SECONDS", "5"))
PROCESSING_TIMEOUT = int(os.getenv("SCHEDULED_MESSAGE_PROCESSING_TIMEOUT_SECONDS", "60"))

# State variables for health monitoring
health_state = {
    "last_successful_poll_at": None,
    "last_enqueue_attempt_at": None,
    "poll_interval_seconds": POLL_INTERVAL,
    "redis_connected": False,
    "postgres_connected": False
}


async def process_due_messages():
    """
    Finds due scheduled messages, transitions status to QUEUED in DB, and enqueues in Redis.
    Uses a two-phase commit-then-enqueue pattern to release database locks before worker pops jobs.
    """
    now_utc = datetime.now(timezone.utc)
    due_messages = []
    
    # 1. Fetch due messages, mark them as QUEUED, and commit transaction immediately to release locks
    try:
        async with SessionLocal() as db:
            async with db.begin():
                # Query due rows for update (to prevent double enqueue by concurrent schedulers)
                stmt = (
                    select(ScheduledMessage)
                    .where(
                        and_(
                            ScheduledMessage.status == "SCHEDULED",
                            ScheduledMessage.scheduled_at_utc <= now_utc
                        )
                    )
                    .with_for_update(skip_locked=True)
                )
                result = await db.execute(stmt)
                due_messages_db = result.scalars().all()

                if not due_messages_db:
                    return

                logger.info(f"Discovered {len(due_messages_db)} due scheduled messages.")
                scheduled_jobs_discovered.inc(len(due_messages_db))
                health_state["last_enqueue_attempt_at"] = datetime.now(timezone.utc).isoformat()

                # Save metadata before transaction commit
                for msg in due_messages_db:
                    due_messages.append({
                        "id": msg.id,
                        "scheduled_at_utc": msg.scheduled_at_utc
                    })
                    msg.status = "QUEUED"
                    
    except Exception as e:
        logger.error(f"Error updating due messages status to QUEUED: {e}", exc_info=True)
        return

    # 2. Push to Redis queue now that DB locks are fully released
    if not due_messages:
        return

    t1 = time.time()
    from app.queue.metrics import scheduler_discovery_latency, scheduler_jobs_discovered_total, scheduler_jobs_enqueued_total

    scheduler_jobs_discovered_total.inc(len(due_messages))

    for item in due_messages:
        msg_id = item["id"]
        scheduled_at = item["scheduled_at_utc"]
        logger.info(f"Queueing ScheduledMessage ID: {msg_id}")
        
        # Target scheduled time t0
        t0 = scheduled_at.replace(tzinfo=timezone.utc).timestamp()
        scheduler_discovery_latency.observe(t1 - t0)
        
        # Push to Redis
        success = await enqueue_job(str(msg_id), t0=t0, t1=t1)
        if success:
            scheduler_jobs_enqueued_total.inc()
        else:
            logger.error(f"Failed to push message {msg_id} to Redis queue")
            # Revert status to SCHEDULED in DB to support immediate retries and resilience
            try:
                async with SessionLocal() as db_revert:
                    async with db_revert.begin():
                        stmt_revert = (
                            select(ScheduledMessage)
                            .where(ScheduledMessage.id == msg_id)
                            .with_for_update()
                        )
                        res_revert = await db_revert.execute(stmt_revert)
                        msg_revert = res_revert.scalars().first()
                        if msg_revert:
                            msg_revert.status = "SCHEDULED"
                            logger.info(f"Reverted message {msg_id} status back to SCHEDULED due to Redis enqueue failure.")
            except Exception as revert_err:
                logger.error(f"Failed to revert status to SCHEDULED for message {msg_id}: {revert_err}")



async def recover_stalled_messages():
    """
    Finds messages stuck in PROCESSING state beyond the timeout and resets them back to SCHEDULED.
    Also recovers messages stuck in QUEUED state beyond the timeout (indicating Redis queue loss).
    """
    now_utc = datetime.now(timezone.utc)
    processing_cutoff = now_utc - timedelta(seconds=PROCESSING_TIMEOUT)
    queued_cutoff = now_utc - timedelta(seconds=PROCESSING_TIMEOUT)
    
    try:
        async with SessionLocal() as db:
            async with db.begin():
                # 1. Recover stalled PROCESSING messages
                stmt_proc = (
                    select(ScheduledMessage)
                    .where(
                        and_(
                            ScheduledMessage.status == "PROCESSING",
                            ScheduledMessage.processing_started_at <= processing_cutoff
                        )
                    )
                    .with_for_update(skip_locked=True)
                )
                res_proc = await db.execute(stmt_proc)
                stalled_proc = res_proc.scalars().all()

                if stalled_proc:
                    logger.info(f"Found {len(stalled_proc)} stalled PROCESSING messages. Recovering them...")
                    for msg in stalled_proc:
                        msg.status = "SCHEDULED"
                        msg.processing_started_at = None
                        msg.failure_reason = "Processing timeout exceeded, rescheduled"
                        logger.info(f"Recovered processing message ID: {msg.id} -> SCHEDULED")

                # 2. Recover stalled QUEUED messages (indicates Redis queue loss)
                stmt_queued = (
                    select(ScheduledMessage)
                    .where(
                        and_(
                            ScheduledMessage.status == "QUEUED",
                            ScheduledMessage.updated_at <= queued_cutoff
                        )
                    )
                    .with_for_update(skip_locked=True)
                )
                res_queued = await db.execute(stmt_queued)
                stalled_queued = res_queued.scalars().all()

                if stalled_queued:
                    logger.info(f"Found {len(stalled_queued)} stalled QUEUED messages. Rescheduling back to SCHEDULED...")
                    for msg in stalled_queued:
                        msg.status = "SCHEDULED"
                        msg.failure_reason = "Queued timeout exceeded (Redis queue loss), rescheduled"
                        logger.info(f"Recovered queued message ID: {msg.id} -> SCHEDULED")

                # 3. Recover stalled FAILED_PENDING_DLQ messages (collect and publish outside transaction)
                stmt_dlq = (
                    select(ScheduledMessage)
                    .where(ScheduledMessage.status == "FAILED_PENDING_DLQ")
                    .with_for_update(skip_locked=True)
                )
                res_dlq = await db.execute(stmt_dlq)
                stalled_dlq = res_dlq.scalars().all()
                
                stalled_dlq_jobs = []
                if stalled_dlq:
                    logger.info(f"Found {len(stalled_dlq)} stalled FAILED_PENDING_DLQ messages to recover.")
                    for msg in stalled_dlq:
                        stalled_dlq_jobs.append((msg.id, msg.failure_reason))

        # Publish recovered DLQ messages outside database transaction block
        if stalled_dlq_jobs:
            from app.queue.retry import publish_to_dlq
            for j_id, j_reason in stalled_dlq_jobs:
                logger.info(f"Recovering DLQ publication for job {j_id}")
                await publish_to_dlq(j_id, j_reason or "Stalled DLQ recovery")

    except Exception as e:
        logger.error(f"Error executing timeout recovery cycle: {e}", exc_info=True)


async def scheduler_loop():
    """
    Background polling loop for due messages, retries, and timeout recoveries.
    """
    logger.info("Starting scheduler loop background task...")
    
    # Wait briefly for startup
    await asyncio.sleep(2)

    while True:
        start_time = time.time()
        scheduler_poll_total.inc()

        try:
            # 1. Check and enqueue due retries from Redis sorted set
            await check_and_enqueue_retries()

            # 2. Reschedule any hung PROCESSING messages
            await recover_stalled_messages()

            # 3. Publish due SCHEDULED database records to queue
            await process_due_messages()

            # Record success timestamps for health metrics
            health_state["last_successful_poll_at"] = datetime.now(timezone.utc).isoformat()
            health_state["postgres_connected"] = True
            
        except Exception as err:
            logger.error(f"Loop cycle error: {err}")
            health_state["postgres_connected"] = False

        duration = time.time() - start_time
        scheduler_poll_duration.observe(duration)

        await asyncio.sleep(POLL_INTERVAL)


# --- Lifespan and API setup ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start loop background task
    task = asyncio.create_task(scheduler_loop())
    yield
    # Shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Latext Scheduled Message Scheduler",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """
    Checks health of DB and Redis connections and returns polling statistics.
    """
    redis_healthy = await check_redis_health()
    health_state["redis_connected"] = redis_healthy

    # Simple DB ping
    db_healthy = False
    try:
        async with SessionLocal() as db:
            await db.execute(select(func.now()))
            db_healthy = True
            health_state["postgres_connected"] = True
    except Exception:
        health_state["postgres_connected"] = False

    overall_status = "healthy" if (redis_healthy and db_healthy) else "unhealthy"

    return {
        "status": overall_status,
        "database_connected": db_healthy,
        "redis_connected": redis_healthy,
        "metrics": health_state
    }


@app.get("/metrics")
async def get_metrics():
    """
    Prometheus metrics scrape target.
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    import uvicorn
    logger.info("Starting scheduler application server...")
    uvicorn.run("app.scheduler.scheduler:app", host="0.0.0.0", port=8002)
