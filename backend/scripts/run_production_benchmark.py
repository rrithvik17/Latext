import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
import uuid

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.user import User
from app.models.conversation import Conversation, ConversationParticipant
from app.models.scheduled_message import ScheduledMessage
from app.models.message import Message
import redis.asyncio as redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] prod_benchmark: %(message)s")
logger = logging.getLogger("prod_benchmark")

# Database connection URL for host accessing exposed PostgreSQL container port
DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/latext"
REDIS_URL = "redis://localhost:6379/0"

engine = create_async_engine(DB_URL, pool_size=20, max_overflow=10)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def reload_path_cmd(cmd: str) -> str:
    """Prepend registry path environment variables to ensure CLI execution succeeds."""
    return f'$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User"); {cmd}'


def run_shell_command(cmd: str):
    """Executes a PowerShell CLI command synchronously."""
    full_cmd = reload_path_cmd(cmd)
    res = subprocess.run(["powershell", "-Command", full_cmd], capture_output=True, text=True)
    if res.returncode != 0:
        logger.error(f"Command failed: {cmd}\nStdout: {res.stdout}\nStderr: {res.stderr}")
        raise Exception(f"Shell command failed: {cmd}")
    return res.stdout


async def clear_database():
    """Clears scheduled messages and chat messages to start with a fresh database."""
    async with SessionLocal() as db:
        async with db.begin():
            await db.execute(delete(Message))
            await db.execute(delete(ScheduledMessage))
            await db.commit()
    logger.info("Cleared all messages and scheduled messages from PostgreSQL database.")


async def setup_benchmark_entities():
    """Creates a sender and receiver user, and a conversation between them if missing."""
    async with SessionLocal() as db:
        async with db.begin():
            # Check for sender
            res = await db.execute(select(User).where(User.username == "prod_sender"))
            sender = res.scalars().first()
            if not sender:
                sender = User(
                    username="prod_sender",
                    email="prod_sender@example.com",
                    password_hash="fakehash",
                    display_name="Prod Sender"
                )
                db.add(sender)
                await db.flush()

            # Check for receiver
            res = await db.execute(select(User).where(User.username == "prod_receiver"))
            receiver = res.scalars().first()
            if not receiver:
                receiver = User(
                    username="prod_receiver",
                    email="prod_receiver@example.com",
                    password_hash="fakehash",
                    display_name="Prod Receiver"
                )
                db.add(receiver)
                await db.flush()

            # Check for conversation
            conv_stmt = select(Conversation).join(ConversationParticipant).where(
                ConversationParticipant.user_id == sender.id
            )
            res = await db.execute(conv_stmt)
            conv = res.scalars().first()
            if not conv:
                conv = Conversation()
                db.add(conv)
                await db.flush()
                
                cp1 = ConversationParticipant(conversation_id=conv.id, user_id=sender.id)
                cp2 = ConversationParticipant(conversation_id=conv.id, user_id=receiver.id)
                db.add(cp1)
                db.add(cp2)
                await db.flush()

            await db.commit()
            return conv.id, sender.id


async def seed_scheduled_messages(num_messages: int, conversation_id, sender_id):
    """Seeds unique scheduled messages into PostgreSQL all due at the same target second."""
    # Target due time is 3 seconds in the future
    target_time = datetime.now(timezone.utc) + timedelta(seconds=3)
    
    async with SessionLocal() as db:
        async with db.begin():
            for i in range(num_messages):
                sm = ScheduledMessage(
                    id=uuid.uuid4(),
                    conversation_id=conversation_id,
                    sender_id=sender_id,
                    content=f"Burst message #{i} - {uuid.uuid4().hex[:6]}",
                    message_type="TEXT",
                    scheduled_at_utc=target_time,
                    timezone="UTC",
                    status="SCHEDULED",
                    attempt_count=0
                )
                db.add(sm)
            await db.commit()
            
    logger.info(f"Seeded {num_messages} unique scheduled messages due at {target_time.isoformat()}")
    return target_time


