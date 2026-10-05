import asyncio
import json
import logging
import os
import uuid
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Response, status
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import select
from sqlalchemy.sql import func

from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.models.scheduled_message import ScheduledMessage
from app.models.message import Message
from app.models.conversation import Conversation
from app.queue.client import check_redis_health, redis_client
from app.queue.consumer import start_consumer
from app.queue.retry import schedule_retry
from app.queue.metrics import (
    worker_jobs_processed_total,
    worker_jobs_failed_total,
    worker_job_duration,
    queue_processing_duration,
    jobs_dead_lettered_total,
    scheduled_messages_sent_total,
    scheduled_messages_failed_total,
)

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] worker: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("worker")

DLQ_NAME = "latext:scheduled:dead-letter"


async def process_callback(scheduled_message_id: str, payload_data: dict = None):
    """
    Executes worker processing logic: claims job, manages state transitions,
    verifies idempotency, and coordinates retries or DLQ handoff.
    """
    sm_id = uuid.UUID(str(scheduled_message_id))
    start_time = time.time()
    db_message = None
    scheduled_at_utc_val = None
    trigger_dlq_push = False
    dlq_reason = ""

    # Timing metrics variables
    t0 = t1 = t2 = t3 = t4 = t5 = t6 = t7 = t8 = t9 = t10 = t11 = None
    t4 = time.time()

    # Extract upstream timestamps from payload if available
    if payload_data:
        t0 = payload_data.get("t0")
        t1 = payload_data.get("t1")
        t2 = payload_data.get("t2")
        t3 = payload_data.get("t3")
        
        # Observe queue wait and enqueued-to-dequeued latencies
        from app.queue.metrics import queue_wait_latency, enqueue_to_dequeue_latency, dequeue_to_processing_latency
        if t2 is not None and t3 is not None:
            queue_wait_latency.observe(t3 - t2)
            enqueue_to_dequeue_latency.observe(t3 - t2)
        if t3 is not None:
            dequeue_to_processing_latency.observe(t4 - t3)

    try:
        t5 = time.time()
        async with SessionLocal() as db:
            async with db.begin():
                # Lock row with FOR UPDATE SKIP LOCKED
                stmt = (
                    select(ScheduledMessage)
                    .where(ScheduledMessage.id == sm_id)
                    .with_for_update(skip_locked=True)
                )
                res = await db.execute(stmt)
                scheduled = res.scalars().first()

                if not scheduled:
                    logger.warning(f"Could not acquire row lock for job {sm_id} (already claimed).")
                    return

                scheduled_at_utc_val = scheduled.scheduled_at_utc

                # Validate execution state: expect QUEUED or SCHEDULED
                if scheduled.status not in ("QUEUED", "SCHEDULED"):
                    logger.warning(f"Job {sm_id} is in status '{scheduled.status}', skipping execution.")
                    return

                if scheduled.attempt_count >= settings.MAX_SCHEDULED_MESSAGE_ATTEMPTS:
                    logger.warning(f"Job {sm_id} exceeded max attempts ({scheduled.attempt_count}). Transitioning to FAILED_PENDING_DLQ.")
                    scheduled.status = "FAILED_PENDING_DLQ"
                    scheduled.failure_reason = "Max retry attempts exceeded"
                    await db.flush()
                    trigger_dlq_push = True
                    dlq_reason = "Max retry attempts exceeded"

                if not trigger_dlq_push:
                    # Increment attempt count
                    scheduled.attempt_count += 1
                    scheduled_at_utc_val = scheduled.scheduled_at_utc

                    # 1. Idempotency Check: does Message already exist?
                    msg_stmt = select(Message).where(Message.scheduled_message_id == sm_id)
                    msg_res = await db.execute(msg_stmt)
                    existing_message = msg_res.scalars().first()

                    if existing_message:
                        logger.warning(f"Idempotency hit: Message for job {sm_id} already exists. Transitioning to SENT.")
                        scheduled.status = "SENT"
                        scheduled.sent_at = func.now()
                        db_message = existing_message
                        worker_jobs_processed_total.inc()
                        t7 = time.time()
                        t6 = t5
                        return

                    # 2. Create the actual Message with explicit ID
                    logger.info(f"Persisting chat Message linked to job {sm_id}")
                    msg_id = uuid.uuid4()
                    db_message = Message(
                        id=msg_id,
                        conversation_id=scheduled.conversation_id,
                        sender_id=scheduled.sender_id,
                        content=scheduled.content,
                        message_type=scheduled.message_type,
                        status="SENT",
                        scheduled_message_id=scheduled.id
                    )
                    db.add(db_message)
                    t6 = time.time()

                    # 3. Update conversation activity directly without SELECT
                    from app.models.conversation import Conversation, ConversationParticipant
                    from sqlalchemy import update
                    await db.execute(
                        update(Conversation)
                        .where(Conversation.id == scheduled.conversation_id)
                        .values(updated_at=func.now())
                    )

                    # Fetch participants to identify the recipient
                    part_stmt = select(ConversationParticipant.user_id).where(
                        ConversationParticipant.conversation_id == scheduled.conversation_id
                    )
                    part_res = await db.execute(part_stmt)
                    participant_ids = part_res.scalars().all()
                    recipient_id = next((pid for pid in participant_ids if pid != scheduled.sender_id), None)

                    if scheduled_at_utc_val:
                        scheduled_aware = scheduled_at_utc_val.replace(tzinfo=timezone.utc) if scheduled_at_utc_val.tzinfo is None else scheduled_at_utc_val
                        latency = (datetime.now(timezone.utc) - scheduled_aware).total_seconds()
                        queue_processing_duration.observe(latency)
                        logger.info(f"Job {sm_id} completed successfully. Queue latency was {latency:.2f}s")

                    # Insert Outbox Event
                    if recipient_id:
                        from app.models.outbox import OutboxEvent
                        
                        event_payload = {
                            "event_type": "message.created",
                            "version": 1,
                            "timestamp": time.time(),
                            "message_id": str(msg_id),
                            "conversation_id": str(scheduled.conversation_id),
                            "recipient_user_id": str(recipient_id),
                            "sender_user_id": str(scheduled.sender_id)
                        }
                        
                        outbox_event = OutboxEvent(
                            event_type="message.created",
                            event_version=1,
                            aggregate_id=str(msg_id),
                            payload=json.dumps(event_payload)
                        )
                        db.add(outbox_event)

                    # 4. Finalize state to SENT
                    scheduled.status = "SENT"
                    scheduled.sent_at = func.now()
                    scheduled_messages_sent_total.inc()
                    await db.flush()

        t7 = time.time()
        if trigger_dlq_push:
            from app.queue.retry import publish_to_dlq
            success = await publish_to_dlq(sm_id, dlq_reason)
            if success:
                jobs_dead_lettered_total.inc()
                scheduled_messages_failed_total.inc()
            return

        from app.queue.metrics import worker_db_transaction_latency, worker_message_creation_latency
        worker_db_transaction_latency.observe(t7 - t5)
        if t6 is not None:
            worker_message_creation_latency.observe(t6 - t5)

        duration = time.time() - start_time
        worker_job_duration.observe(duration)
        worker_jobs_processed_total.inc()

        # 5. Hand off WebSocket delivery to backend
        db_only_mode = os.getenv("BENCHMARK_DB_ONLY") == "true"
        if db_only_mode:
            logger.info(f"DB-Only mode active. Skipping handoff for message: {db_message.id if db_message else None}")
            t8 = t9 = t10 = t11 = t7
            
            from app.queue.metrics import worker_processing_latency, processing_latency, scheduled_to_delivery_latency
            worker_processing_latency.observe(t11 - t4)
            processing_latency.observe(t11 - t4)
            if t0 is not None:
                scheduled_to_delivery_latency.observe(t11 - t0)

            stats_dict = {
                "scheduled_message_id": str(sm_id),
                "t0": t0, "t1": t1, "t2": t2, "t3": t3, "t4": t4,
                "t5": t5, "t6": t6, "t7": t7, "t8": t8, "t9": t9,
                "t10": t10, "t11": t11
            }
            try:
                await redis_client.rpush("latext:benchmark:stats", json.dumps(stats_dict))
            except Exception as redis_err:
                logger.error(f"Failed to record benchmark metrics to Redis: {redis_err}")
            worker_jobs_processed_total.inc()
        elif db_message:
            # Trigger outbox publisher to deliver immediately in background
            if recipient_id:
                try:
                    from app.events.outbox_publisher import trigger_outbox_publish
                    trigger_outbox_publish()
                except Exception as pub_err:
                    logger.error(f"Failed to trigger outbox publish event: {pub_err}")

            asyncio.create_task(
                do_handoff_for_message(
                    str(db_message.id),
                    str(sm_id),
                    t0=t0, t1=t1, t2=t2, t3=t3, t4=t4,
                    t5=t5, t6=t6, t7=t7
                )
            )
            worker_jobs_processed_total.inc()
        else:
            t8 = t9 = t10 = t11 = t7
            stats_dict = {
                "scheduled_message_id": str(sm_id),
                "t0": t0, "t1": t1, "t2": t2, "t3": t3, "t4": t4,
                "t5": t5, "t6": t6, "t7": t7, "t8": t8, "t9": t9,
                "t10": t10, "t11": t11
            }
            try:
                await redis_client.rpush("latext:benchmark:stats", json.dumps(stats_dict))
            except Exception as redis_err:
                logger.error(f"Failed to record benchmark metrics to Redis: {redis_err}")

    except Exception as e:
        logger.error(f"Error executing worker task for job {sm_id}: {e}", exc_info=True)
        worker_jobs_failed_total.inc()

        # Manage failures & schedule retries inside a separate session
        trigger_dlq_push = False
        trigger_retry = False
        dlq_reason = ""
        attempts = 0
        try:
            async with SessionLocal() as db_fail:
                async with db_fail.begin():
                    result = await db_fail.execute(
                        select(ScheduledMessage).where(ScheduledMessage.id == sm_id)
                    )
                    sm_fail = result.scalars().first()
                    if sm_fail:
                        sm_fail.attempt_count += 1
                        attempts = sm_fail.attempt_count
                        if attempts < settings.MAX_SCHEDULED_MESSAGE_ATTEMPTS:
                            # Revert back to QUEUED for retry
                            logger.info(f"Rescheduling job {sm_id} for retry. Attempt count: {attempts}")
                            sm_fail.status = "QUEUED"
                            sm_fail.processing_started_at = None
                            sm_fail.failure_reason = str(e)
                            await db_fail.flush()
                            trigger_retry = True
                        else:
                            # Mark as FAILED_PENDING_DLQ
                            logger.warning(f"Job {sm_id} failed and exhausted max retries ({attempts}). Transitioning to FAILED_PENDING_DLQ.")
                            sm_fail.status = "FAILED_PENDING_DLQ"
                            sm_fail.failure_reason = f"Max attempts exhausted. Last error: {e}"
                            await db_fail.flush()
                            trigger_dlq_push = True
                            dlq_reason = f"Max attempts exhausted. Last error: {e}"

            if trigger_retry:
                # Schedule delayed retry in Redis outside transaction
                await schedule_retry(str(sm_id), attempts)
            elif trigger_dlq_push:
                # Push to DLQ list in Redis outside transaction
                from app.queue.retry import publish_to_dlq
                success = await publish_to_dlq(sm_id, dlq_reason)
                if success:
                    jobs_dead_lettered_total.inc()
                    scheduled_messages_failed_total.inc()
        except Exception as fail_err:
            logger.error(f"Failed to record execution error status for job {sm_id}: {fail_err}")
