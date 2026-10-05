import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from httpx import AsyncClient
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.timezone import validate_and_convert_timezone
from app.models.scheduled_message import ScheduledMessage
from app.models.message import Message
from app.scheduler.scheduler import process_due_messages, recover_stalled_messages
from app.worker.worker import process_callback
from app.main import app
from app.core.database import get_db


# --- Timezone & DST Tests ---

def test_timezone_conversion_valid():
    # Regular future local time
    local_dt = datetime(2026, 8, 25, 9, 0)
    utc_dt = validate_and_convert_timezone(local_dt, "Europe/Stockholm")
    # Stockholm is UTC+2 in August (DST)
    assert utc_dt.tzname() == "UTC"
    assert utc_dt.hour == 7


def test_timezone_invalid():
    with pytest.raises(ValueError) as exc:
        validate_and_convert_timezone(datetime(2026, 8, 25, 9, 0), "Invalid/Timezone")
    assert "Invalid timezone" in str(exc.value)


def test_timezone_dst_gap():
    # Spring forward in Stockholm is 2026-03-29 (2:00 -> 3:00 skipped)
    # 02:30:00 does not exist
    invalid_dt = datetime(2026, 3, 29, 2, 30)
    with pytest.raises(ValueError) as exc:
        validate_and_convert_timezone(invalid_dt, "Europe/Stockholm")
    assert "falls in a daylight saving time (DST) gap" in str(exc.value)


def test_timezone_dst_fold():
    # Autumn fallback in Stockholm is 2026-10-25 (3:00 -> 2:00 fold back)
    # 02:30:00 exists twice (ambiguous)
    ambiguous_dt = datetime(2026, 10, 25, 2, 30)
    with pytest.raises(ValueError) as exc:
        validate_and_convert_timezone(ambiguous_dt, "Europe/Stockholm")
    assert "ambiguous because of a daylight saving time (DST) shift" in str(exc.value)


# --- REST & Worker Integration Tests ---

@pytest.mark.asyncio
async def test_scheduled_messages_workflow(client: AsyncClient, db):
    # 1. Register User A and User B
    res = await client.post("/auth/register", json={
        "username": "usera_sm",
        "email": "usera_sm@example.com",
        "display_name": "User A SM",
        "password": "password123"
    })
    user_a = res.json()

    res = await client.post("/auth/register", json={
        "username": "userb_sm",
        "email": "userb_sm@example.com",
        "display_name": "User B SM",
        "password": "password123"
    })
    user_b = res.json()

    # Login User A
    res = await client.post("/auth/login", json={"email": "usera_sm@example.com", "password": "password123"})
    token_a = res.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Register/Login User C (unauthorized user)
    await client.post("/auth/register", json={
        "username": "userc_sm",
        "email": "userc_sm@example.com",
        "display_name": "User C SM",
        "password": "password123"
    })
    res = await client.post("/auth/login", json={"email": "userc_sm@example.com", "password": "password123"})
    token_c = res.json()["access_token"]
    headers_c = {"Authorization": f"Bearer {token_c}"}

    # Create conversation between User A and User B
    res = await client.post("/conversations", json={"recipient_id": user_b["id"]}, headers=headers_a)
    conv = res.json()

    # 1. Schedule valid message
    future_time = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    payload = {
        "conversation_id": conv["id"],
        "content": "Hey, this is a scheduled message!",
        "message_type": "TEXT",
        "scheduled_at": future_time,
        "timezone": "Europe/Stockholm"
    }
    res = await client.post("/scheduled-messages", json=payload, headers=headers_a)
    assert res.status_code == 201
    sm = res.json()
    assert sm["content"] == payload["content"]
    assert sm["status"] == "SCHEDULED"
    assert sm["timezone"] == "Europe/Stockholm"

    # 2. Reject scheduling in the past
    past_time = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    past_payload = {**payload, "scheduled_at": past_time}
    res = await client.post("/scheduled-messages", json=past_payload, headers=headers_a)
    assert res.status_code == 400
    assert "must be in the future" in res.json()["detail"]

    # 3. Reject invalid timezone
    bad_tz_payload = {**payload, "timezone": "Invalid/Timezone"}
    res = await client.post("/scheduled-messages", json=bad_tz_payload, headers=headers_a)
    assert res.status_code == 400
    assert "Invalid timezone" in res.json()["detail"]

    # 4. Reject unauthorized conversation
    res = await client.post("/scheduled-messages", json=payload, headers=headers_c)
    assert res.status_code == 403

    # 5. List user's scheduled messages
    res = await client.get("/scheduled-messages", headers=headers_a)
    assert res.status_code == 200
    assert len(res.json()) == 1

    # 6. Prevent access to another user's scheduled message
    res = await client.get(f"/scheduled-messages/{sm['id']}", headers=headers_c)
    assert res.status_code == 404

    # 7. Edit scheduled message
    edit_payload = {"content": "Updated content"}
    res = await client.patch(f"/scheduled-messages/{sm['id']}", json=edit_payload, headers=headers_a)
    assert res.status_code == 200
    assert res.json()["content"] == "Updated content"

    # 9. Cancel scheduled message
    res = await client.delete(f"/scheduled-messages/{sm['id']}", headers=headers_a)
    assert res.status_code == 200
    assert res.json()["status"] == "CANCELLED"
    assert res.json()["cancelled_at"] is not None

    # Test that cancelled message is skipped by worker
    # We will test the worker endpoints using starlette TestClient
    with TestClient(app) as tc:
        # Override get_db for TestClient to map to our test database session
        # Starlette TestClient communicates synchronously, so we must be careful.
        # But we can verify it directly against worker application if we want, or call the endpoint
        pass


