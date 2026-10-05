import asyncio
import json
import logging
import time
import uuid
from app.queue.client import redis_client, check_redis_health
from app.websocket.connection_manager import manager
from app.core.database import SessionLocal
from app.models.message import Message
from app.models.conversation import ConversationParticipant
from sqlalchemy import select, update
from app.events.publisher import publish_message_status, EVENTS_CHANNEL
from prometheus_client import Counter, Histogram

logger = logging.getLogger("events_subscriber")

# Prometheus metrics
events_consumed_total = Counter(
    "events_consumed_total",
    "Total events consumed from Redis Pub/Sub",
    ["event_type"]
)
event_processing_failures_total = Counter(
    "event_processing_failures_total",
    "Total event processing failures",
    ["event_type"]
)
event_processing_duration = Histogram(
    "event_processing_duration",
    "Time spent processing a Pub/Sub event",
    ["event_type"]
)
websocket_delivery_total = Counter(
    "websocket_delivery_total",
    "Total messages delivered via WebSocket"
)
websocket_delivery_failures_total = Counter(
    "websocket_delivery_failures_total",
    "Total WebSocket delivery failures"
)


async def handle_event(payload_str: str):
    """
    Parses and dispatches Redis Pub/Sub events.
    """
    try:
        data = json.loads(payload_str)
        event_type = data.get("event_type")
        if not event_type:
            logger.error("Event payload missing event_type")
            return
            
        t_start = time.time()
        events_consumed_total.labels(event_type=event_type).inc()
        
        if event_type == "message.created":
            await handle_message_created(data)
        elif event_type == "message.status":
            await handle_message_status(data)
        else:
            logger.warning(f"Unknown event type received: {event_type}")
            
        event_processing_duration.labels(event_type=event_type).observe(time.time() - t_start)
    except Exception as e:
        logger.error(f"Failed to handle event payload {payload_str}: {e}", exc_info=True)


async def handle_message_created(data: dict):
    message_id = data["message_id"]
    conversation_id = data["conversation_id"]
    recipient_user_id = uuid.UUID(data["recipient_user_id"])
    sender_user_id = uuid.UUID(data["sender_user_id"])
    
    # 1. Determine if recipient has active local WebSocket connection
    is_recipient_connected = recipient_user_id in manager.active_connections
    
    # 2. If connected locally, try to set status to DELIVERED in PostgreSQL using a safe update
    if is_recipient_connected:
        db_updated = False
        try:
            async with SessionLocal() as db:
                stmt = (
                    update(Message)
                    .where(Message.id == uuid.UUID(message_id))
                    .where(Message.status == "SENT")
                    .values(status="DELIVERED")
                )
                res = await db.execute(stmt)
                await db.commit()
                if res.rowcount == 1:
                    db_updated = True
                    logger.info(f"Transitioned message {message_id} to DELIVERED status in DB")
                    # Emit a status event to notify the sender
                    await publish_message_status(message_id, conversation_id, str(recipient_user_id), "DELIVERED")
        except Exception as db_err:
            logger.error(f"Failed to update message status to DELIVERED in DB for message {message_id}: {db_err}")

        # Load message data to send over WebSockets
        try:
            async with SessionLocal() as db:
                msg_stmt = select(Message).where(Message.id == uuid.UUID(message_id))
                msg_res = await db.execute(msg_stmt)
                db_message = msg_res.scalars().first()
                if db_message:
                    payload = {
                        "event": "message",
                        "data": {
                            "id": str(db_message.id),
                            "conversation_id": str(db_message.conversation_id),
                            "sender_id": str(db_message.sender_id),
                            "content": db_message.content,
                            "message_type": db_message.message_type,
                            "status": db_message.status,
                            "created_at": db_message.created_at.isoformat(),
                            "updated_at": db_message.updated_at.isoformat()
                        }
                    }
                    await manager.send_to_user(recipient_user_id, payload)
                    websocket_delivery_total.inc()
        except Exception as we:
            websocket_delivery_failures_total.inc()
            logger.error(f"WebSocket delivery failed for user {recipient_user_id}: {we}")
    else:
        # If recipient is not connected locally, but sender is connected locally,
        # we can deliver the message payload to the sender so their device receives it.
        if sender_user_id in manager.active_connections:
            try:
                async with SessionLocal() as db:
                    msg_stmt = select(Message).where(Message.id == uuid.UUID(message_id))
                    msg_res = await db.execute(msg_stmt)
                    db_message = msg_res.scalars().first()
                    if db_message:
                        payload = {
                            "event": "message",
                            "data": {
                                "id": str(db_message.id),
                                "conversation_id": str(db_message.conversation_id),
                                "sender_id": str(db_message.sender_id),
                                "content": db_message.content,
                                "message_type": db_message.message_type,
                                "status": db_message.status,
                                "created_at": db_message.created_at.isoformat(),
                                "updated_at": db_message.updated_at.isoformat()
                            }
                        }
                        await manager.send_to_user(sender_user_id, payload)
                        websocket_delivery_total.inc()
            except Exception as we:
                logger.error(f"WebSocket delivery failed to sender {sender_user_id}: {we}")


async def handle_message_status(data: dict):
    message_id = data["message_id"]
    conversation_id = data["conversation_id"]
    recipient_user_id = uuid.UUID(data["recipient_user_id"])
    status = data["status"]
    
    # Notify conversation participants (specifically the sender) about status changes
    try:
        async with SessionLocal() as db:
            msg_stmt = select(Message).where(Message.id == uuid.UUID(message_id))
            msg_res = await db.execute(msg_stmt)
            db_message = msg_res.scalars().first()
            if db_message:
                payload = {
                    "event": "status_update",
                    "data": {
                        "message_id": message_id,
                        "status": status
                    }
                }
                participants = [db_message.sender_id, recipient_user_id]
                for user_id in participants:
                    if user_id in manager.active_connections:
                        try:
                            await manager.send_to_user(user_id, payload)
                            websocket_delivery_total.inc()
                        except Exception as we:
                            websocket_delivery_failures_total.inc()
                            logger.error(f"WebSocket status delivery failed for user {user_id}: {we}")
    except Exception as e:
        logger.error(f"Failed to handle message status event for message {message_id}: {e}")


async def start_subscriber(stop_event: asyncio.Event = None):
    """
    Subscribes to Redis Pub/Sub events with automatic reconnection.
    """
    logger.info("Starting Redis Pub/Sub subscriber task...")
    while stop_event is None or not stop_event.is_set():
        try:
            # Check health first
            is_healthy = await check_redis_health()
            if not is_healthy:
                raise ConnectionError("Redis server is unhealthy")

            pubsub = redis_client.pubsub()
            await pubsub.subscribe(EVENTS_CHANNEL)
            logger.info("Subscribed to Redis events channel successfully.")
            
            while stop_event is None or not stop_event.is_set():
                try:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message and message.get("type") == "message":
                        payload_str = message["data"]
                        if isinstance(payload_str, bytes):
                            payload_str = payload_str.decode("utf-8")
                        await handle_event(payload_str)
                    else:
                        await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Error reading message from pubsub: {e}")
                    break  # Break out to reconnect
                    
            await pubsub.unsubscribe(EVENTS_CHANNEL)
            await pubsub.close()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Redis Pub/Sub subscriber connection failed: {e}. Retrying in 3s...")
            await asyncio.sleep(3.0)
    logger.info("Stopped Redis Pub/Sub subscriber task.")