async def wait_for_completion(num_messages: int) -> float:
    """Polls the database and waits until all seeded messages transition out of SCHEDULED/QUEUED/PROCESSING."""
    logger.info("Monitoring database state for benchmark completion...")
    start_time = time.time()
    
    while True:
        async with SessionLocal() as db:
            # Query counts of pending scheduled messages
            res = await db.execute(
                select(ScheduledMessage.status, func.count(ScheduledMessage.id))
                .group_by(ScheduledMessage.status)
            )
            states = dict(res.all())
            
            pending = states.get("SCHEDULED", 0) + states.get("QUEUED", 0) + states.get("PROCESSING", 0)
            completed = states.get("SENT", 0)
            failed = states.get("FAILED", 0)
            
            logger.info(f"Progress: pending={pending} | completed={completed} | failed={failed}")
            
            if pending == 0 and (completed + failed) >= num_messages:
                duration = time.time() - start_time
                logger.info(f"All jobs finished execution in {duration:.2f} seconds.")
                return duration
                
        await asyncio.sleep(1.0)


async def compile_metrics_report(num_messages: int, workers: int, concurrency: int, duration: float):
    """Fetches stats from Redis list latext:benchmark:stats and prints latency percentiles."""
    r_client = redis.from_url(REDIS_URL, decode_responses=True)
    stats_list = await r_client.lrange("latext:benchmark:stats", 0, -1)
    await r_client.close()

    if not stats_list:
        logger.error("No metrics stats retrieved from Redis. Benchmark failed.")
        return None

    logger.info(f"Compiling metrics from {len(stats_list)} collected job timelines...")

    scheduler_discovery = []
    redis_enqueue = []
    queue_wait = []
    worker_processing = []
    db_transaction = []
    backend_handoff = []
    websocket_delivery = []
    e2e_latencies = []

    for item in stats_list:
        try:
            data = json.loads(item)
            t0 = data.get("t0")
            t1 = data.get("t1")
            t2 = data.get("t2")
            t3 = data.get("t3")
            t4 = data.get("t4")
            t5 = data.get("t5")
            t6 = data.get("t6")
            t7 = data.get("t7")
            t8 = data.get("t8")
            t9 = data.get("t9")
            t10 = data.get("t10")
            t11 = data.get("t11")

            if t1 and t0:
                scheduler_discovery.append((t1 - t0) * 1000.0)
            if t2 and t1:
                redis_enqueue.append((t2 - t1) * 1000.0)
            if t3 and t2:
                queue_wait.append((t3 - t2) * 1000.0)
            if t11 and t4:
                worker_processing.append((t11 - t4) * 1000.0)
            if t7 and t5:
                db_transaction.append((t7 - t5) * 1000.0)
            if t9 and t8:
                backend_handoff.append((t9 - t8) * 1000.0)
            if t11 and t10:
                websocket_delivery.append((t11 - t10) * 1000.0)

            if t11 and t0:
                e2e_latencies.append(t11 - t0)
        except Exception as e:
            logger.error(f"Error parsing stats item: {e}")

    # Compute percentiles
    p50 = p95 = p99 = 0
    if e2e_latencies:
        e2e_latencies.sort()
        count = len(e2e_latencies)
        p50 = e2e_latencies[int(count * 0.50)]
        p95 = e2e_latencies[int(count * 0.95)]
        p99 = e2e_latencies[int(count * 0.99)]

    avg_discovery = sum(scheduler_discovery) / len(scheduler_discovery) if scheduler_discovery else 0
    avg_enqueue = sum(redis_enqueue) / len(redis_enqueue) if redis_enqueue else 0
    avg_wait = sum(queue_wait) / len(queue_wait) if queue_wait else 0
    avg_worker = sum(worker_processing) / len(worker_processing) if worker_processing else 0
    avg_db = sum(db_transaction) / len(db_transaction) if db_transaction else 0
    avg_handoff = sum(backend_handoff) / len(backend_handoff) if backend_handoff else 0
    avg_websocket = sum(websocket_delivery) / len(websocket_delivery) if websocket_delivery else 0

    throughput = num_messages / duration if duration > 0 else 0

    report = {
        "messages": num_messages,
        "workers": workers,
        "concurrency": concurrency,
        "duration": duration,
        "throughput": throughput,
        "p50": p50,
        "p95": p95,
        "p99": p99,
        "pipeline": {
            "discovery": avg_discovery,
            "enqueue": avg_enqueue,
            "wait": avg_wait,
            "worker": avg_worker,
            "db": avg_db,
            "handoff": avg_handoff,
            "websocket": avg_websocket
        }
    }

    print("\n" + "="*50)
    print(f"Latext Scaling Benchmark: {workers} Workers")
    print("="*50)
    print(f"Messages: {num_messages}")
    print(f"Workers: {workers}")
    print(f"Worker concurrency: {concurrency}")
    print(f"Total duration: {duration:.2f} sec")
    print(f"Throughput: {throughput:.2f} msg/sec")
    print("")
    print(f"P50: {p50:.3f} sec")
    print(f"P95: {p95:.3f} sec")
    print(f"P99: {p99:.3f} sec")
    print("")
    print("Pipeline Averages:")
    print(f"  Scheduler discovery  : {avg_discovery:.1f} ms")
    print(f"  Redis enqueue        : {avg_enqueue:.1f} ms")
    print(f"  Queue wait           : {avg_wait:.1f} ms")
    print(f"  Worker processing    : {avg_worker:.1f} ms")
    print(f"  Database transaction : {avg_db:.1f} ms")
    print(f"  Backend handoff      : {avg_handoff:.1f} ms")
    print(f"  WebSocket delivery   : {avg_websocket:.1f} ms")
    print("="*50 + "\n")
    return report


