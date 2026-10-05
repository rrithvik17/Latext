from prometheus_client import Counter, Histogram, Gauge, REGISTRY

# Safe Metric Registration Helpers (pre-empts ValueError in reloads/tests)
def get_or_create_counter(name, documentation, labelnames=()):
    if name in REGISTRY._names_to_collectors:
        return REGISTRY._names_to_collectors[name]
    return Counter(name, documentation, labelnames=labelnames)


def get_or_create_histogram(name, documentation, labelnames=()):
    if name in REGISTRY._names_to_collectors:
        return REGISTRY._names_to_collectors[name]
    return Histogram(name, documentation, labelnames=labelnames)


def get_or_create_gauge(name, documentation, labelnames=()):
    if name in REGISTRY._names_to_collectors:
        return REGISTRY._names_to_collectors[name]
    return Gauge(name, documentation, labelnames=labelnames)


# --- Scheduler Metrics ---
scheduler_poll_total = get_or_create_counter(
    "scheduler_poll_total",
    "Total number of polling cycles executed by the scheduler"
)
scheduler_poll_duration = get_or_create_histogram(
    "scheduler_poll_duration",
    "Time taken to execute scheduler poll cycle in seconds"
)
scheduler_jobs_discovered_total = get_or_create_counter(
    "scheduler_jobs_discovered_total",
    "Total number of due jobs discovered in the database"
)
scheduler_jobs_enqueued_total = get_or_create_counter(
    "scheduler_jobs_enqueued_total",
    "Total number of jobs successfully pushed to Redis"
)
scheduled_jobs_discovered = scheduler_jobs_discovered_total
scheduled_jobs_enqueued = scheduler_jobs_enqueued_total

# --- Queue Metrics ---
jobs_enqueued_total = get_or_create_counter(
    "jobs_enqueued_total",
    "Total number of jobs pushed to the queue list"
)
jobs_consumed_total = get_or_create_counter(
    "jobs_consumed_total",
    "Total number of jobs popped from the queue list"
)
jobs_retried_total = get_or_create_counter(
    "jobs_retried_total",
    "Total number of job retry operations executed"
)
jobs_dead_lettered_total = get_or_create_counter(
    "jobs_dead_lettered_total",
    "Total number of jobs moved to the dead letter queue (DLQ)"
)
queue_processing_duration = get_or_create_histogram(
    "queue_processing_duration",
    "Latency from scheduled_at time to message creation in seconds"
)

# --- Worker Metrics ---
worker_jobs_processed_total = get_or_create_counter(
    "worker_jobs_processed_total",
    "Total number of jobs processed by workers"
)
worker_jobs_failed_total = get_or_create_counter(
    "worker_jobs_failed_total",
    "Total number of job failures during worker processing"
)
worker_job_duration = get_or_create_histogram(
    "worker_job_duration",
    "Time taken for worker to process a job in seconds"
)
worker_active_jobs = get_or_create_gauge(
    "worker_active_jobs",
    "Number of jobs currently being executed by the worker"
)

# --- Message Lifecycle Metrics ---
scheduled_messages_sent_total = get_or_create_counter(
    "scheduled_messages_sent_total",
    "Total number of scheduled messages marked SENT in DB"
)
scheduled_messages_failed_total = get_or_create_counter(
    "scheduled_messages_failed_total",
    "Total number of scheduled messages marked FAILED in DB"
)
scheduled_messages_cancelled_total = get_or_create_counter(
    "scheduled_messages_cancelled_total",
    "Total number of scheduled messages marked CANCELLED in DB"
)

# --- Phase 3.5 Pipeline Metrics ---
scheduler_discovery_latency = get_or_create_histogram(
    "scheduler_discovery_latency",
    "Latency from scheduled target time to scheduler discovery (seconds)"
)
scheduler_enqueue_latency = get_or_create_histogram(
    "scheduler_enqueue_latency",
    "Time spent enqueuing the message job to Redis (seconds)"
)
redis_enqueue_latency = get_or_create_histogram(
    "redis_enqueue_latency",
    "Time spent publishing job to Redis (seconds)"
)
redis_dequeue_latency = get_or_create_histogram(
    "redis_dequeue_latency",
    "Time spent in Redis dequeue/blpop block operation (seconds)"
)
queue_wait_latency = get_or_create_histogram(
    "queue_wait_latency",
    "Latency spent waiting in the queue (dequeue_time - enqueue_time) (seconds)"
)
queue_depth = get_or_create_gauge(
    "queue_depth",
    "Current length of the Redis scheduled queue"
)
worker_processing_latency = get_or_create_histogram(
    "worker_processing_latency",
    "Total processing time of worker from dequeue to end (seconds)"
)
worker_db_transaction_latency = get_or_create_histogram(
    "worker_db_transaction_latency",
    "Time spent in database transaction block (seconds)"
)
worker_message_creation_latency = get_or_create_histogram(
    "worker_message_creation_latency",
    "Time spent creating and flushing message record inside transaction (seconds)"
)
worker_backend_handoff_latency = get_or_create_histogram(
    "worker_backend_handoff_latency",
    "Time spent in HTTP REST backend handoff request (seconds)"
)
backend_internal_broadcast_latency = get_or_create_histogram(
    "backend_internal_broadcast_latency",
    "Time spent inside backend broadcast route execution (seconds)"
)
websocket_broadcast_latency = get_or_create_histogram(
    "websocket_broadcast_latency",
    "Time spent broadcasting message to active websocket clients (seconds)"
)
scheduled_to_enqueue_latency = get_or_create_histogram(
    "scheduled_to_enqueue_latency",
    "Latency from scheduled target time to enqueued in Redis (seconds)"
)
enqueue_to_dequeue_latency = get_or_create_histogram(
    "enqueue_to_dequeue_latency",
    "Latency from Redis enqueue time to worker dequeue time (seconds)"
)
dequeue_to_processing_latency = get_or_create_histogram(
    "dequeue_to_processing_latency",
    "Latency from worker dequeue to worker processing start (seconds)"
)
processing_latency = get_or_create_histogram(
    "processing_latency",
    "Latency from worker processing start to WebSocket delivery complete (seconds)"
)
scheduled_to_delivery_latency = get_or_create_histogram(
    "scheduled_to_delivery_latency",
    "Total latency from scheduled target time to delivery complete (seconds)"
)

