# Latext — Engineering Evolution & Architectural Case Study

This document details the progressive engineering journey of **Latext** from a single-node real-time chat prototype to a resilient, horizontally scaled distributed messaging platform.

---

## 1. Executive Summary

Latext was built to solve a core messaging problem: **delivering messages reliably at a precise future timestamp across global timezones**, while maintaining sub-millisecond real-time chat. 

The project evolved through 10 engineering phases. Rather than adopting complex technologies prematurely, each architectural layer was introduced in response to concrete empirical bottlenecks discovered during load testing and failure injection.

---

## 2. Phase-by-Phase Architectural Journey

### Phase 1: Real-Time Messaging Baseline
* **Goal**: Establish the fundamental chat application.
* **Architecture**: FastAPI, PostgreSQL, WebSockets, Next.js.
* **Key Mechanisms**:
  - 1-to-1 conversations backed by PostgreSQL with UUID primary keys.
  - Delivery lifecycle states: `SENT` $\rightarrow$ `DELIVERED` $\rightarrow$ `READ`.
  - In-memory WebSocket connection manager attached to the ASGI process.

---

### Phase 2: Scheduled Messaging & Timezone Engine
* **Goal**: Add deferred message scheduling.
* **Architecture**: Introduction of the `ScheduledMessage` entity and background polling.
* **Key Challenges Solved**:
  - **Timezone & DST Validation**: Users schedule in local time (e.g. `Europe/Copenhagen` or `America/New_York`). The backend converts local time to UTC, explicitly rejecting ambiguous or non-existent times caused by Daylight Saving Time (DST) transitions using Python's `zoneinfo`.
  - **Single Worker Poller**: An async background task periodically queried `WHERE scheduled_at_utc <= NOW() AND status = 'SCHEDULED'`.

---

### Phase 3: Distributed Queue & Worker Decoupling
* **Goal**: Isolate scheduling execution from user-facing API workloads.
* **Bottleneck Discovered**: Running heavy message creation loops inside the web API server degraded HTTP request latency.
* **Architectural Decision**:
  - Introduced **Redis List Queues** (`latext:scheduled:queue`) as a buffer.
  - Separated the application into distinct processes: `backend`, `scheduler`, and stateless `worker` nodes.
  - Built an exponential backoff retry mechanism with a Dead-Letter Queue (`latext:scheduled:dead-letter`).

---

### Phase 4: The Database Contention Discovery
* **Goal**: Benchmark scheduler and worker throughput at 1,000 scheduled messages.
* **The Problem Discovered**:
  - During Phase 4 benchmarks, increasing worker concurrency from 1 to 5 did *not* scale throughput linearly. In fact, scaling beyond 4 workers caused throughput to drop and error rates to spike.
* **The Root Cause**:
  - Multiple workers were concurrently issuing `SELECT ... FOR UPDATE` row locks on the same database rows when claiming jobs.
  - PostgreSQL transaction locks and connection pool contention became the primary bottleneck.
* **The Empirical Experiment**:
  - Systematically ran parameter grid experiments testing Worker Count (1 to 8), Batch Size (1 to 50), and Concurrency (1 to 20).
* **The Solution**:
  1. Utilized PostgreSQL's `FOR UPDATE SKIP LOCKED` inside the scheduler coordinator to eliminate worker lock contention.
  2. Batched database status transitions into single atomic operations.
  3. Tuned worker pool size to match optimal database connection throughput, achieving a peak throughput of **109.25 messages/sec**.

---

### Phase 5: Distributed Multi-Backend WebSocket Fanout
* **Goal**: Horizontally scale backend API nodes behind a load balancer.
* **The Problem**:
  - When User A is connected to WebSocket on `backend-1` and User B is connected to `backend-2`, messages created on `backend-1` could not reach User B because WebSocket connections resided in separate process memories.
* **The Solution**:
  - Introduced **Redis Pub/Sub** on the channel `latext:events`.
  - Each backend node subscribes to the channel on startup and forwards incoming message events to its locally connected WebSocket clients.

---

### Phase 5.5: Transactional Outbox & Crash Resilience
* **Goal**: Ensure guaranteed message delivery without dual-write inconsistencies.
* **The Dual-Write Problem**:
  - Writing to PostgreSQL and publishing to Redis Pub/Sub in sequence can fail if the process crashes after the DB commit but before the Redis publish, permanently dropping the message event.
