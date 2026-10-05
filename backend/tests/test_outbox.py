import asyncio
import json
import uuid
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from app.events.outbox_publisher import process_outbox_events, start_outbox_publisher
from app.models.message import Message
from app.models.outbox import OutboxEvent
from app.models.scheduled_message import ScheduledMessage
from app.core.database import SessionLocal
from sqlalchemy import select, delete




@pytest.mark.asyncio
async def test_crash_test_1_commit_then_publish(db, mock_redis_injection, create_conversation):
    """
    Crash Test 1:
    1. Begin message transaction.
    2. Insert Message & Outbox event.
    3. Commit.
    4. Verify publisher eventually publishes the event.
    """
    mock_r = mock_redis_injection
    conv, u1, _ = await create_conversation()
    msg_id = uuid.uuid4()
    
    # 1. Begin transaction, insert message & outbox
    db_msg = Message(
        id=msg_id,
        conversation_id=conv.id,
        sender_id=u1.id,
        content="Crash Test 1 Content",
        message_type="TEXT",
        status="SENT"
    )
    db.add(db_msg)
    
    event_payload = {
        "event_type": "message.created",
        "version": 1,
        "timestamp": datetime.now(timezone.utc).timestamp(),
        "message_id": str(msg_id)
    }
    db_outbox = OutboxEvent(
        id=uuid.uuid4(),
        event_type="message.created",
        event_version=1,
        aggregate_id=str(msg_id),
        payload=json.dumps(event_payload)
    )
    db.add(db_outbox)
    await db.commit()
    
    # Verify records exist in PostgreSQL
    msg_db = (await db.execute(select(Message).where(Message.id == msg_id))).scalars().first()
    outbox_db = (await db.execute(select(OutboxEvent).where(OutboxEvent.aggregate_id == str(msg_id)))).scalars().first()
    assert msg_db is not None
    assert outbox_db is not None
    assert outbox_db.published_at is None
    
    # Run publisher process
    processed = await process_outbox_events()
    assert processed == 1
    
    # Verify event was published to Redis and status updated in DB
    assert len(mock_r.event_queue) == 1
    await db.refresh(db_outbox)
    assert db_outbox.published_at is not None



@pytest.mark.asyncio
async def test_crash_test_2_duplicate_pub_safety(db, mock_redis_injection):
    """
    Crash Test 2:
    1. Publish event to Redis.
    2. Simulate publisher crash BEFORE committing published_at.
    3. Event gets published again on retry/restart.
    """
    mock_r = mock_redis_injection
    msg_id = uuid.uuid4()
    
    event_payload = {
        "event_type": "message.created",
        "version": 1,
        "message_id": str(msg_id)
    }
    db_outbox = OutboxEvent(
        id=uuid.uuid4(),
        event_type="message.created",
        event_version=1,
        aggregate_id=str(msg_id),
        payload=json.dumps(event_payload)
    )
    db.add(db_outbox)
    await db.commit()
    
    # Simulate first publish (adds to Redis event queue, but we don't mark published in DB)
    await mock_r.publish("latext:events", db_outbox.payload)
    assert len(mock_r.event_queue) == 1
    
    # Run publisher (will claim and publish again, creating duplicate publish)
    processed = await process_outbox_events()
    assert processed == 1
    assert len(mock_r.event_queue) == 2  # Published again
    
    # Verify outbox eventually marked published
    await db.refresh(db_outbox)
    assert db_outbox.published_at is not None


@pytest.mark.asyncio
async def test_crash_test_3_crash_before_commit(db, create_conversation):
    """
    Crash Test 3:
    1. Message transaction starts.
    2. Message inserted.
    3. Process crashes before commit (rollback simulated).
    """
    conv, u1, _ = await create_conversation()
    msg_id = uuid.uuid4()
    
    async with SessionLocal() as local_db:
        # Simulate uncommitted inserts
        db_msg = Message(
            id=msg_id,
            conversation_id=conv.id,
            sender_id=u1.id,
            content="Crash Test 3 Content",
            status="SENT"
        )
        local_db.add(db_msg)
        # Rollback/Close without commit
        await local_db.rollback()
        
    # Verify DB has no records
    msg_db = (await db.execute(select(Message).where(Message.id == msg_id))).scalars().first()
    assert msg_db is None


@pytest.mark.asyncio
async def test_crash_test_4_rollback_safety(db, create_conversation):
    """
    Crash Test 4:
    1. Message & Outbox inserted.
    2. Transaction explicitly rolled back.
    """
    conv, u1, _ = await create_conversation()
    msg_id = uuid.uuid4()
    
    async with SessionLocal() as local_db:
        async with local_db.begin():
            db_msg = Message(
                id=msg_id,
                conversation_id=conv.id,
                sender_id=u1.id,
                content="Rollback Content",
                status="SENT"
            )
            local_db.add(db_msg)
            
            db_outbox = OutboxEvent(
                id=uuid.uuid4(),
                event_type="message.created",
                event_version=1,
                aggregate_id=str(msg_id),
                payload="{}"
            )
            local_db.add(db_outbox)
            
            # Explicit rollback
            await local_db.rollback()
            
    # Verify neither exists
    msg_db = (await db.execute(select(Message).where(Message.id == msg_id))).scalars().first()
    outbox_db = (await db.execute(select(OutboxEvent).where(OutboxEvent.aggregate_id == str(msg_id)))).scalars().first()
    assert msg_db is None
    assert outbox_db is None



@pytest.mark.asyncio
async def test_redis_outage_retries(db, mock_redis_injection):
    """
    Redis Outage Test:
    1. Stop Redis (simulate by failing Redis commands).
    2. Outbox event exists.
    3. Publisher fails.
    4. Database remains uncorrupted, event remains unpublished.
    5. Redis returns, event eventually publishes.
    """
    mock_r = mock_redis_injection
    msg_id = uuid.uuid4()
    
    db_outbox = OutboxEvent(
        id=uuid.uuid4(),
        event_type="message.created",
        event_version=1,
        aggregate_id=str(msg_id),
        payload="{}"
    )
    db.add(db_outbox)
    await db.commit()
    
    # 1. Simulate Redis Outage
    mock_r.fail_ping = True
    
    # Publisher should fail and return 0 processed successfully
    processed = await process_outbox_events()
    assert processed == 0
    
    # Verify event is still unpublished and attempts incremented
    await db.refresh(db_outbox)
    assert db_outbox.published_at is None
    assert db_outbox.attempts == 1
    
    # 2. Simulate Redis Recovery
    mock_r.fail_ping = False
    
    # Simulate passage of backoff time (10s)
    db_outbox.last_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=15)
    db.add(db_outbox)
    await db.commit()
    
    # Run publisher again
    processed = await process_outbox_events()
    assert processed == 1
    
    # Verify successfully published
    await db.refresh(db_outbox)
    assert db_outbox.published_at is not None
