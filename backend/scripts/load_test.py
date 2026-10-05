import asyncio
import logging
import sys
import uuid
import time
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func

from app.core.database import SessionLocal
from app.models.user import User
from app.models.conversation import Conversation, ConversationParticipant
from app.models.scheduled_message import ScheduledMessage
from app.models.message import Message

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] load_test: %(message)s")
logger = logging.getLogger("load_test")


async def setup_test_entities(db) -> tuple[uuid.UUID, uuid.UUID]:
    """
    Sets up a load testing conversation between two seed users.
    Returns (conversation_id, sender_id).
    """
    # 1. Ensure user A and B exist
    u1_stmt = select(User).where(User.username == "load_sender")
    u1_res = await db.execute(u1_stmt)
    u1 = u1_res.scalars().first()
    
    if not u1:
        u1 = User(
            username="load_sender",
            email="load_sender@example.com",
            display_name="Load Sender",
            password_hash="$2b$12$EixZaYVK1fsAH1vlDB.xOD.c8a2y/522.zL5x5j46kZ3.b9vW55cO" # password
        )
        db.add(u1)
        await db.flush()

    u2_stmt = select(User).where(User.username == "load_recipient")
    u2_res = await db.execute(u2_stmt)
    u2 = u2_res.scalars().first()

    if not u2:
        u2 = User(
            username="load_recipient",
            email="load_recipient@example.com",
            display_name="Load Recipient",
            password_hash="$2b$12$EixZaYVK1fsAH1vlDB.xOD.c8a2y/522.zL5x5j46kZ3.b9vW55cO" # password
        )
        db.add(u2)
        await db.flush()

    # 2. Check or create conversation
    # Look for existing participant records between u1 and u2
    conv_stmt = select(ConversationParticipant.conversation_id).where(
        ConversationParticipant.user_id == u1.id
    )
    conv_res = await db.execute(conv_stmt)
    u1_conv_ids = conv_res.scalars().all()

    conv_id = None
    if u1_conv_ids:
        shared_stmt = select(ConversationParticipant.conversation_id).where(
            ConversationParticipant.conversation_id.in_(u1_conv_ids),
            ConversationParticipant.user_id == u2.id
        )
        shared_res = await db.execute(shared_stmt)
        conv_id = shared_res.scalars().first()

    if not conv_id:
        new_conv = Conversation()
        db.add(new_conv)
        await db.flush()
        
        p1 = ConversationParticipant(conversation_id=new_conv.id, user_id=u1.id)
        p2 = ConversationParticipant(conversation_id=new_conv.id, user_id=u2.id)
        db.add_all([p1, p2])
        await db.flush()
        conv_id = new_conv.id

    return conv_id, u1.id


async def generate_load(num_messages: int = 1000):
    """
    Seeds database with num_messages ScheduledMessages scheduled for the near future.
    """
    logger.info(f"Initializing load benchmark setup for {num_messages} messages...")
    async with SessionLocal() as db:
        async with db.begin():
            conv_id, sender_id = await setup_test_entities(db)
            
            # Target 15 seconds in the future
            target_time = datetime.now(timezone.utc) + timedelta(seconds=15)
            
            logger.info(f"Generating {num_messages} ScheduledMessages targeting {target_time} UTC...")
            messages = []
            for i in range(num_messages):
                messages.append(
                    ScheduledMessage(
                        id=uuid.uuid4(),
                        conversation_id=conv_id,
                        sender_id=sender_id,
                        content=f"Load test payload message index #{i} - reliable scheduled check.",
                        message_type="TEXT",
                        scheduled_at_utc=target_time,
                        timezone="UTC",
                        status="SCHEDULED"
                    )
                )
            db.add_all(messages)
            
    logger.info("Successfully committed load messages database seed.")
    return target_time, conv_id


