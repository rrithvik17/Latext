import asyncio
import json
import uuid
import time
from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import select, and_

from app.core.config import settings
from app.models.scheduled_message import ScheduledMessage
from app.models.message import Message
from app.queue.producer import enqueue_job
from app.queue.retry import schedule_retry, check_and_enqueue_retries, get_retry_delay
from app.scheduler.scheduler import process_due_messages, recover_stalled_messages
from app.worker.worker import process_callback


# --- Queue & State Machine Tests ---

@pytest.mark.asyncio
async def test_job_enqueue_and_pop(mock_redis_injection):
    mock_r = mock_redis_injection
    job_id = str(uuid.uuid4())

    # 1. Enqueue job
    await enqueue_job(job_id)
    assert len(mock_r.lists["latext:scheduled:queue"]) == 1

    # 2. Pop job
    res = await mock_r.blpop("latext:scheduled:queue", timeout=1)
    assert res is not None
    assert json.loads(res[1])["scheduled_message_id"] == job_id


@pytest.mark.asyncio
async def test_scheduler_atomic_enqueue_workflow(db, mock_redis_injection, create_conversation):
    mock_r = mock_redis_injection
    conv, u1, _ = await create_conversation()
    
    # Create due scheduled message
    sm = ScheduledMessage(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        sender_id=u1.id,
        content="Due atomic enqueuing message",
        message_type="TEXT",
        scheduled_at_utc=datetime.now(timezone.utc) - timedelta(minutes=2),
        timezone="UTC",
        status="SCHEDULED"
    )
    db.add(sm)
    await db.commit()
    await db.refresh(sm)

    # Run scheduler process
    await process_due_messages()

    # Verify status changed to QUEUED and it is in Redis
    await db.refresh(sm)
    assert sm.status == "QUEUED"
    assert len(mock_r.lists["latext:scheduled:queue"]) == 1


@pytest.mark.asyncio
async def test_scheduler_redis_outage_resilience(db, mock_redis_injection, create_conversation):
    mock_r = mock_redis_injection
    mock_r.fail_rpush = True  # Simulate Redis outage during push
    conv, u1, _ = await create_conversation()

    sm = ScheduledMessage(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        sender_id=u1.id,
        content="Outage message",
        message_type="TEXT",
        scheduled_at_utc=datetime.now(timezone.utc) - timedelta(minutes=2),
        timezone="UTC",
        status="SCHEDULED"
    )
    db.add(sm)
    await db.commit()
    await db.refresh(sm)

    # Run scheduler process. It should raise error and rollback.
    await process_due_messages()

    # Verify status remains SCHEDULED
    await db.refresh(sm)
    assert sm.status == "SCHEDULED"


@pytest.mark.asyncio
async def test_worker_successful_processing_lifecycles(db, create_conversation):
    conv, u1, _ = await create_conversation()
    sm = ScheduledMessage(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        sender_id=u1.id,
        content="Queue message lifecycle",
        message_type="TEXT",
        scheduled_at_utc=datetime.now(timezone.utc) - timedelta(minutes=2),
        timezone="UTC",
        status="QUEUED"
    )
    db.add(sm)
    await db.commit()

    # Run worker process_callback
    await process_callback(str(sm.id))

    # Verify DB statuses updated correctly
    await db.refresh(sm)
    assert sm.status == "SENT"
    assert sm.sent_at is not None

    # Check Message created
    stmt = select(Message).where(Message.scheduled_message_id == sm.id)
    res = await db.execute(stmt)
    msg = res.scalars().first()
    assert msg is not None
    assert msg.content == "Queue message lifecycle"


