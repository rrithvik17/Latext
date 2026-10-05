import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

# Set PYTHONPATH to root directory to allow local imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, engine
from app.models.user import User
from app.models.conversation import Conversation, ConversationParticipant
from app.models.scheduled_message import ScheduledMessage
from app.models.message import Message
from app.scheduler.scheduler import process_due_messages
from app.worker.worker import process_callback

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] benchmark: %(message)s")
logger = logging.getLogger("benchmark")

async def run_benchmark():
    logger.info("Initializing 100-message sanity workload check...")
    
    # Ensure tables exist
    from app.models.base import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    # 1. Create a clean user & conversation
    async with SessionLocal() as db:
        async with db.begin():
            # Create user
            user_id = uuid.uuid4()
            user = User(
                id=user_id,
                username=f"bench_{uuid.uuid4().hex[:6]}",
                email=f"bench_{uuid.uuid4().hex[:6]}@example.com",
                display_name="Benchmark User",
                password_hash="password"
            )
            db.add(user)
            
            # Create conversation
            conv_id = uuid.uuid4()
            conv = Conversation(id=conv_id)
            db.add(conv)
            
            # Add participant
            part = ConversationParticipant(conversation_id=conv_id, user_id=user_id)
            db.add(part)

            # Schedule 100 messages due now
            now_utc = datetime.now(timezone.utc) - timedelta(seconds=1)
            sm_ids = []
            for i in range(100):
                sm_id = uuid.uuid4()
                sm_ids.append(sm_id)
                sm = ScheduledMessage(
                    id=sm_id,
                    conversation_id=conv_id,
                    sender_id=user_id,
                    content=f"Workload message {i}",
                    message_type="TEXT",
                    scheduled_at_utc=now_utc,
                    timezone="UTC",
                    status="SCHEDULED"
                )
                db.add(sm)
            
            logger.info(f"Committed user, conversation, and 100 scheduled messages to database.")

    # Mock redis for this in-memory test run
    class DummyRedis:
        def __init__(self):
            self.queue = []
        async def rpush(self, key, val):
            self.queue.append(val)
            return len(self.queue)
        async def ping(self):
            return True
        async def zadd(self, key, mapping):
            return 1
            
    dummy_redis = DummyRedis()
    import app.scheduler.scheduler
    import app.worker.worker
    import app.queue.retry
    import app.queue.producer
    app.scheduler.scheduler.enqueue_job = lambda msg_id, **kwargs: dummy_redis.rpush("latext:scheduled:queue", json.dumps({"scheduled_message_id": msg_id}))
    app.worker.worker.redis_client = dummy_redis
    app.queue.retry.redis_client = dummy_redis
    app.queue.producer.redis_client = dummy_redis

    # 2. Run scheduler polling
    t_start = time.time()
    await process_due_messages()
    t_poll = time.time() - t_start
    logger.info(f"Scheduler poll completed. Enqueued {len(dummy_redis.queue)} messages in {t_poll:.4f}s.")
    
    # 3. Process jobs in worker
    t_worker_start = time.time()
    for job in dummy_redis.queue:
        payload = json.loads(job)
        sm_id = payload["scheduled_message_id"]
        await process_callback(sm_id)
    t_worker = time.time() - t_worker_start
    
    # 4. Verify results
    async with SessionLocal() as db:
        async with db.begin():
            # Check scheduled messages status
            res = await db.execute(select(ScheduledMessage).where(ScheduledMessage.conversation_id == conv_id))
            sms = res.scalars().all()
            sent_count = sum(1 for s in sms if s.status == "SENT")
            failed_count = sum(1 for s in sms if s.status in ("FAILED", "FAILED_PENDING_DLQ"))
            
            # Check created messages
            res_m = await db.execute(select(Message).where(Message.conversation_id == conv_id))
            msgs = res_m.scalars().all()
            msg_count = len(msgs)
            
            # Check duplicates
            msg_ids = [m.scheduled_message_id for m in msgs]
            duplicates = len(msg_ids) - len(set(msg_ids))

    total_time = t_poll + t_worker
    throughput = 100 / total_time if total_time > 0 else 0

    print("=========================================")
    print("      WORKLOAD SANITY CHECK RESULTS      ")
    print("=========================================")
    print(f"Scheduled Messages Sent:   {sent_count}/100")
    print(f"Scheduled Messages Failed: {failed_count}/100")
    print(f"Messages Persisted in DB:  {msg_count}/100")
    print(f"Duplicate Deliveries:      {duplicates}")
    print(f"Total Processing Time:     {total_time:.4f} seconds")
    print(f"Rough Throughput:          {throughput:.2f} messages/sec")
    print("=========================================")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
