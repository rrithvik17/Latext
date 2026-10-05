# Latext — Distributed Systems Interview Deep-Dive Guide

This guide contains technical explanations for 21 core architectural decisions in Latext.

---

### 1. Why Redis Queue for scheduled message jobs?
Redis list queues (`LPUSH` / `BLPOP`) provide in-memory, sub-millisecond job dispatching. Using Redis decouples the database from high-frequency polling loops, allowing worker pools to block on a lightweight Redis socket rather than hammering PostgreSQL with `SELECT` queries.

---

### 2. Why PostgreSQL as the ultimate source of truth?
PostgreSQL provides strict ACID transactions and relational integrity. Messaging requires relational consistency between users, conversation memberships, message records, and delivery states. If Redis experiences catastrophic data loss, the entire schedule queue and message history can be fully reconstructed from PostgreSQL.

---

### 3. Why the Transactional Outbox Pattern?
When a message is sent, the system must both persist the message in PostgreSQL and publish an event to Redis Pub/Sub. Performing a database write followed by a network publish creates a **dual-write problem**—if the process crashes between the two, the event is lost. The Transactional Outbox pattern writes the message and an `outbox_events` row in the *same* database transaction. An asynchronous daemon then publishes the event, ensuring **at-least-once** event publication.

---

### 4. Why Redis Pub/Sub for WebSocket fanout?
Redis Pub/Sub provides low-latency, memory-efficient broadcast messaging across multiple backend pods. Because WebSocket connections are stateful and tied to specific process instances, Redis Pub/Sub allows any backend pod to publish an event that is instantly broadcast to all pods holding active client connections.

---

### 5. Why not Kafka or RabbitMQ?
Kafka introduces operational overhead (Zookeeper/KRaft, partition rebalancing, storage management) that is unwarranted for Latext's single-region traffic profile. Latext already runs Redis for caching and queues; utilizing Redis for ephemeral pub/sub and list queues kept the infrastructure lightweight while meeting sub-millisecond latency targets.

---

### 6. Why `SELECT ... FOR UPDATE SKIP LOCKED`?
Standard `FOR UPDATE` locks cause concurrent workers to block and wait for another worker's transaction to release. Under high worker concurrency, this causes serialization lock contention. `SKIP LOCKED` instructs PostgreSQL to bypass rows that are already locked by another transaction, allowing multiple workers and outbox publishers to claim distinct jobs concurrently without lock contention.

---

### 7. Why batch processing in the scheduler?
Individual `UPDATE` queries for each due message incur network round-trip overhead and multiple database transactions. The scheduler coordinator queries due messages in batches (e.g., 50 at a time), updates their status to `QUEUED` in a single SQL statement, and pushes the batch to Redis, drastically reducing coordinator overhead.

---

### 8. What caused the performance bottleneck discovered in Phase 4?
During initial benchmarks, multiple workers were issuing concurrent `SELECT ... FOR UPDATE` queries directly against the `ScheduledMessage` table. The row-lock contention and database connection pool saturation caused transaction holding times to spike, degrading overall system throughput.

---

### 9. Why did adding more workers eventually reduce throughput?
PostgreSQL connection capacity is finite. As worker concurrency increased beyond optimal thresholds, worker threads spent more time waiting for database connection pool slots and acquiring lock queues than executing message logic. The overhead of context switching and lock contention resulted in sub-linear scaling and eventual throughput drop.

---

### 10. How does idempotency work?
Every scheduled message has a unique `id`. When a worker processes a scheduled message, it inserts a chat `Message` with `scheduled_message_id = scheduled.id`. PostgreSQL enforces a `UNIQUE` constraint on `messages.scheduled_message_id`. If a network timeout causes a worker to retry processing the same job, the unique constraint or worker idempotency check prevents duplicate message creation.

---

