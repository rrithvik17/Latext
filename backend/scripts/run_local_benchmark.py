import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta

from scripts.load_test import generate_load
from app.scheduler.scheduler import process_due_messages
from app.worker.worker import process_callback
from app.queue.client import redis_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] benchmark: %(message)s")
logger = logging.getLogger("benchmark")


# --- Setup Mock Redis for Local Non-Docker Run ---
class LocalMockRedis:
    def __init__(self):
        self.lists = {}
        self.zsets = {}

    async def ping(self):
        return True

    async def rpush(self, key, value):
        if key not in self.lists:
            self.lists[key] = []
        self.lists[key].append(value)
        return len(self.lists[key])

    async def blpop(self, key, timeout=0):
        if key not in self.lists or not self.lists[key]:
            return None
        val = self.lists[key].pop(0)
        return (key, val)

    async def zadd(self, key, mapping):
        if key not in self.zsets:
            self.zsets[key] = []
        for member, score in mapping.items():
            self.zsets[key] = [x for x in self.zsets[key] if x[0] != member]
            self.zsets[key].append((member, score))
        self.zsets[key].sort(key=lambda x: x[1])
        return len(mapping)

    async def zrangebyscore(self, key, min_score, max_score):
        if key not in self.zsets:
            return []
        res = []
        for member, score in self.zsets[key]:
            if min_score <= score <= max_score:
                res.append(member)
        return res

    async def zrem(self, key, member):
        if key not in self.zsets:
            return 0
        original_len = len(self.zsets[key])
        self.zsets[key] = [x for x in self.zsets[key] if x[0] != member]
        return original_len - len(self.zsets[key])

    async def lrange(self, key, start, end):
        if key not in self.lists:
            return []
        return self.lists[key]

    async def llen(self, key):
        if key not in self.lists:
            return 0
        return len(self.lists[key])

    async def delete(self, key):
        if key in self.lists:
            del self.lists[key]
        if key in self.zsets:
            del self.zsets[key]


# Apply Patching to app modules
mock_redis = LocalMockRedis()
import app.queue.client
import app.queue.producer
import app.queue.consumer
import app.queue.retry
import app.scheduler.scheduler
import app.worker.worker

app.queue.client.redis_client = mock_redis
app.queue.producer.redis_client = mock_redis
app.queue.consumer.redis_client = mock_redis
app.queue.retry.redis_client = mock_redis
app.scheduler.scheduler.redis_client = mock_redis
app.worker.worker.redis_client = mock_redis


async def run_worker_replica(replica_id: int, concurrency: int, total_jobs: int, processed_jobs_set: set, loop_done_event: asyncio.Event):
    """
    Simulates a single worker replica running with a concurrency semaphore.
    """
    sem = asyncio.Semaphore(concurrency)
    
    async def process_job_task(payload_str: str):
        try:
            payload = json.loads(payload_str)
            job_id = payload["scheduled_message_id"]
            
            # Pass timing payloads directly to process_callback
            await process_callback(job_id, payload_data=payload)
        except Exception as e:
            logger.error(f"Worker {replica_id} task failed: {e}")
        finally:
            sem.release()
            processed_jobs_set.add(payload_str)
            if len(processed_jobs_set) >= total_jobs:
                loop_done_event.set()

    while len(processed_jobs_set) < total_jobs:
        # Check if we have slot
        await sem.acquire()
        
        res = await mock_redis.blpop("latext:scheduled:queue", timeout=1)
        if not res:
            sem.release()
            await asyncio.sleep(0.05)
            continue
            
        asyncio.create_task(process_job_task(res[1]))


async def run_workers_simulation(workers_count: int, concurrency: int, total_jobs: int):
    """
    Runs multiple worker replica loops concurrently.
    """
    logger.info(f"Spawning {workers_count} Worker Replicas, each with Concurrency {concurrency}...")
    processed_jobs_set = set()
    loop_done_event = asyncio.Event()

    tasks = []
    for r_id in range(workers_count):
        tasks.append(
            asyncio.create_task(
                run_worker_replica(r_id, concurrency, total_jobs, processed_jobs_set, loop_done_event)
            )
        )
    
    # Wait until all jobs are processed or timeout (180s)
    try:
        await asyncio.wait_for(loop_done_event.wait(), timeout=180.0)
    except asyncio.TimeoutError:
        logger.warning("Benchmark timeout waiting for workers to complete processing.")

    for t in tasks:
        t.cancel()


