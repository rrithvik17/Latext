# Phase 4 Performance Analysis & Optimization Report - PostgreSQL Contention & Throughput

This document profiles the scheduled-message pipeline in a distributed environment, analyzes scaling characteristics, details parameter tuning sweeps, and presents the architectural optimizations that resolved PostgreSQL contention.

---

## 1. Summary of Optimizations

The following optimizations were implemented to resolve write-lock contention and database latency:
1. **Partial Indexing**: Created a partial index `ix_scheduled_messages_due_partial` on `scheduled_messages (scheduled_at_utc) WHERE status = 'SCHEDULED'`. This reduced query lookups from `Seq Scan` to `Index Scan`, decreasing query execution time from `0.528 ms` to `0.091 ms` (**5.8x speedup**).
2. **Reduced DB Roundtrips**: Eliminated the redundant intermediate update `status = 'PROCESSING'` inside the main transaction. If the worker crashes, the PostgreSQL transaction rolls back and the scheduler recovers the stuck job. This reduced roundtrips by 1.
3. **Direct UPDATE**: Replaced the sequential `SELECT` conversation query with a direct, non-blocking `UPDATE` statement targeting conversation activity. This reduced roundtrips by 1.
4. **Batch Claiming & Processing**: Implemented a batch processing loop that claims up to `N` due messages from Redis and executes their database updates in a single bulk transaction. If the batch fails, the worker automatically rolls back and retries each message individually (safe fallback pathway), preserving idempotency and preventing cascading failures.

---

## 2. Optimized Scaling Sweeps (Batch Size = 10, Pool Size = 40)

Running a burst load of 1,000 scheduled messages all due simultaneously after optimizations:

| Workers | Concurrency | Total Duration | Throughput | P50 Latency | P95 Latency | P99 Latency | Failures | Duplicates | Lost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | 10 | `20.40 seconds` | **49.03 msg/sec** | `13.021 s` | `19.139 s` | `19.571 s` | 0 | 0 | 0 |
| **2** | 10 | `13.23 seconds` | **75.59 msg/sec** | `8.565 s` | `12.889 s` | `13.141 s` | 0 | 0 | 0 |
| **4** | 10 | `12.21 seconds` | **81.92 msg/sec** | `8.709 s` | `11.941 s` | `12.119 s` | 0 | 0 | 0 |
| **8** | 10 | `10.18 seconds` | **98.27 msg/sec** | `7.063 s` | `9.972 s` | `10.114 s` | 0 | 0 | 0 |
| **16** | 10 | `21.57 seconds` | **46.36 msg/sec** | `14.529 s` | `20.849 s` | `21.468 s` | 0 | 0 | 0 |

> [!NOTE]
> Scaling to **8 worker containers** yielded a peak throughput of **98.27 msg/sec**, nearly doubling the pre-optimization horizontal scale limit. Beyond 8 workers, connection pool contention on the 300 max_connections database ceiling leads to saturation.

---

## 3. Parameter Tuning Sweeps (Sweep Results)

We isolated connection pool size, worker concurrency, and batch sizes in controlled sweeps (using 2 workers and 1,000 messages):

### 3.1 Connection Pool Sweep (Workers = 2, Concurrency = 10, Batch Size = 1)

| Pool Size | Duration (s) | Throughput (msg/s) | Avg DB Transaction Time (ms) |
| :--- | :--- | :--- | :--- |
| **10** | `19.18` | **52.14** | `280.2 ms` |
| **20** | `17.16` | **58.29** | `238.4 ms` |
| **40** | `15.19` | **65.83** | `254.7 ms` |
| **80** | `13.18` | **75.90** | `233.3 ms` |

*Insight*: Larger connection pool sizes eliminate checkout delays for workers.

### 3.2 Worker Concurrency Sweep (Workers = 2, Connection Pool = 20, Batch Size = 1)

| Concurrency | Duration (s) | Throughput (msg/s) | Avg DB Transaction Time (ms) |
| :--- | :--- | :--- | :--- |
| **1** | `12.18` | **82.10** | `17.1 ms` |
| **2** | `14.20` | **70.44** | `32.0 ms` |
| **4** | `16.23` | **61.63** | `81.2 ms` |
| **8** | `15.20` | **65.77** | `183.4 ms` |
| **16** | `15.23` | **65.66** | `411.7 ms` |
| **32** | `24.55` | **40.73** | `1101.2 ms` |

*Insight*: Higher in-worker concurrency directly triggers write-lock contention in PostgreSQL, causing database transaction times to spike from **17.1 ms** (concurrency=1) to **1101.2 ms** (concurrency=32), which degrades overall throughput.

### 3.3 Batch Claiming Sweep (Workers = 2, Concurrency = 10, Connection Pool = 20)

| Batch Size | Duration (s) | Throughput (msg/s) | Avg DB Transaction Time (ms) |
| :--- | :--- | :--- | :--- |
| **1** | `17.25` | **57.98** | `234.8 ms` |
| **5** | `11.17` | **89.52** | `150.5 ms` |
| **10** | `12.20` | **81.97** | `120.2 ms` |
| **25** | `10.17` | **98.35** | `125.8 ms` |
| **50** | `9.15` | **109.25** | `136.3 ms` |

*Insight*: Batching is the single most effective throughput enhancer. Grouping messages into a single database transaction allows us to achieve **109.25 msg/sec**, reducing transactional overhead and lock intervals.

---

## 4. Architectural Recommendations

To sustain high throughput under production loads, configure:
1. **Worker Concurrency**: Set `WORKER_CONCURRENCY=5` to `10`.
2. **Batch size**: Set `WORKER_BATCH_SIZE=10` to `25`.
3. **Database connection pool**: Configure `DATABASE_POOL_SIZE=40` or higher to prevent connection starvation.
4. **Replica Count**: Scale workers up to **8 replicas** dynamically based on queue depth.