async def do_handoff_for_message(
    message_id: str,
    sm_id: str,
    t0: float = None,
    t1: float = None,
    t2: float = None,
    t3: float = None,
    t4: float = None,
    t5: float = None,
    t6: float = None,
    t7: float = None
):
    t8 = time.time()
    t9 = t10 = t11 = t8

    if t11 is None:
        t11 = time.time()

    if t4 is not None:
        from app.queue.metrics import worker_processing_latency, processing_latency
        worker_processing_latency.observe(t11 - t4)
        processing_latency.observe(t11 - t4)
    if t0 is not None:
        from app.queue.metrics import scheduled_to_delivery_latency
        scheduled_to_delivery_latency.observe(t11 - t0)

    stats_dict = {
        "scheduled_message_id": sm_id,
        "t0": t0, "t1": t1, "t2": t2, "t3": t3, "t4": t4,
        "t5": t5, "t6": t6, "t7": t7, "t8": t8, "t9": t9,
        "t10": t10, "t11": t11
    }
    try:
        await redis_client.rpush("latext:benchmark:stats", json.dumps(stats_dict))
    except Exception as redis_err:
        logger.error(f"Failed to record benchmark metrics: {redis_err}")


async def process_batch_callback(payloads: list[dict]) -> None:
    t5 = time.time()
    sm_ids = [p["scheduled_message_id"] for p in payloads if "scheduled_message_id" in p]
    if not sm_ids:
        return
        
    payload_map = {p["scheduled_message_id"]: p for p in payloads if "scheduled_message_id" in p}
    
    try:
        # Try to process all messages in the batch in a single transaction (Fast Path)
        async with SessionLocal() as db:
            async with db.begin():
                # 1. Lock all rows using skip_locked to avoid blocking worker slots
                import uuid
                stmt = (
                    select(ScheduledMessage)
                    .where(ScheduledMessage.id.in_([uuid.UUID(i) for i in sm_ids]))
                    .with_for_update(skip_locked=True)
                )
                res = await db.execute(stmt)
                scheduled_list = res.scalars().all()

                if not scheduled_list:
                    return

                # Exclude any that are not QUEUED or SCHEDULED or exceeded max attempts
                active_scheduled = [
                    s for s in scheduled_list 
                    if s.status in ("QUEUED", "SCHEDULED") and s.attempt_count < settings.MAX_SCHEDULED_MESSAGE_ATTEMPTS
                ]
                if not active_scheduled:
                    return

                # Increment attempt count
                for s in active_scheduled:
                    s.attempt_count += 1

                # 2. Check existing messages for idempotency
                active_ids = [s.id for s in active_scheduled]
                msg_stmt = select(Message).where(Message.scheduled_message_id.in_(active_ids))
                msg_res = await db.execute(msg_stmt)
                existing_messages = {m.scheduled_message_id: m for m in msg_res.scalars().all()}

                # Process each scheduled message
                messages_to_insert = []
                conversations_to_update = set()
                handoff_items = []

                for s in active_scheduled:
                    str_id = str(s.id)
                    p = payload_map.get(str_id, {})
                    
                    if s.id in existing_messages:
                        # Idempotency hit
                        s.status = "SENT"
                        s.sent_at = func.now()
                        db_message = existing_messages[s.id]
                        worker_jobs_processed_total.inc()
                        # Record handoff item (for metrics)
                        handoff_items.append({
                            "message_id": str(db_message.id),
                            "sm_id": str_id,
                            "payload": p,
                            "t6": t5,
                            "is_dup": True
                        })
                        continue

                    # Create the actual Message with explicit ID
                    msg_id = uuid.uuid4()
                    db_message = Message(
                        id=msg_id,
                        conversation_id=s.conversation_id,
                        sender_id=s.sender_id,
                        content=s.content,
                        message_type=s.message_type,
                        status="SENT",
                        scheduled_message_id=s.id
                    )
                    db.add(db_message)
                    messages_to_insert.append((db_message, s))
                    conversations_to_update.add(s.conversation_id)

                    # Update status
                    s.status = "SENT"
                    s.sent_at = func.now()

                # Update conversation activity for all updated conversations directly
                if conversations_to_update:
                    from app.models.conversation import Conversation
                    from sqlalchemy import update
                    await db.execute(
                        update(Conversation)
                        .where(Conversation.id.in_(list(conversations_to_update)))
                        .values(updated_at=func.now())
                    )

                # Fetch participant IDs for all conversations to identify recipient IDs
                part_stmt = select(ConversationParticipant.conversation_id, ConversationParticipant.user_id).where(
                    ConversationParticipant.conversation_id.in_(list(conversations_to_update))
                )
                part_res = await db.execute(part_stmt)
                participants_map = {}
                for conv_id, user_id in part_res.all():
                    if conv_id not in participants_map:
                        participants_map[conv_id] = []
                    participants_map[conv_id].append(user_id)

                # Insert Outbox Events
                from app.models.outbox import OutboxEvent
                for msg, s in messages_to_insert:
                    part_ids = participants_map.get(s.conversation_id, [])
                    recipient_id = next((pid for pid in part_ids if pid != s.sender_id), None)
                    if recipient_id:
                        event_payload = {
                            "event_type": "message.created",
                            "version": 1,
                            "timestamp": time.time(),
                            "message_id": str(msg.id),
                            "conversation_id": str(s.conversation_id),
                            "recipient_user_id": str(recipient_id),
                            "sender_user_id": str(s.sender_id)
                        }
                        outbox_event = OutboxEvent(
                            event_type="message.created",
                            event_version=1,
                            aggregate_id=str(msg.id),
                            payload=json.dumps(event_payload)
                        )
                        db.add(outbox_event)

                # Flush all inserts/updates in one go
                await db.flush()

                t6 = time.time()
                # Save handoff items after flushing (so db_message.id is generated)
                for msg, s in messages_to_insert:
                    p = payload_map.get(str(s.id), {})
                    part_ids = participants_map.get(s.conversation_id, [])
                    recipient_id = next((pid for pid in part_ids if pid != s.sender_id), None)
                    handoff_items.append({
                        "message_id": str(msg.id),
                        "sm_id": str(s.id),
                        "payload": p,
                        "t6": t6,
                        "is_dup": False,
                        "recipient_id": str(recipient_id) if recipient_id else None,
                        "sender_id": str(s.sender_id),
                        "conversation_id": str(s.conversation_id)
                    })
                    scheduled_messages_sent_total.inc()

        t7 = time.time()
        
        # Observe database latencies
        from app.queue.metrics import worker_db_transaction_latency
        worker_db_transaction_latency.observe(t7 - t5)

        # Trigger handoffs outside transaction
        for item in handoff_items:
            p = item["payload"]
            db_only_mode = os.getenv("BENCHMARK_DB_ONLY") == "true"
            if db_only_mode:
                # Log metrics directly
                t11 = t7
                t4 = p.get("t4")
                t0 = p.get("t0")
                if t4 is not None:
                    from app.queue.metrics import worker_processing_latency, processing_latency
                    worker_processing_latency.observe(t11 - t4)
                    processing_latency.observe(t11 - t4)
                if t0 is not None:
                    from app.queue.metrics import scheduled_to_delivery_latency
                    scheduled_to_delivery_latency.observe(t11 - t0)
                stats_dict = {
                    "scheduled_message_id": item["sm_id"],
                    "t0": t0, "t1": p.get("t1"), "t2": p.get("t2"), "t3": p.get("t3"), "t4": t4,
                    "t5": t5, "t6": item["t6"], "t7": t7, "t8": t7, "t9": t7, "t10": t7, "t11": t7
                }
                try:
                    await redis_client.rpush("latext:benchmark:stats", json.dumps(stats_dict))
                except Exception as redis_err:
                    logger.error(f"Failed to record benchmark metrics: {redis_err}")
                worker_jobs_processed_total.inc()
            else:
                if not item.get("is_dup") and item.get("recipient_id"):
                    try:
                        from app.events.outbox_publisher import trigger_outbox_publish
                        trigger_outbox_publish()
                    except Exception as pub_err:
                        logger.error(f"Failed to trigger outbox publish event: {pub_err}")

                asyncio.create_task(
                    do_handoff_for_message(
                        item["message_id"],
                        item["sm_id"],
                        t0=p.get("t0"),
                        t1=p.get("t1"),
                        t2=p.get("t2"),
                        t3=p.get("t3"),
                        t4=p.get("t4"),
                        t5=t5,
                        t6=item["t6"],
                        t7=t7
                    )
                )
                if not item["is_dup"]:
                    worker_jobs_processed_total.inc()

    except Exception as e:
        logger.warning(f"Batch execution failed: {e}. Falling back to single-job processing.")
        # Rollback happened automatically. Now process each message one-by-one (Slow Path fallback)
        for sm_id in sm_ids:
            try:
                p = payload_map.get(sm_id, {})
                await process_callback(sm_id, payload_data=p)
            except Exception as single_err:
                logger.error(f"Single fallback processing failed for job {sm_id}: {single_err}")


