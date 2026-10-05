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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] param_experiments: %(message)s")
logger = logging.getLogger("param_experiments")

DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/latext"
REDIS_URL = "redis://localhost:6379/0"

engine = create_async_engine(DB_URL, pool_size=80, max_overflow=20)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def reload_path_cmd(cmd: str) -> str:
    return f'$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User"); {cmd}'


def run_shell_command(cmd: str, env: dict = None):
    full_cmd = reload_path_cmd(cmd)
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    res = subprocess.run(["powershell", "-Command", full_cmd], capture_output=True, text=True, env=run_env)
    if res.returncode != 0:
        logger.error(f"Command failed: {cmd}\nStdout: {res.stdout}\nStderr: {res.stderr}")
        raise Exception(f"Shell command failed: {cmd}")
    return res.stdout


async def clear_database():
    async with SessionLocal() as db:
        async with db.begin():
            await db.execute(delete(Message))
            await db.execute(delete(ScheduledMessage))
            await db.commit()


async def setup_benchmark_entities():
    async with SessionLocal() as db:
        async with db.begin():
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
    return target_time


async def wait_for_completion(num_messages: int) -> float:
    start_time = time.time()
    while True:
        async with SessionLocal() as db:
            res = await db.execute(
                select(ScheduledMessage.status, func.count(ScheduledMessage.id))
                .group_by(ScheduledMessage.status)
            )
            states = dict(res.all())
            pending = states.get("SCHEDULED", 0) + states.get("QUEUED", 0) + states.get("PROCESSING", 0)
            completed = states.get("SENT", 0)
            failed = states.get("FAILED", 0)
            
            if pending == 0 and (completed + failed) >= num_messages:
                return time.time() - start_time
        await asyncio.sleep(1.0)


async def compile_metrics_report(num_messages: int, workers: int, concurrency: int, pool_size: int, batch_size: int, duration: float):
    r_client = redis.from_url(REDIS_URL, decode_responses=True)
    stats_list = await r_client.lrange("latext:benchmark:stats", 0, -1)
    await r_client.close()

    if not stats_list:
        return None

    db_transaction = []
    e2e_latencies = []

    for item in stats_list:
        try:
            data = json.loads(item)
            t0 = data.get("t0")
            t5 = data.get("t5")
            t7 = data.get("t7")
            t11 = data.get("t11")

            if t7 and t5:
                db_transaction.append((t7 - t5) * 1000.0)
            if t11 and t0:
                e2e_latencies.append(t11 - t0)
        except Exception:
            pass

    p50 = p95 = p99 = 0
    if e2e_latencies:
        e2e_latencies.sort()
        count = len(e2e_latencies)
        p50 = e2e_latencies[int(count * 0.50)]
        p95 = e2e_latencies[int(count * 0.95)]
        p99 = e2e_latencies[int(count * 0.99)]

    avg_db = sum(db_transaction) / len(db_transaction) if db_transaction else 0
    throughput = num_messages / duration if duration > 0 else 0

    return {
        "workers": workers,
        "concurrency": concurrency,
        "pool_size": pool_size,
        "batch_size": batch_size,
        "duration": duration,
        "throughput": throughput,
        "p50": p50,
        "p95": p95,
        "p99": p99,
        "avg_db_tx_ms": avg_db
    }