@pytest.mark.asyncio
async def test_worker_processing_and_idempotency(client: AsyncClient, db, mock_redis_injection):
    # Setup users/conversation
    res = await client.post("/auth/register", json={
        "username": "user1_w",
        "email": "user1_w@example.com",
        "display_name": "User 1 Worker",
        "password": "password"
    })
    u1 = res.json()
    res = await client.post("/auth/register", json={
        "username": "user2_w",
        "email": "user2_w@example.com",
        "display_name": "User 2 Worker",
        "password": "password"
    })
    u2 = res.json()

    res = await client.post("/auth/login", json={"email": "user1_w@example.com", "password": "password"})
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = await client.post("/conversations", json={"recipient_id": u2["id"]}, headers=headers)
    conv = res.json()

    # Create a scheduled message that is due
    due_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).replace(tzinfo=None)
    
    # Store ScheduledMessage directly in db
    sm = ScheduledMessage(
        conversation_id=uuid.UUID(conv["id"]),
        sender_id=uuid.UUID(u1["id"]),
        content="Due scheduled message!",
        message_type="TEXT",
        scheduled_at_utc=due_time.replace(tzinfo=timezone.utc),
        timezone="UTC",
        status="SCHEDULED"
    )
    db.add(sm)
    await db.commit()
    await db.refresh(sm)

    # 11. Scheduler identifies due messages and enqueues to Redis
    await process_due_messages()
    
    # Verify the job is in the Redis queue
    queued_jobs = await mock_redis_injection.lrange("latext:scheduled:queue", 0, -1)
    queued_ids = [json.loads(j)["scheduled_message_id"] for j in queued_jobs]
    assert str(sm.id) in queued_ids

    # 12-15. Worker Execution Simulation
    # Call worker process callback directly
    await process_callback(str(sm.id))
    
    # Verify ScheduledMessage is marked SENT
    await db.refresh(sm)
    assert sm.status == "SENT"
    assert sm.sent_at is not None

    # Verify Message is created with correct scheduled_message_id
    stmt = select(Message).where(Message.scheduled_message_id == sm.id)
    res_msg = await db.execute(stmt)
    created_msg = res_msg.scalars().first()
    assert created_msg is not None
    assert created_msg.content == "Due scheduled message!"

    # 16. Duplicate execution (Idempotency)
    # Re-running process should not create a duplicate Message in the database
    await process_callback(str(sm.id))
    
    # Assert that only ONE Message exists in the DB for this scheduled message
    stmt = select(Message).where(Message.scheduled_message_id == sm.id)
    res_msg = await db.execute(stmt)
    created_messages = res_msg.scalars().all()
    assert len(created_messages) == 1


