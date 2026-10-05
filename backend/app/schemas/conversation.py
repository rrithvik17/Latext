import uuid
from datetime import datetime
from typing import List
from pydantic import BaseModel

from app.schemas.user import UserOut


class ConversationParticipantOut(BaseModel):
    conversation_id: uuid.UUID
    user_id: uuid.UUID
    joined_at: datetime
    user: UserOut

    class Config:
        from_attributes = True


class ConversationOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    participants: List[ConversationParticipantOut]

    class Config:
        from_attributes = True


class ConversationCreate(BaseModel):
    recipient_id: uuid.UUID
