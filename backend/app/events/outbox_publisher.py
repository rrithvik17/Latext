import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, update, or_, and_, delete
from app.core.database import SessionLocal
from app.queue.client import redis_client, check_redis_health
from app.models.outbox import OutboxEvent
from prometheus_client import Gauge, Counter, Histogram

logger = logging.getLogger("outbox_publisher")
EVENTS_CHANNEL = "latext:events"

# Prometheus metrics
outbox_pending_total = Gauge(
    "outbox_pending_total",
    "Total pending/unpublished events in the outbox"
)
outbox_published_total = Counter(
    "outbox_published_total",
    "Total events successfully published from the outbox"
)
outbox_publish_failures_total = Counter(
    "outbox_publish_failures_total",
    "Total failures in outbox event publishing"
)
outbox_retry_total = Counter(
    "outbox_retry_total",
    "Total retry attempts for outbox events"
)
outbox_publish_duration = Histogram(
    "outbox_publish_duration",
    "Time between outbox event creation and successful Redis publish in seconds"
)
outbox_oldest_pending_age = Gauge(
    "outbox_oldest_pending_age",
    "Age of the oldest pending outbox event in seconds"
)

# Async event to trigger immediate publisher run
_wakeup_event = asyncio.Event()

def trigger_outbox_publish():
    """
    Wakes up the outbox publisher daemon immediately to process new events.
    """
    _wakeup_event.set()

async def get_backoff_thresholds():
    """
    Returns the time criteria for retries based on attempts.
    - Attempt 1: immediate
    - Attempt 2: 10 seconds backoff
    - Attempt 3: 30 seconds backoff
    - Attempt 4: 90 seconds backoff
    """
    now = datetime.now(timezone.utc)
    return now

