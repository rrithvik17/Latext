import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class ScheduledMessageBase(BaseModel):
    content: str = Field(..., min_length=1)
    message_type: str = "TEXT"
    timezone: str = Field(..., min_length=1)


class ScheduledMessageCreate(ScheduledMessageBase):
    conversation_id: uuid.UUID
    scheduled_at: datetime  # Naive local datetime representation

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Message content cannot be empty")
        return v


class ScheduledMessageUpdate(BaseModel):
    content: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    timezone: Optional[str] = None

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and (not v or not v.strip()):
            raise ValueError("Message content cannot be empty")
        return v


class ScheduledMessageOut(ScheduledMessageBase):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_id: uuid.UUID
    scheduled_at_utc: datetime
    status: str  # SCHEDULED, PROCESSING, SENT, CANCELLED, FAILED
    created_at: datetime
    updated_at: datetime
    processing_started_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    attempt_count: int

    class Config:
        from_attributes = True
