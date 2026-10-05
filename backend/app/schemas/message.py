import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class MessageBase(BaseModel):
    content: str
    message_type: str = "TEXT"


class MessageCreate(MessageBase):
    pass


class MessageOut(MessageBase):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_id: uuid.UUID
    status: str  # SENT, DELIVERED, READ
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