@pytest.mark.asyncio
async def test_worker_processing_failure_and_retry(db, mock_redis_injection, monkeypatch, create_conversation):
    mock_r = mock_redis_injection
    conv, u1, _ = await create_conversation()
    
    # Mock database flush to raise an exception on the first call (message execution),
    # but succeed on subsequent calls (status/retry logging).
    from sqlalchemy.ext.asyncio import AsyncSession
    original_flush = AsyncSession.flush
    flush_count = 0

    async def mock_flush(self, *args, **kwargs):
        nonlocal flush_count
        flush_count += 1
        if flush_count == 1:
            raise Exception("Mocked database flush failure")
        return await original_flush(self, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "flush", mock_flush)

    sm = ScheduledMessage(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        sender_id=u1.id,
        content="Failing message",
        message_type="TEXT",
        scheduled_at_utc=datetime.now(timezone.utc) - timedelta(minutes=2),
        timezone="UTC",
        status="QUEUED",
        attempt_count=1
    )
    db.add(sm)
    await db.commit()

    # Run worker
    await process_callback(str(sm.id))

    # Verify status went back to QUEUED, attempts incremented to 2, and scheduled in retry set
    await db.refresh(sm)
    assert sm.status == "QUEUED"
    assert sm.attempt_count == 2
    assert sm.failure_reason is not None

    # Verify it is scheduled in the Redis retry set
    assert len(mock_r.zsets["latext:scheduled:retry"]) == 1


def test_retry_delay_calculations():
    assert get_retry_delay(1) == 0      # Attempt 1: immediate
    assert get_retry_delay(2) == 10     # Attempt 2: short delay
    assert get_retry_delay(3) == 30     # Attempt 3: longer delay
    assert get_retry_delay(4) == 90     # Attempt 4: max delay


@pytest.mark.asyncio
async def test_dead_letter_queue_routing(db, mock_redis_injection, create_conversation):
    mock_r = mock_redis_injection
    conv, u1, _ = await create_conversation()
    
    # Message has already hit max attempts (4)
    sm = ScheduledMessage(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        sender_id=u1.id,
        content="Dead letter job",
        message_type="TEXT",
        scheduled_at_utc=datetime.now(timezone.utc) - timedelta(minutes=2),
        timezone="UTC",
        status="QUEUED",
        attempt_count=4  # Max attempts reached
    )
    db.add(sm)
    await db.commit()

    # Run worker
    await process_callback(str(sm.id))

    # Verify status is FAILED in DB and pushed to DLQ
    from app.core.database import SessionLocal as TestingSessionLocal
    async with TestingSessionLocal() as fresh_db:
        res = await fresh_db.execute(select(ScheduledMessage).where(ScheduledMessage.id == sm.id))
        sm_fresh = res.scalars().first()
        assert sm_fresh.status == "FAILED"
        assert sm_fresh.failure_reason == "Max retry attempts exceeded"
    assert len(mock_r.lists["latext:scheduled:dead-letter"]) == 1


@pytest.mark.asyncio
async def test_redis_failure_after_db_commit(db, mock_redis_injection, create_conversation):
    mock_r = mock_redis_injection
    conv, u1, _ = await create_conversation()
    # Message at max attempts
    sm = ScheduledMessage(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        sender_id=u1.id,
        content="Failed message",
        message_type="TEXT",
        scheduled_at_utc=datetime.now(timezone.utc) - timedelta(minutes=2),
        timezone="UTC",
        status="QUEUED",
        attempt_count=4
    )
    db.add(sm)
    await db.commit()

    # Make Redis fail rpush
    mock_r.fail_rpush = True

    # Run worker -> fails to publish to DLQ but commits FAILED_PENDING_DLQ to Postgres
    await process_callback(str(sm.id))

    # Verify status is FAILED_PENDING_DLQ
    from app.core.database import SessionLocal as TestingSessionLocal
    async with TestingSessionLocal() as fresh_db:
        res = await fresh_db.execute(select(ScheduledMessage).where(ScheduledMessage.id == sm.id))
        sm_fresh = res.scalars().first()
        assert sm_fresh.status == "FAILED_PENDING_DLQ"
        assert sm_fresh.failure_reason == "Max retry attempts exceeded"

    # Restore Redis and run scheduler recovery
    mock_r.fail_rpush = False
    from app.scheduler.scheduler import recover_stalled_messages
    await recover_stalled_messages()

    # Verify status is now FAILED in DB and pushed to DLQ
    async with TestingSessionLocal() as fresh_db:
        res = await fresh_db.execute(select(ScheduledMessage).where(ScheduledMessage.id == sm.id))
        sm_fresh = res.scalars().first()
        assert sm_fresh.status == "FAILED"
    assert len(mock_r.lists["latext:scheduled:dead-letter"]) == 1


