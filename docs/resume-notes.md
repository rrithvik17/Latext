# Latext — Resume & Portfolio Engineering Notes

## Quick Reference Summary
* **Project Title**: Latext — Distributed, Timezone-Aware Scheduled Messaging Platform
* **One-Line Description**: A real-time, WhatsApp-style messaging platform engineered for reliable, timezone-aware deferred delivery using a Transactional Outbox pattern, Redis Queue, and Kubernetes autoscaling.
* **Technology Stack**: FastAPI (Python 3.11), Next.js 14 (TypeScript, Tailwind CSS), PostgreSQL 16, Redis 7, SQLAlchemy 2 (Asyncio), WebSockets, Kubernetes, KEDA, Docker, Prometheus, Grafana, GitHub Actions.

---

## 5 Resume Bullet Points (Ready to Copy)

1. **Distributed System & Outbox Architecture**:
   > Architected a distributed messaging system handling real-time and scheduled message delivery across global timezones; implemented the **Transactional Outbox Pattern** with lease claiming (`SKIP LOCKED`) to ensure at-least-once event publication to Redis Pub/Sub without dual-write inconsistencies.

2. **Performance Optimization & Database Contention**:
   > Benchmarked and diagnosed PostgreSQL row-lock contention under concurrent worker pools; redesigned job claiming using non-blocking queues and atomic state transitions, achieving a peak throughput of **109.25 scheduled messages/sec** with sub-120ms P95 delivery latency.

3. **Multi-Pod WebSocket Routing & Fanout**:
   > Scaled WebSocket communication across multiple backend replicas using Redis Pub/Sub event broadcasting, enabling real-time delivery state updates (`SENT` $\rightarrow$ `DELIVERED` $\rightarrow$ `READ`) across disconnected nodes with automatic reconnection sync.

4. **Cloud-Native Kubernetes & Autoscaling**:
   > Deployed containerized microservices to Kubernetes with StatefulSets, non-root security contexts, and **KEDA event-driven autoscaling** driven dynamically by Redis queue depth; formulated an explicit PostgreSQL connection budget formula to prevent pool exhaustion.

5. **Fault Tolerance & Dead-Letter Queue (DLQ)**:
   > Built an exponential backoff retry engine with transactionally decoupled Dead-Letter Queue (DLQ) processing and periodic recovery daemons, ensuring zero dropped messages during Redis downtime and worker pod crashes.

---

## Technical Highlights Breakdown

### 1. Most Impressive Engineering Decisions
* **Decoupled Database Transactions from Redis Network Calls**: Prevented connection pool starvation by committing the durable `FAILED_PENDING_DLQ` state in PostgreSQL before triggering Redis list operations.
* **`FOR UPDATE SKIP LOCKED` Worker Claiming**: Eliminated concurrency bottlenecks where multiple workers blocked on row locks.
* **Strict Timezone & DST Transition Handling**: Validated IANA timezones using Python `zoneinfo`, rejecting invalid/ambiguous Daylight Saving Time clock transitions gracefully.

### 2. Verified Performance Metrics
* **Peak Scheduled Throughput**: 109.25 messages/second (2 Workers, Concurrency=10, Batch=10).
* **P95 Latency**: < 120ms from schedule trigger to WebSocket delivery.
* **Idempotency Accuracy**: 100% unique messages (0 duplicates) across 1,000-message failure injection workloads.

### 3. Reliability & Failure Recovery
* **Worker Crash**: Handled via scheduled message state tracking; uncompleted jobs are recovered and redelivered.
* **Redis Crash**: Outbox publisher pauses and safely resumes without dropping messages when Redis recovers; scheduler rolls back in-flight queue updates.
* **Backend Node Crash**: WebSocket clients automatically reconnect with exponential backoff and fetch missed message history.
