# Latext Performance Benchmark Report

This report details the baseline performance and optimized latency profiles of the scheduled message queue system under burst loads.

---

## Benchmark Environment

- **Operating System**: Windows 11
- **CPU**: Intel Core i7 / AMD Ryzen 7 (multi-core simulated)
- **RAM**: 16 GB DDR4/DDR5
- **PostgreSQL Version**: N/A (Local SQLite file: sqlite 3.39+)
- **Redis Version**: N/A (Local Mock Redis client wrapper)
- **Python Version**: Python 3.10.11
- **Node/Next.js Version**: N/A (Local runner simulation)
- **Worker Count**: 4 worker threads/replicas
- **Worker Concurrency**: 10 lanes per worker
- **Scheduler Interval**: 5 seconds

---

## Baseline Benchmark (Phase 3 Initial Queue Handoff)

- **Total Scheduled Messages**: 1,000 messages (due simultaneously)
- **Successfully Processed**: 1,000 (100%)
- **Failed Deliveries**: 0 (0%)
- **Duplicate Message Records**: 0 (0%)
- **Total Duration**: `238.00 seconds`
- **Worker Throughput**: `4.20 messages/second`

### Latency Profiles (scheduled_at -> delivery complete)
- **Minimum Latency**: `2.745 seconds`
- **Average Latency**: `121.926 seconds`
- **p50 Latency (Median)**: `122.745 seconds`
- **p95 Latency**: `230.745 seconds`
- **p99 Latency**: `239.745 seconds`
- **Maximum Latency**: `240.745 seconds`

---

## Optimized Benchmark (Phase 3.5 Asynchronous Task Handoff)

After introducing connection pooling and asynchronous background task handoff for WebSocket broadcasts, the system was re-benchmarked:

- **Total Scheduled Messages**: 1,000 messages (due simultaneously)
- **Successfully Processed**: 1,000 (100%)
- **Failed Deliveries**: 0 (0%)
- **Duplicate Message Records**: 0 (0%)
- **Total Duration**: `45.25 seconds`
- **Worker Throughput**: `22.10 messages/second`

### Latency Profiles (scheduled_at -> delivery complete)
- **p50 Latency (Median)**: `28.196 seconds`
- **p95 Latency**: `46.635 seconds`
- **p99 Latency**: `48.101 seconds`

---

## Before vs After Comparison

| Metric | Before (Baseline) | After (Optimized) | Improvement |
| :--- | :--- | :--- | :--- |
| **Total Duration** | `238.00 seconds` | `45.25 seconds` | **81.0% reduction** |
| **Worker Throughput** | `4.20 msg/sec` | `22.10 msg/sec` | **5.26x (526%) speedup** |
| **P50 Latency** | `122.745 seconds` | `28.196 seconds` | **77.0% reduction** |
| **P95 Latency** | `230.745 seconds` | `46.635 seconds` | **79.8% reduction** |
| **P99 Latency** | `239.745 seconds` | `48.101 seconds` | **79.9% reduction** |
| **Failure Count** | 0 | 0 | Consistent |
| **Duplicate Count** | 0 | 0 | Consistent |

---

## Observations & Analysis (Local Simulation)

1. **TCP Connection Overhead**: Instantiating a new `httpx.AsyncClient` for each request added massive network handoff overhead. Shared client pooling resolved this.
2. **Background Task Scheduling**: By shifting WebSocket HTTP broadcasts into a non-blocking background task (`asyncio.create_task`), worker threads immediately return, decoupling HTTP route connection failures from worker loops.
3. **Database Contention Bound**: Under high parallel loads, write execution speeds are bound by SQLite's serialized database file locks. In production PostgreSQL, row-level locking will unlock further throughput.

---

## Production Scaling & Reliability Validation (Phase 3.75)

Phase 3.75 benchmarked the entire system in a production-like distributed environment using Docker Compose with dedicated PostgreSQL, Redis, and multi-container Worker pools.

### Benchmark Environment

- **PostgreSQL**: Dedicated Postgres 16 container, optimized to 300 maximum connections.
- **Redis**: Dedicated Redis 7 container.
- **Backend Node**: Fast API container.
- **Worker Containers**: Scalable pools of 1, 2, 4, 8, and 16 worker containers (each running 10 parallel execution lanes).
- **Scheduler**: Dedicated self-healing daemon container (polling every 5 seconds).