async def monitor_load(target_time: datetime, num_messages: int):
    """
    Monitors database state machine transitions and computes performance stats.
    """
    logger.info("Starting real-time load execution monitor loop...")
    
    # Wait until target time is reached
    sleep_till_due = (target_time - datetime.now(timezone.utc)).total_seconds()
    if sleep_till_due > 0:
        logger.info(f"Sleeping for {sleep_till_due:.2f}s until target delivery minute is reached...")
        await asyncio.sleep(sleep_till_due)

    start_monitor_time = time.time()
    max_wait = 180  # 3 minutes maximum timeout
    elapsed = 0

    while elapsed < max_wait:
        async with SessionLocal() as db:
            # Query status counts
            count_stmt = select(ScheduledMessage.status, func.count(ScheduledMessage.id)).group_by(ScheduledMessage.status)
            res = await db.execute(count_stmt)
            counts = dict(res.all())

        scheduled = counts.get("SCHEDULED", 0)
        queued = counts.get("QUEUED", 0)
        processing = counts.get("PROCESSING", 0)
        sent = counts.get("SENT", 0)
        failed = counts.get("FAILED", 0)
        cancelled = counts.get("CANCELLED", 0)

        total_pending = scheduled + queued + processing
        logger.info(
            f"Progress: pending={total_pending} [Sched={scheduled}, Queued={queued}, Proc={processing}] | "
            f"done={sent} | failed={failed}"
        )

        if total_pending == 0:
            logger.info("Execution complete! No pending scheduled messages remaining.")
            break

        await asyncio.sleep(3)
        elapsed = time.time() - start_monitor_time

    # Retrieve latency calculations
    logger.info("Computing delivery latency metrics...")
    async with SessionLocal() as db:
        stmt = (
            select(ScheduledMessage.scheduled_at_utc, ScheduledMessage.sent_at)
            .where(ScheduledMessage.status == "SENT")
            .order_by(ScheduledMessage.sent_at.asc())
        )
        res = await db.execute(stmt)
        records = res.all()

    if not records:
        logger.error("No sent messages discovered. Benchmark failed.")
        return

    latencies = []
    first_sent = None
    last_sent = None

    for sched_utc, sent_utc in records:
        if sent_utc:
            lat = (sent_utc - sched_utc).total_seconds()
            latencies.append(lat)
            if first_sent is None or sent_utc < first_sent:
                first_sent = sent_utc
            if last_sent is None or sent_utc > last_sent:
                last_sent = sent_utc

    latencies.sort()
    count = len(latencies)
    
    # Latency Percentiles
    p50 = latencies[int(count * 0.50)]
    p95 = latencies[int(count * 0.95)]
    p99 = latencies[int(count * 0.99)]
    avg_lat = sum(latencies) / count
    min_lat = latencies[0]
    max_lat = latencies[-1]

    # Throughput calculation
    duration = (last_sent - first_sent).total_seconds() if (last_sent and first_sent) else 0.1
    if duration == 0:
        duration = 0.1
    throughput = count / duration

    print("\n" + "="*50)
    print("           LATEXT PHASE 3 BENCHMARK REPORT      ")
    print("="*50)
    print(f"Total Seeding Count  : {num_messages} messages")
    print(f"Total Sent Count     : {count} messages")
    print(f"Total Failed Count   : {failed} messages")
    print(f"Elapsed Time         : {duration:.2f} seconds")
    print(f"Throughput           : {throughput:.2f} messages/sec")
    print("-"*50)
    print("Latency Metrics (scheduled_at -> delivery start):")
    print(f"  Min Latency        : {min_lat:.3f} seconds")
    print(f"  Avg Latency        : {avg_lat:.3f} seconds")
    print(f"  p50 Latency (Med)  : {p50:.3f} seconds")
    print(f"  p95 Latency        : {p95:.3f} seconds")
    print(f"  p99 Latency        : {p99:.3f} seconds")
    print(f"  Max Latency        : {max_lat:.3f} seconds")
    print("="*50 + "\n")


async def main():
    num_messages = 1000
    if len(sys.argv) > 1:
        try:
            num_messages = int(sys.argv[1])
        except ValueError:
            pass

    target_time, conv_id = await generate_load(num_messages)
    await monitor_load(target_time, num_messages)


if __name__ == "__main__":
    asyncio.run(main())