@pytest.mark.asyncio
async def test_duplicate_dlq_publication(db, mock_redis_injection, create_conversation):
    mock_r = mock_redis_injection
    conv, u1, _ = await create_conversation()
    # Message is already FAILED
    sm = ScheduledMessage(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        sender_id=u1.id,
        content="Idempotent check",
        message_type="TEXT",
        scheduled_at_utc=datetime.now(timezone.utc) - timedelta(minutes=2),
        timezone="UTC",
        status="FAILED",
        attempt_count=4
    )
    db.add(sm)
    await db.commit()

    # Re-run worker
    await process_callback(str(sm.id))

    # Verify no Message is created in DB
    from app.core.database import SessionLocal as TestingSessionLocal
    async with TestingSessionLocal() as fresh_db:
        res = await fresh_db.execute(select(Message).where(Message.scheduled_message_id == sm.id))
        messages = res.scalars().all()
        assert len(messages) == 0


@pytest.mark.asyncio
async def test_concurrent_failures(db, mock_redis_injection, create_conversation):
    mock_r = mock_redis_injection
    conv, u1, _ = await create_conversation()
    # Create two due messages at max attempts
    sm1 = ScheduledMessage(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        sender_id=u1.id,
        content="Concurrent fail 1",
        message_type="TEXT",
        scheduled_at_utc=datetime.now(timezone.utc) - timedelta(minutes=2),
        timezone="UTC",
        status="QUEUED",
        attempt_count=4
    )
    sm2 = ScheduledMessage(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        sender_id=u1.id,
        content="Concurrent fail 2",
        message_type="TEXT",
        scheduled_at_utc=datetime.now(timezone.utc) - timedelta(minutes=2),
        timezone="UTC",
        status="QUEUED",
        attempt_count=4
    )
    db.add_all([sm1, sm2])
    await db.commit()

    # Run them concurrently using asyncio.gather
    await asyncio.gather(
        process_callback(str(sm1.id)),
        process_callback(str(sm2.id))
    )

    # Verify both are FAILED in DB and pushed to DLQ
    from app.core.database import SessionLocal as TestingSessionLocal
    async with TestingSessionLocal() as fresh_db:
        res = await fresh_db.execute(select(ScheduledMessage).where(ScheduledMessage.id.in_([sm1.id, sm2.id])))
        failures = res.scalars().all()
        assert len(failures) == 2
        for f in failures:
            assert f.status == "FAILED"
    assert len(mock_r.lists["latext:scheduled:dead-letter"]) == 2



def test_connection_budget():
    import os
    import re
    
    # 1. Resolve k8s folder path relative to this file
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    k8s_dir = os.path.join(os.path.dirname(base_dir), "k8s")
    
    def get_replicas(filename):
        path = os.path.join(k8s_dir, filename)
        if not os.path.exists(path):
            return 1
        with open(path, "r") as f:
            content = f.read()
        matches = re.findall(r"replicas:\s*(\d+)", content)
        return int(matches[0]) if matches else 1

    b_repl = get_replicas("backend.yaml")
    w_repl = get_replicas("worker.yaml")
    s_repl = get_replicas("scheduler.yaml")

    # 2. Get database pool configuration (default config or env)
    from app.core.database import POOL_SIZE, MAX_OVERFLOW
    
    # Total connections per pod
    conn_per_pod = POOL_SIZE + MAX_OVERFLOW
    
    # Calculate connection budget
    total_connections = (b_repl + w_repl + s_repl) * conn_per_pod
    
    # Documented PostgreSQL limit
    max_connections = 300
    reserve = 50
    safe_budget = max_connections - reserve
    
    # Assert connection safety
    assert total_connections <= safe_budget, (
        f"Calculated connection footprint ({total_connections}) exceeds safe PostgreSQL capacity ({safe_budget}). "
        f"Backend replicas: {b_repl}, Worker replicas: {w_repl}, Scheduler replicas: {s_repl}, pool size: {conn_per_pod}."
    )