* **The Solution**:
  - Implemented the **Transactional Outbox Pattern**:
    1. The chat message and an `OutboxEvent` record are inserted atomically in the same PostgreSQL transaction.
    2. An asynchronous Outbox Publisher daemon claims unhandled outbox events using lease-based claiming (`FOR UPDATE SKIP LOCKED`).
    3. Events are published to Redis Pub/Sub, and the outbox records are marked as published.
  - Result: Guaranteed at-least-once delivery with zero dropped events across pod crashes.

---

### Phase 6: Kubernetes Orchestration & KEDA Autoscaling
* **Goal**: Deploy Latext to Kubernetes with dynamic autoscaling.
* **Architecture**:
  - `backend` Deployment with horizontal pod scaling (HPA) and graceful shutdown (`preStop` sleep hooks).
  - `postgres` StatefulSet with persistent volume claims.
  - `redis` Deployment with ClusterIP service.
  - `scheduler` singleton Deployment (ensuring single coordinator leader).
  - `worker` Deployment managed by **KEDA (Kubernetes Event-driven Autoscaling)** triggered dynamically by Redis queue length.
  - Prometheus and Grafana observability stack scraping metrics from all pods.

---

### Phase 7: Production Engineering, CI/CD & Security Hardening
* **Goal**: Enforce production-grade security, container hardening, and automated CI/CD.
* **Implementations**:
  - **Least Privilege**: Hardened Docker containers to execute under non-root users (`appuser` UID 10001, `node` UID 1000).
  - **CI/CD Pipeline**: GitHub Actions workflow running formatting audits, full integration test suites, and frontend production builds.
  - **Database Migrations**: Automated Alembic migrations running as a single-run Kubernetes `Job` prior to application rollouts.

---

### Phase 7.5 & 7.6: Architecture Audit & DLQ Transaction Remediation
* **Goal**: Rigorous production readiness audit and transaction boundary safety.
* **The Vulnerability Identified**:
  - `worker.py` was invoking `redis_client.rpush` to the Dead-Letter Queue *inside* an active PostgreSQL write transaction holding row locks. If Redis was slow or offline, database transactions were held open, exhausting the connection pool.
* **The Remediation**:
  1. Decoupled all Redis operations from PostgreSQL transactions. Failed jobs transition to `FAILED_PENDING_DLQ` in PostgreSQL and commit before any Redis network interaction.
  2. If Redis is down, the durable status remains `FAILED_PENDING_DLQ`. The scheduler's `recover_stalled_messages` daemon periodically republishes stalled DLQ items once Redis returns.
  3. Established a deterministic **PostgreSQL Connection Budget Formula**:
     $$C_{\text{total}} = (B \times 15) + (W \times 15) + (S \times 15) + C_{\text{reserve}} \le 300$$
     Enforcing maximum KEDA worker autoscaling bounds so that database connection capacity is never exceeded.

---

### Phase 8: Product Polish & UX
* **Goal**: Transform the project into a resume-worthy product.
* **Key Enhancements**:
  - WhatsApp-style chat interface with real-time delivery state indicators: `SENT` (✓), `DELIVERED` (✓✓), `READ` (✓✓).
  - Dedicated Scheduled Queue with inline editing, cancellation confirmation, and race-condition handling.
  - Human-readable Daylight Saving Time error messages.
  - Real-time WebSocket connection state feedback (`Connected`, `Connecting...`, `Reconnecting...`).
  - Mobile responsive drawer navigation.

---

## 3. Engineering Decisions Matrix

| Requirement | Alternative Considered | Chosen Decision | Rationale |
| :--- | :--- | :--- | :--- |
| **Schedule Buffer** | PostgreSQL Polling | Redis Queue (`blpop`) | Decouples DB read locks from worker worker loops; sub-millisecond popping. |
| **Dual-Write Safety** | Two-Phase Commit (2PC) | Transactional Outbox | 2PC has severe latency and availability penalties; Outbox provides at-least-once guarantee with PostgreSQL ACID. |
| **Multi-Pod Fanout** | Kafka / RabbitMQ | Redis Pub/Sub | Latext already operates Redis; Pub/Sub provides low-latency ephemeral broadcast without broker overhead. |
| **Worker Scalability** | CPU/Memory HPA | KEDA Queue Metric | Queue depth directly reflects pending workload; CPU utilization is a lagging indicator. |
| **Row Locking** | Optimistic Locking | `FOR UPDATE SKIP LOCKED` | Eliminates lock contention and serialization aborts under high worker concurrency. |