# --- Lifespan and API setup ---

# Shared HTTP connection pool client
http_client: httpx.AsyncClient = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    # Initialize shared HTTP client connection pool
    limits = httpx.Limits(max_keepalive_connections=50, max_connections=100)
    http_client = httpx.AsyncClient(limits=limits)

    # Launch background consumer task
    import os
    is_testing = os.getenv("TESTING", "false").lower() == "true"
    task = None
    if not is_testing:
        batch_size = int(os.getenv("WORKER_BATCH_SIZE", "1"))
        if batch_size > 1:
            task = asyncio.create_task(start_consumer(process_callback, process_batch_callback=process_batch_callback))
        else:
            task = asyncio.create_task(start_consumer(process_callback))
    yield
    # Shutdown
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    # Close shared HTTP connection pool
    if http_client:
        await http_client.aclose()



app = FastAPI(
    title="Latext Scheduled Message Worker Node",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """
    Checks health of DB and Redis connections.
    """
    redis_healthy = await check_redis_health()
    
    db_healthy = False
    try:
        async with SessionLocal() as db:
            await db.execute(select(func.now()))
            db_healthy = True
    except Exception:
        pass

    overall_status = "healthy" if (redis_healthy and db_healthy) else "unhealthy"

    return {
        "status": overall_status,
        "database_connected": db_healthy,
        "redis_connected": redis_healthy
    }


@app.get("/metrics")
async def get_metrics():
    """
    Prometheus metrics scrape target.
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    import uvicorn
    logger.info("Starting worker node application server...")
    uvicorn.run("app.worker.worker:app", host="0.0.0.0", port=8001)
