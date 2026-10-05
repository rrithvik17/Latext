import uuid
from pydantic import BaseModel, Field

class BaseEvent(BaseModel):
    event_type: str
    version: int = 1
    timestamp: float

class MessageCreatedEvent(BaseEvent):
    event_type: str = "message.created"
    message_id: str
    conversation_id: str
    recipient_user_id: str
    sender_user_id: str

class MessageStatusEvent(BaseEvent):
    event_type: str = "message.status"
    message_id: str
    conversation_id: str
    recipient_user_id: str
    status: str