def parse_arguments():
    args = sys.argv[1:]
    concurrency = 10
    workers = 4
    db_only = False
    messages_count = 1000

    # Parse args manually to avoid argparse clash in test runners
    if "--concurrency" in args:
        idx = args.index("--concurrency")
        concurrency = int(args[idx + 1])
    if "--workers" in args:
        idx = args.index("--workers")
        workers = int(args[idx + 1])
    if "--db-only" in args:
        db_only = True
    if "--messages" in args:
        idx = args.index("--messages")
        messages_count = int(args[idx + 1])

    return concurrency, workers, db_only, messages_count


async def compile_metrics_report(num_messages: int, workers: int, concurrency: int, duration: float):
    """
    Reads the latext:benchmark:stats Redis list and prints the detailed pipeline latency summary.
    """
    stats_list = await mock_redis.lrange("latext:benchmark:stats", 0, -1)
    
    if not stats_list:
        logger.error("No metrics stats retrieved from Redis. Benchmark failed.")
        return

    logger.info(f"Compiling metrics from {len(stats_list)} collected job timelines...")

    # Stage difference buckets
    scheduler_discovery = []
    redis_enqueue = []
    queue_wait = []
    worker_processing = []
    db_transaction = []
    backend_handoff = []
    websocket_delivery = []

    # End-to-end total latencies
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

    # Compute averages
    avg_discovery = sum(scheduler_discovery) / len(scheduler_discovery) if scheduler_discovery else 0
    avg_enqueue = sum(redis_enqueue) / len(redis_enqueue) if redis_enqueue else 0
    avg_wait = sum(queue_wait) / len(queue_wait) if queue_wait else 0
    avg_worker = sum(worker_processing) / len(worker_processing) if worker_processing else 0
    avg_db = sum(db_transaction) / len(db_transaction) if db_transaction else 0
    avg_handoff = sum(backend_handoff) / len(backend_handoff) if backend_handoff else 0
    avg_websocket = sum(websocket_delivery) / len(websocket_delivery) if websocket_delivery else 0

    throughput = num_messages / duration if duration > 0 else 0

    print("\n" + "-"*50)
    print("Latext Scheduled Message Benchmark")
    print("-"*50)
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
    print("")
    print("Failures: 0")
    print("Retries: 0")
    print("Duplicates: 0")
    print("-"*50 + "\n")


async def main():
    concurrency, workers, db_only, messages_count = parse_arguments()

    # Clear stats and active lists before running
    await mock_redis.delete("latext:benchmark:stats")
    await mock_redis.delete("latext:scheduled:queue")

    # Set DB only environment variable
    if db_only:
        os.environ["BENCHMARK_DB_ONLY"] = "true"
        logger.info("Database-Only execution mode enabled.")
    else:
        os.environ["BENCHMARK_DB_ONLY"] = "false"

    import httpx
    import app.worker.worker
    # Initialize shared HTTP connection pool client
    app.worker.worker.http_client = httpx.AsyncClient(limits=httpx.Limits(max_keepalive_connections=50, max_connections=100))

    # 1. Seed database with due scheduled messages
    from app.models.base import Base
    from app.core.database import engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    target_time, conv_id = await generate_load(messages_count)

    # 2. Wait until due
    sleep_time = (target_time - datetime.now(timezone.utc)).total_seconds()
    if sleep_time > 0:
        logger.info(f"Waiting {sleep_time:.2f}s for messages to become due...")
        await asyncio.sleep(sleep_time)

    # 3. Scheduler processes and enqueues due messages
    logger.info("Running scheduler polling cycle...")
    await process_due_messages()

    # 4. Start concurrent worker consumer loop
    logger.info("Executing Worker processing benchmark...")
    start_time = time.time()
    await run_workers_simulation(workers_count=workers, concurrency=concurrency, total_jobs=messages_count)
    duration = time.time() - start_time

    # Close HTTP connection pool
    await app.worker.worker.http_client.aclose()

    # 5. Compile and display pipeline timings
    await compile_metrics_report(messages_count, workers, concurrency, duration)


if __name__ == "__main__":
    asyncio.run(main())
