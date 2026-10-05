import asyncio
import json
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from app.events.schemas import MessageCreatedEvent, MessageStatusEvent
from app.events.publisher import publish_message_created, publish_message_status
from app.events.subscriber import handle_event
from app.models.message import Message
from app.models.conversation import Conversation, ConversationParticipant
from app.websocket.connection_manager import manager
from fastapi import WebSocket
from sqlalchemy import select

# Dummy WebSocket mock
class DummyWebSocket:
    def __init__(self):
        self.sent_messages = []
        self.accepted = False
        self.closed = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, data):
        self.sent_messages.append(data)

    async def close(self, code=1000):
        self.closed = True


@pytest.mark.asyncio
async def test_event_schema_validation():
    # Test message.created schema
    created_event = MessageCreatedEvent(
        timestamp=123456.78,
        message_id="msg-1",
        conversation_id="conv-1",
        recipient_user_id="user-2",
        sender_user_id="user-1"
    )
    data = created_event.model_dump()
    assert data["event_type"] == "message.created"
    assert data["message_id"] == "msg-1"
    assert data["version"] == 1

    # Test message.status schema
    status_event = MessageStatusEvent(
        timestamp=123456.78,
        message_id="msg-1",
        conversation_id="conv-1",
        recipient_user_id="user-2",
        status="DELIVERED"
    )
    data2 = status_event.model_dump()
    assert data2["event_type"] == "message.status"
    assert data2["status"] == "DELIVERED"


@pytest.mark.asyncio
async def test_pubsub_publish(mock_redis_injection):
    mock_r = mock_redis_injection

    # Publish message created
    await publish_message_created(
        message_id="msg-123",
        conversation_id="conv-123",
        recipient_user_id="recipient-123",
        sender_user_id="sender-123"
    )
    assert len(mock_r.event_queue) == 1
    event = json.loads(mock_r.event_queue[0]["data"])
    assert event["event_type"] == "message.created"
    assert event["message_id"] == "msg-123"

    # Publish message status
    await publish_message_status(
        message_id="msg-123",
        conversation_id="conv-123",
        recipient_user_id="recipient-123",
        status="READ"
    )
    assert len(mock_r.event_queue) == 2
    event2 = json.loads(mock_r.event_queue[1]["data"])
    assert event2["event_type"] == "message.status"
    assert event2["status"] == "READ"


@pytest.mark.asyncio
async def test_subscriber_message_routing_to_connected_user(db, mock_redis_injection):
    # Setup database entities
    conversation_id = uuid.uuid4()
    recipient_id = uuid.uuid4()
    sender_id = uuid.uuid4()

    # Add message
    msg = Message(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        sender_id=sender_id,
        content="Test Pub/Sub delivery",
        message_type="TEXT",
        status="SENT"
    )
    db.add(msg)
    await db.commit()

    # Simulate WebSocket connection for recipient user
    ws = DummyWebSocket()
    await manager.connect(recipient_id, ws)

    # Construct event payload
    payload = {
        "event_type": "message.created",
        "version": 1,
        "timestamp": 123456.0,
        "message_id": str(msg.id),
        "conversation_id": str(conversation_id),
        "recipient_user_id": str(recipient_id),
        "sender_user_id": str(sender_id)
    }

    # Dispatch event processing
    await handle_event(json.dumps(payload))

    # Verify message status transitioned to DELIVERED in database
    await db.refresh(msg)
    assert msg.status == "DELIVERED"

    # Verify recipient received message via WebSocket
    assert len(ws.sent_messages) == 1
    assert ws.sent_messages[0]["event"] == "message"
    assert ws.sent_messages[0]["data"]["content"] == "Test Pub/Sub delivery"
    assert ws.sent_messages[0]["data"]["status"] == "DELIVERED"

    # Clean up connection manager
    manager.disconnect(recipient_id, ws)


@pytest.mark.asyncio
async def test_subscriber_ignores_unrelated_events(db):
    recipient_id = uuid.uuid4()
    sender_id = uuid.uuid4()

    # Simulate WebSocket connection for recipient user
    ws = DummyWebSocket()
    await manager.connect(recipient_id, ws)

    # Construct event payload targeted at a different recipient
    payload = {
        "event_type": "message.created",
        "version": 1,
        "timestamp": 123456.0,
        "message_id": str(uuid.uuid4()),
        "conversation_id": str(uuid.uuid4()),
        "recipient_user_id": str(uuid.uuid4()),  # Unconnected recipient
        "sender_user_id": str(sender_id)
    }

    # Dispatch event
    await handle_event(json.dumps(payload))

    # Verify WS did not receive anything
    assert len(ws.sent_messages) == 0

    # Clean up connection manager
    manager.disconnect(recipient_id, ws)
