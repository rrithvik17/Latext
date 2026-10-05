import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, UUID, Integer, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.models.base import Base

class OutboxEvent(Base):
    __tablename__ = "message_outbox"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )
    event_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False
    )
    aggregate_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True
    )
    payload: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False
    )
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    failure_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    __table_args__ = (
        Index(
            "ix_message_outbox_unpublished",
            "created_at",
            postgresql_where=text("published_at IS NULL")
        ),
    )