### 11. What happens if Redis crashes?
1. **Outbox Events**: The Outbox Publisher encounters a connection error and safely backs off. Outbox records remain in PostgreSQL as `PENDING`. When Redis recovers, the publisher resumes without dropping any events.
2. **Scheduled Queue**: The scheduler fails to push due jobs to Redis, leaving their status in PostgreSQL. Once Redis recovers, the scheduler resumes enqueuing.
3. **Dead-Letter Queue**: If Redis fails during DLQ push, the job remains in PostgreSQL with status `FAILED_PENDING_DLQ` and is recovered by the scheduler once Redis returns.

---

### 12. What happens if a worker pod crashes mid-execution?
If a worker crashes while processing a job:
- If the database transaction did not commit, the message remains un-sent and the job status remains `QUEUED` or reverts during scheduler recovery.
- If the database transaction committed, the message exists in PostgreSQL. If the job is re-delivered, the worker's idempotency check detects the existing message and transitions cleanly to `SENT` without creating a duplicate.

---

### 13. What happens if a backend API pod crashes?
Active WebSocket connections on that pod terminate. The Next.js frontend automatically enters `Reconnecting...` mode and attempts reconnection with exponential backoff. The Kubernetes Service routes the client to a healthy backend pod. Upon reconnection, the client queries the REST API for missed message history.

---

### 14. Why is the scheduler a singleton deployment in Kubernetes?
The scheduler coordinator is responsible for identifying due messages (`scheduled_at_utc <= NOW()`) and moving them from PostgreSQL to Redis. Running a single scheduler replica eliminates leader election complexity and guarantees that scheduling timestamps are evaluated linearly.

---

### 15. How does KEDA scale workers?
KEDA monitors the length of the Redis list queue (`latext:scheduled:queue`). When the queue depth exceeds a configured threshold (e.g., > 10 messages), KEDA automatically scales out the worker Deployment replicas from 1 up to the maximum replica limit. When the queue clears, KEDA scales the workers back down.

---

### 16. What limits worker scaling in production?
Worker scaling is bounded by the **PostgreSQL Connection Budget**:
$$C_{\text{total}} = (B \times 15) + (W \times 15) + (S \times 15) + C_{\text{reserve}} \le 300$$
Each worker pod allocates a database connection pool (default: 15 connections). If worker replicas scale without bounds, they will exhaust PostgreSQL's `max_connections` (300), causing backend API failures. KEDA's `maxReplicaCount` is strictly enforced to stay within the connection budget.

---

### 17. How are WebSockets distributed across multiple nodes?
Each backend pod maintains its own in-memory dictionary of active WebSocket connections (`connection_manager.py`). When an event arrives via Redis Pub/Sub, each pod checks if the target recipient is connected to its local process. If connected, the pod writes the message frame to the client's WebSocket. If not, the pod ignores the event.

---

### 18. What are the delivery guarantees?
- **WebSocket Broadcast**: At-least-once delivery with client-side deduplication.
- **Scheduled Messages**: At-least-once execution backed by database-level idempotency constraints.
- **Message Persistence**: Strict ACID durability in PostgreSQL.

---

### 19. What does the Transactional Outbox guarantee?
It guarantees that an event will **never be lost** if a message is successfully written to the database. Even during catastrophic process termination, the outbox record persists in PostgreSQL and will be published when the daemon recovers.

---

### 20. What would you change at 10× traffic (~1,000 msg/sec)?
1. **Connection Pooling**: Deploy **PgBouncer** in transaction-pooling mode in front of PostgreSQL to support hundreds of worker pods without connection exhaustion.
2. **Database Read Replicas**: Route historical message retrieval queries (`GET /conversations/{id}/messages`) to read replicas.
3. **Partitioning**: Partition the `messages` and `scheduled_messages` tables by date range (`created_at`).

---

### 21. What would you change at 100× traffic (~10,000 msg/sec)?
1. **Message Storage Migration**: Migrate long-term historical message storage from PostgreSQL to a distributed wide-column store like **Apache Cassandra** or **ScyllaDB**.
2. **Message Broker**: Replace Redis list queues with **Apache Kafka** or **AWS SQS** for partitioned stream processing and persistent replay capabilities.
3. **Dedicated Ephemeral Cluster**: Separate Redis caching from Redis Pub/Sub across independent clusters.