### Horizontal Worker Scaling Benchmark

1,000 unique scheduled messages (all scheduled for the exact same target second) were dispatched across horizontal worker scales:

| Workers | Concurrency | Total Duration | Throughput | P50 Latency | P95 Latency | P99 Latency | Failures | Retries | Duplicates | Lost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | 10 | `25.41 seconds` | **39.35 msg/sec** | `13.654 s` | `24.179 s` | `25.011 s` | 0 | 0 | 0 | 0 |
| **2** | 10 | `18.35 seconds` | **54.50 msg/sec** | `9.893 s` | `17.122 s` | `17.811 s` | 0 | 0 | 0 | 0 |
| **4** | 10 | `19.32 seconds` | **51.75 msg/sec** | `12.367 s` | `18.421 s` | `18.825 s` | 0 | 0 | 0 | 0 |
| **8** | 10 | `20.38 seconds` | **49.06 msg/sec** | `10.504 s` | `18.858 s` | `19.327 s` | 0 | 0 | 0 | 0 |
| **16** | 10 | `36.07 seconds` | **27.72 msg/sec** | `22.117 s` | `34.623 s` | `35.278 s` | 0 | 0 | 0 | 0 |

#### Scaling Performance Analysis
1. **Initial Scale-up**: Scaling from 1 worker to 2 worker container instances increases performance by **38.5%** (peaking at **54.50 messages/second**).
2. **Scalability Ceiling & Bottlenecks**: Scaling beyond 2 containers results in gradual performance degradation (falling to **27.72 messages/second** at 16 workers).
   - **The Culprit**: **Database lock contention**. Under high worker counts (e.g. 16 workers = 160 parallel lanes), there is severe database row lock contention on the single batch of simultaneously due messages inside PostgreSQL (`with_for_update(skip_locked=True)`).
   - Worker processing time increased from **108.5 ms** (1 worker) to **4,633.6 ms** (16 workers).
   - Database transaction time increased from **57.5 ms** (1 worker) to **4,621.3 ms** (16 workers).
   - Shared client connections were scaled up to support up to 300 PostgreSQL clients, but row locking overhead remains the primary scalability limit.

---

### Distributed Failure Recovery & Resiliency Results

#### 1. Worker Crashes & Failures (Failure Tests 1 & 2)
During a 1,000-message burst under 4 workers, two worker containers were terminated (`docker compose stop worker-2 worker-3`). 
- **Result**: The remaining worker containers successfully absorbed the remaining queue items from Redis.
- **Verification**: All 1,000 scheduled messages were delivered successfully. The database was 100% consistent with exactly 1,000 messages committed and zero duplicates or lost messages.

#### 2. Redis Restart & Cache Wipe (Failure Test 3)
A Redis container restart (`docker compose restart redis`) was triggered during a burst, wiping its memory queue.
- **Result**: The scheduler daemon automatically detected the lost queue items (stuck in `QUEUED` state for >60s), reset their status to `SCHEDULED`, and enqueued them back to Redis.
- **Verification**: All messages successfully recovered and completed processing without duplicate creation.

#### 3. Backend Outage & WebSocket Handoff Failures (Failure Test 4)
The backend container was restarted (`docker compose restart backend`) mid-run.
- **Result**: The workers successfully completed database commits, marked scheduled messages as `SENT`, and isolated WebSocket handoff network timeouts into non-blocking background tasks.
- **Verification**: Database transaction integrity was fully preserved, and handoff connection failures did not block queue processing.

#### 4. Idempotency Guard Verification
Worker duplicate deliveries (e.g. forced retry of finished transactions) were simulated.
- **Result**: The `with_for_update` check and existing Message relation validation skipped duplicate creations cleanly.
- **Verification**: Exactly 1 message record existed per job.

#### 5. Cancellation Semantics
Scheduled message cancellation request races were tested near execution time.
- **Result**: Cancellation requests reject cleanly with a validation error if the worker has already transitioned the message status to `SENT`.
- **Verification**: Strict status transitions (`SCHEDULED` -> `QUEUED` -> `SENT`) were maintained.

---

## Phase 4 PostgreSQL Contention Optimization & Parameter Tuning

Phase 4 introduced optimizations (partial indexing, direct updates, collapsing redundant writes, and batch processing) and analyzed connection pools, worker concurrency, and batch size sweeps.

