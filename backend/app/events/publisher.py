import json
import time
import logging
from app.queue.client import redis_client
from app.events.schemas import MessageCreatedEvent, MessageStatusEvent
from prometheus_client import Counter

logger = logging.getLogger("events_publisher")
EVENTS_CHANNEL = "latext:events"

# Prometheus metrics
events_published_total = Counter(
    "events_published_total",
    "Total events published to Redis Pub/Sub",
    ["event_type"]
)
event_publish_failures_total = Counter(
    "event_publish_failures_total",
    "Total event publish failures",
    ["event_type"]
)

async def publish_message_created(message_id: str, conversation_id: str, recipient_user_id: str, sender_user_id: str):
    """
    Publishes a message.created event to Redis Pub/Sub.
    """
    event = MessageCreatedEvent(
        timestamp=time.time(),
        message_id=message_id,
        conversation_id=conversation_id,
        recipient_user_id=recipient_user_id,
        sender_user_id=sender_user_id
    )
    payload = event.model_dump_json()
    try:
        await redis_client.publish(EVENTS_CHANNEL, payload)
        events_published_total.labels(event_type="message.created").inc()
        logger.info(f"Published message.created event for message {message_id}")
    except Exception as e:
        event_publish_failures_total.labels(event_type="message.created").inc()
        logger.error(f"Failed to publish message.created event: {e}")

async def publish_message_status(message_id: str, conversation_id: str, recipient_user_id: str, status: str):
    """
    Publishes a message.status event to Redis Pub/Sub.
    """
    event = MessageStatusEvent(
        timestamp=time.time(),
        message_id=message_id,
        conversation_id=conversation_id,
        recipient_user_id=recipient_user_id,
        status=status
    )
    payload = event.model_dump_json()
    try:
        await redis_client.publish(EVENTS_CHANNEL, payload)
        events_published_total.labels(event_type="message.status").inc()
        logger.info(f"Published message.status event for message {message_id} with status {status}")
    except Exception as e:
        event_publish_failures_total.labels(event_type="message.status").inc()
        logger.error(f"Failed to publish message.status event: {e}")