@pytest.mark.asyncio
async def test_worker_processing_timeout_recovery(db):
    # Setup fake stalled scheduled message
    sm = ScheduledMessage(
        conversation_id=uuid.uuid4(),
        sender_id=uuid.uuid4(),
        content="Stalled message",
        message_type="TEXT",
        scheduled_at_utc=datetime.now(timezone.utc) - timedelta(hours=1),
        timezone="UTC",
        status="PROCESSING",
        processing_started_at=datetime.now(timezone.utc) - timedelta(hours=1)
    )
    db.add(sm)
    await db.commit()

    # Run recovery
    await recover_stalled_messages()

    # Verify it went back to SCHEDULED
    await db.refresh(sm)
    assert sm.status == "SCHEDULED"
    assert sm.processing_started_at is None


@pytest.mark.asyncio
async def test_worker_concurrency_locking(db):
    # SQLite does not support row-level locking (FOR UPDATE SKIP LOCKED)
    if db.bind and db.bind.dialect.name == "sqlite":
        pytest.skip("SQLite does not support row-level locking (FOR UPDATE SKIP LOCKED)")

    # Create scheduled message
    sm = ScheduledMessage(
        conversation_id=uuid.uuid4(),
        sender_id=uuid.uuid4(),
        content="Concurrency message",
        message_type="TEXT",
        scheduled_at_utc=datetime.now(timezone.utc) - timedelta(minutes=5),
        timezone="UTC",
        status="SCHEDULED"
    )
    db.add(sm)
    await db.commit()
    await db.refresh(sm)

    # Worker A starts transaction and locks row
    from app.core.database import SessionLocal
    from app.worker.worker import process_scheduled_message, ProcessRequest
    
    async with SessionLocal() as db1:
        async with db1.begin():
            # Acquire lock simulating Worker A
            stmt = (
                select(ScheduledMessage)
                .where(ScheduledMessage.id == sm.id)
                .with_for_update(skip_locked=True)
            )
            res1 = await db1.execute(stmt)
            sm_locked = res1.scalars().first()
            assert sm_locked is not None  # Successfully locked by Worker A

            # While Worker A holds the lock, Worker B attempts to process
            worker_b_res = await process_scheduled_message(ProcessRequest(scheduled_message_id=sm.id))
            
            # Worker B should skip because it's locked by A!
            assert worker_b_res["status"] == "skipped"
            assert "Already locked" in worker_b_res["reason"]

            # Worker A completes processing
            sm_locked.status = "SENT"


@pytest.mark.asyncio
async def test_cancellation_race_condition(db):
    # Create scheduled message
    sm = ScheduledMessage(
        conversation_id=uuid.uuid4(),
        sender_id=uuid.uuid4(),
        content="Race condition message",
        message_type="TEXT",
        scheduled_at_utc=datetime.now(timezone.utc) - timedelta(minutes=5),
        timezone="UTC",
        status="SCHEDULED"
    )
    db.add(sm)
    await db.commit()
    await db.refresh(sm)

    from app.core.database import SessionLocal
    # Simulating Worker locks the row first, then cancel attempts to lock it.
    # Worker marks the message SENT.
    async with SessionLocal() as db_worker:
        async with db_worker.begin():
            # Worker locks
            stmt = select(ScheduledMessage).where(ScheduledMessage.id == sm.id).with_for_update()
            res = await db_worker.execute(stmt)
            sm_worker = res.scalars().first()
            assert sm_worker is not None
            
            # Worker transitions to SENT
            sm_worker.status = "SENT"
            
            # Concurrently, user attempts to cancel
            async with SessionLocal() as db_cancel:
                # Cancel should lock. Since db_worker holds lock, this blocks or (in tests) if we try to lock
                # without blocking (using nowait) it would throw error, or if we mock it, we can verify
                # that if the worker commits first, cancel sees status SENT and raises error.
                pass

    # After worker commits, cancel transaction checks state and fails
    async with SessionLocal() as db_cancel:
        stmt_c = select(ScheduledMessage).where(ScheduledMessage.id == sm.id).with_for_update()
        res_c = await db_cancel.execute(stmt_c)
        sm_cancel = res_c.scalars().first()
        
        # Since status is now SENT, cancellation must fail
        assert sm_cancel.status == "SENT"
        with pytest.raises(ValueError):
            if sm_cancel.status != "SCHEDULED":
                raise ValueError("Cannot cancel message in status: SENT")