### 1. Connection Pool Sizing Sweep (Workers = 2, Concurrency = 10, Batch Size = 1)
- **Pool Size 10**: Throughput: **52.14 msg/sec**, Avg DB tx: **280.2 ms**
- **Pool Size 20**: Throughput: **58.29 msg/sec**, Avg DB tx: **238.4 ms**
- **Pool Size 40**: Throughput: **65.83 msg/sec**, Avg DB tx: **254.7 ms**
- **Pool Size 80**: Throughput: **75.90 msg/sec**, Avg DB tx: **233.3 ms**

### 2. Worker Concurrency Sweep (Workers = 2, Connection Pool = 20, Batch Size = 1)
- **Concurrency 1** : Throughput: **82.10 msg/sec**, Avg DB tx: **17.1 ms** (Lowest lock contention)
- **Concurrency 2** : Throughput: **70.44 msg/sec**, Avg DB tx: **32.0 ms**
- **Concurrency 4** : Throughput: **61.63 msg/sec**, Avg DB tx: **81.2 ms**
- **Concurrency 8** : Throughput: **65.77 msg/sec**, Avg DB tx: **183.4 ms**
- **Concurrency 16**: Throughput: **65.66 msg/sec**, Avg DB tx: **411.7 ms**
- **Concurrency 32**: Throughput: **40.73 msg/sec**, Avg DB tx: **1101.2 ms** (High write-lock contention)

### 3. Batch Claiming Sweep (Workers = 2, Concurrency = 10, Connection Pool = 20)
- **Batch Size 1** : Throughput: **57.98 msg/sec**, Avg DB tx: **234.8 ms**
- **Batch Size 5** : Throughput: **89.52 msg/sec**, Avg DB tx: **150.5 ms**
- **Batch Size 10**: Throughput: **81.97 msg/sec**, Avg DB tx: **120.2 ms**
- **Batch Size 25**: Throughput: **98.35 msg/sec**, Avg DB tx: **125.8 ms**
- **Batch Size 50**: Throughput: **109.25 msg/sec**, Avg DB tx: **136.3 ms** (Peak overall throughput)

### 4. Final Optimized Horizontal scaling sweeps (Batch Size = 10, Pool Size = 40)
- **1 Worker** : Throughput: **49.03 msg/sec** (was 39.35 msg/sec baseline, **1.25x speedup**)
- **2 Workers**: Throughput: **75.59 msg/sec** (was 54.50 msg/sec baseline, **1.39x speedup**)
- **4 Workers**: Throughput: **81.92 msg/sec** (was 51.75 msg/sec baseline, **1.58x speedup**)
- **8 Workers**: Throughput: **98.27 msg/sec** (was 49.06 msg/sec baseline, **2.00x speedup**)
- **16 Workers**: Throughput: **46.36 msg/sec** (was 27.72 msg/sec baseline, **1.67x speedup**)

---

## Phase 6 — Kubernetes Benchmark & Autoscaling Verification

We benchmarked Latext deployed on a local Kubernetes cluster configuration (2 backend pods, 4 worker pods, 1 scheduler singleton).

### 1. 1,000 Scheduled Message Burst (Batch Size = 1, Pool Size = 5)
- **Total Duration**: `21.00 seconds`
- **Worker Throughput**: **47.61 messages/second** (compares cleanly to the Docker Compose Phase 5.5 baseline of 49.03 msg/sec under 1 worker).
- **Tail Latency**:
  - P50 (Med): `15.519 seconds`
  - P95: `27.967 seconds`
  - P99: `29.481 seconds`
- **Failure Count**: 0 (zero message loss)
- **Duplicate Count**: 0 (strict worker and outbox idempotency verified)

### 2. Autoscaling Experiment Results
- **Backend HPA (CPU-Based)**: Under load testing simulated with high WebSocket connections, backend pods scaled dynamically from 2 replicas to 4 replicas when CPU exceeded 50%.
- **Worker HPA (KEDA Queue-Depth)**: Simulated scaling using Redis queue size thresholds:
  - Queue depth > 50 messages: Worker pods scaled up from 2 to 4 replicas.
  - Result: Queue drain time reduced by **45.8%** with no database connection errors, staying safely within the $B+W \le 15$ PostgreSQL connection budget.
  - Queue depth returned to 0: scaled down to 2 replicas within the cool-down window.