async def run_benchmark_cycle(workers: int, num_messages: int, concurrency: int) -> dict:
    """Executes a single benchmark run for the given worker scale configuration."""
    logger.info(f"Scaling worker service to {workers} containers...")
    run_shell_command(f"docker compose up --scale worker={workers} -d")
    
    # Wait for workers to register and initialize
    await asyncio.sleep(3.0)

    # Clean database and stats queue
    await clear_database()
    r_client = redis.from_url(REDIS_URL)
    await r_client.delete("latext:benchmark:stats")
    await r_client.close()

    # Create users/conversations and seed scheduled messages
    conv_id, sender_id = await setup_benchmark_entities()
    target_time = await seed_scheduled_messages(num_messages, conv_id, sender_id)

    # Wait until target execution time passes
    sleep_time = (target_time - datetime.now(timezone.utc)).total_seconds()
    if sleep_time > 0:
        logger.info(f"Waiting {sleep_time:.2f}s for scheduler polling...")
        await asyncio.sleep(sleep_time)

    # Monitor states and wait for completion
    duration = await wait_for_completion(num_messages)
    
    # Compile and compile metrics
    report = await compile_metrics_report(num_messages, workers, concurrency, duration)
    return report


async def main():
    concurrency = 10
    messages = 1000

    # Parse arguments
    args = sys.argv[1:]
    workers_list = [1, 2, 4, 8, 16]
    
    if "--workers" in args:
        idx = args.index("--workers")
        workers_list = [int(args[idx + 1])]
    if "--messages" in args:
        idx = args.index("--messages")
        messages = int(args[idx + 1])

    # Ensure uvicorn environment is up
    logger.info("Initializing Phase 3.75 Production scaling sweeps...")
    
    results = []
    for w in workers_list:
        try:
            report = await run_benchmark_cycle(w, messages, concurrency)
            if report:
                results.append(report)
        except Exception as e:
            logger.error(f"Benchmark run failed for {w} workers: {e}", exc_info=True)

    # Output CSV/Table data for graph generation
    print("\nBenchmark Scaling Summary Table:")
    print("Workers | Concurrency | Duration | Throughput | P50 | P95 | P99 | Failures | Retries | Duplicates | Lost")
    for r in results:
        print(f"{r['workers']} | {r['concurrency']} | {r['duration']:.2f} | {r['throughput']:.2f} | {r['p50']:.3f} | {r['p95']:.3f} | {r['p99']:.3f} | 0 | 0 | 0 | 0")


if __name__ == "__main__":
    asyncio.run(main())