async def claim_batch(batch_size: int = 50) -> list[dict]:
    """
    Queries and claims unpublished outbox events using FOR UPDATE SKIP LOCKED.
    Increments attempt count and updates last_attempt_at within the transaction.
    """
    now = datetime.now(timezone.utc)
    
    # Calculate backoff filters
    t_10 = now - timedelta(seconds=10)
    t_30 = now - timedelta(seconds=30)
    t_90 = now - timedelta(seconds=90)

    async with SessionLocal() as db:
        async with db.begin():
            # Query eligible events: published_at is NULL, attempts < 4, and backoff has elapsed
            stmt = (
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .where(OutboxEvent.attempts < 4)
                .where(
                    or_(
                        OutboxEvent.last_attempt_at.is_(None),
                        and_(OutboxEvent.attempts == 1, OutboxEvent.last_attempt_at <= t_10),
                        and_(OutboxEvent.attempts == 2, OutboxEvent.last_attempt_at <= t_30),
                        and_(OutboxEvent.attempts == 3, OutboxEvent.last_attempt_at <= t_90)
                    )
                )
                .order_by(OutboxEvent.created_at.asc())
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            res = await db.execute(stmt)
            events = res.scalars().all()
            
            if not events:
                return []
                
            claimed_data = []
            for ev in events:
                # Increment attempts and update timestamp
                ev.attempts += 1
                ev.last_attempt_at = now
                
                claimed_data.append({
                    "id": ev.id,
                    "event_type": ev.event_type,
                    "aggregate_id": ev.aggregate_id,
                    "payload": ev.payload,
                    "attempts": ev.attempts,
                    "created_at": ev.created_at
                })
                
                if ev.attempts > 1:
                    outbox_retry_total.inc()
                    
            await db.flush()
            return claimed_data

async def mark_results(success_ids: list[uuid.UUID], failed_updates: list[dict]):
    """
    Starts a new transaction to record successful publishes and failure reasons.
    """
    if not success_ids and not failed_updates:
        return
        
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        async with db.begin():
            if success_ids:
                stmt_success = (
                    update(OutboxEvent)
                    .where(OutboxEvent.id.in_(success_ids))
                    .values(published_at=now)
                )
                await db.execute(stmt_success)
                
            for fail in failed_updates:
                stmt_fail = (
                    update(OutboxEvent)
                    .where(OutboxEvent.id == fail["id"])
                    .values(failure_reason=fail["reason"])
                )
                await db.execute(stmt_fail)
                
            await db.flush()

async def process_outbox_events() -> int:
    """
    Single processing run: claims a batch, publishes to Redis, and saves results.
    Returns the number of claimed events.
    """
    try:
        events = await claim_batch()
        if not events:
            return 0
            
        success_ids = []
        failed_updates = []
        
        # Check Redis health first
        is_healthy = await check_redis_health()
        if not is_healthy:
            raise ConnectionError("Redis server is unhealthy")

        for ev in events:
            try:
                # Publish payload to Redis Pub/Sub
                await redis_client.publish(EVENTS_CHANNEL, ev["payload"])
                success_ids.append(ev["id"])
                
                # Observe metrics
                outbox_published_total.inc()
                created_aware = ev["created_at"].replace(tzinfo=timezone.utc) if ev["created_at"].tzinfo is None else ev["created_at"]
                latency = (datetime.now(timezone.utc) - created_aware).total_seconds()
                outbox_publish_duration.observe(latency)
            except Exception as e:
                outbox_publish_failures_total.inc()
                logger.error(f"Failed to publish outbox event {ev['id']} to Redis: {e}")
                failed_updates.append({
                    "id": ev["id"],
                    "reason": str(e)
                })

        # Save success / fail statuses
        await mark_results(success_ids, failed_updates)
        return len(events)
        
    except Exception as e:
        logger.error(f"Error processing outbox events: {e}")
        return 0

async def update_outbox_metrics():
    """
    Periodically updates the gauge metrics for pending outbox count and oldest pending event age.
    """
    try:
        now = datetime.now(timezone.utc)
        async with SessionLocal() as db:
            # 1. Count pending events (attempts < 4 and published_at is NULL)
            count_stmt = (
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .where(OutboxEvent.attempts < 4)
            )
            res = await db.execute(count_stmt)
            pending_count = len(res.scalars().all())
            outbox_pending_total.set(pending_count)

            # 2. Get oldest pending event age
            oldest_stmt = (
                select(OutboxEvent.created_at)
                .where(OutboxEvent.published_at.is_(None))
                .where(OutboxEvent.attempts < 4)
                .order_by(OutboxEvent.created_at.asc())
                .limit(1)
            )
            res_oldest = await db.execute(oldest_stmt)
            oldest_created = res_oldest.scalars().first()
            
            if oldest_created:
                oldest_aware = oldest_created.replace(tzinfo=timezone.utc) if oldest_created.tzinfo is None else oldest_created
                age = (now - oldest_aware).total_seconds()
                outbox_oldest_pending_age.set(age)
            else:
                outbox_oldest_pending_age.set(0)
    except Exception as e:
        logger.error(f"Failed to update outbox metrics: {e}")

async def start_outbox_publisher(stop_event: asyncio.Event = None):
    """
    Outbox Publisher daemon. Listens on wakeup events or wakes up every 5.0 seconds.
    """
    logger.info("Starting Outbox Publisher background task...")
    metrics_tick = 0
    
    while stop_event is None or not stop_event.is_set():
        try:
            # Update metrics every 5 seconds
            metrics_tick += 1
            if metrics_tick >= 5:
                metrics_tick = 0
                await update_outbox_metrics()

            # Process events until no more are found
            while True:
                processed = await process_outbox_events()
                if processed == 0:
                    break
                    
            # Wait for wakeup trigger or timeout (default 1s to ensure real-time latency catchup)
            try:
                await asyncio.wait_for(_wakeup_event.wait(), timeout=1.0)
                _wakeup_event.clear()
            except asyncio.TimeoutError:
                pass
                
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Outbox Publisher loop encountered error: {e}. Retrying in 3s...")
            await asyncio.sleep(3.0)
            
    logger.info("Stopped Outbox Publisher background task.")


async def cleanup_old_published_events(retention_days: int = 7):
    """
    Deletes successfully published outbox events older than retention_days.
    Never deletes unpublished events.
    """
    logger.info(f"Starting outbox cleanup for published events older than {retention_days} days...")
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    try:
        async with SessionLocal() as db:
            async with db.begin():
                stmt = (
                    delete(OutboxEvent)
                    .where(OutboxEvent.published_at.is_not(None))
                    .where(OutboxEvent.published_at <= cutoff)
                )
                res = await db.execute(stmt)
                logger.info(f"Cleaned up {res.rowcount} published outbox events.")
    except Exception as e:
        logger.error(f"Outbox event cleanup failed: {e}")


async def start_outbox_cleanup_daemon(stop_event: asyncio.Event = None, retention_days: int = 7):
    """
    Outbox Cleanup daemon. Runs every 1 hour.
    """
    logger.info("Starting Outbox Cleanup background task...")
    while stop_event is None or not stop_event.is_set():
        try:
            await cleanup_old_published_events(retention_days)
            # Sleep 1 hour (polled in 10s increments to support clean cancellation)
            for _ in range(360):
                if stop_event and stop_event.is_set():
                    break
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Outbox Cleanup loop encountered error: {e}. Retrying in 60s...")
            await asyncio.sleep(60.0)
    logger.info("Stopped Outbox Cleanup background task.")