async def run_experiment_run(workers: int, concurrency: int, pool_size: int, batch_size: int, num_messages: int = 1000) -> dict:
    env = {
        "WORKER_CONCURRENCY": str(concurrency),
        "DATABASE_POOL_SIZE": str(pool_size),
        "WORKER_BATCH_SIZE": str(batch_size),
    }
    logger.info(f"Recreating worker with CONCURRENCY={concurrency}, POOL_SIZE={pool_size}, BATCH_SIZE={batch_size}...")
    run_shell_command(f"docker compose up --scale worker={workers} -d --force-recreate worker", env=env)
    
    # Wait for workers to start and stabilize
    await asyncio.sleep(4.0)

    # Clean Redis stats & DB
    await clear_database()
    r_client = redis.from_url(REDIS_URL)
    await r_client.delete("latext:benchmark:stats")
    await r_client.close()

    # Seed messages
    conv_id, sender_id = await setup_benchmark_entities()
    target_time = await seed_scheduled_messages(num_messages, conv_id, sender_id)

    sleep_time = (target_time - datetime.now(timezone.utc)).total_seconds()
    if sleep_time > 0:
        await asyncio.sleep(sleep_time)

    # Run and time completion
    duration = await wait_for_completion(num_messages)
    
    report = await compile_metrics_report(num_messages, workers, concurrency, pool_size, batch_size, duration)
    return report


async def main():
    # Sweep configurations
    logger.info("Initializing latext parameter tuning experiments...")

    # 1. Connection Pool Sweep
    # Workers=2, Concurrency=10, Batch=1
    pool_results = []
    for pool in [10, 20, 40, 80]:
        try:
            res = await run_experiment_run(workers=2, concurrency=10, pool_size=pool, batch_size=1)
            if res:
                pool_results.append(res)
                logger.info(f"Pool size {pool} throughput: {res['throughput']:.2f} msg/sec, avg DB: {res['avg_db_tx_ms']:.1f} ms")
        except Exception as e:
            logger.error(f"Pool run failed for {pool}: {e}")

    # 2. Worker Concurrency Sweep
    # Workers=2, Pool=20, Batch=1
    concurrency_results = []
    for conn in [1, 2, 4, 8, 16, 32]:
        try:
            res = await run_experiment_run(workers=2, concurrency=conn, pool_size=20, batch_size=1)
            if res:
                concurrency_results.append(res)
                logger.info(f"Concurrency {conn} throughput: {res['throughput']:.2f} msg/sec, avg DB: {res['avg_db_tx_ms']:.1f} ms")
        except Exception as e:
            logger.error(f"Concurrency run failed for {conn}: {e}")

    # 3. Batch Claiming Sweep
    # Workers=2, Concurrency=10, Pool=20
    batch_results = []
    for batch in [1, 5, 10, 25, 50]:
        try:
            res = await run_experiment_run(workers=2, concurrency=10, pool_size=20, batch_size=batch)
            if res:
                batch_results.append(res)
                logger.info(f"Batch size {batch} throughput: {res['throughput']:.2f} msg/sec, avg DB: {res['avg_db_tx_ms']:.1f} ms")
        except Exception as e:
            logger.error(f"Batch run failed for {batch}: {e}")

    # Print tables
    print("\n\n" + "="*80)
    print("EXPERIMENT SWEEP RESULTS SUMMARY")
    print("="*80)
    
    print("\n1. Connection Pool Sweep (Workers = 2, Concurrency = 10, Batch Size = 1)")
    print("Pool Size | Duration (s) | Throughput (msg/s) | Avg DB Transaction Time (ms)")
    for r in pool_results:
        print(f"{r['pool_size']} | {r['duration']:.2f} | {r['throughput']:.2f} | {r['avg_db_tx_ms']:.1f}")

    print("\n2. Worker Concurrency Sweep (Workers = 2, Connection Pool = 20, Batch Size = 1)")
    print("Concurrency | Duration (s) | Throughput (msg/s) | Avg DB Transaction Time (ms)")
    for r in concurrency_results:
        print(f"{r['concurrency']} | {r['duration']:.2f} | {r['throughput']:.2f} | {r['avg_db_tx_ms']:.1f}")

    print("\n3. Batch Claiming Sweep (Workers = 2, Concurrency = 10, Connection Pool = 20)")
    print("Batch Size | Duration (s) | Throughput (msg/s) | Avg DB Transaction Time (ms)")
    for r in batch_results:
        print(f"{r['batch_size']} | {r['duration']:.2f} | {r['throughput']:.2f} | {r['avg_db_tx_ms']:.1f}")


if __name__ == "__main__":
    asyncio.run(main())
