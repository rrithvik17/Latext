import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.timezone import validate_and_convert_timezone
from app.models.scheduled_message import ScheduledMessage
from app.models.user import User
from app.api.routes.conversations import check_membership
from app.schemas.scheduled_message import (
    ScheduledMessageCreate,
    ScheduledMessageOut,
    ScheduledMessageUpdate,
)

router = APIRouter(prefix="/scheduled-messages", tags=["scheduled-messages"])


@router.post("", response_model=ScheduledMessageOut, status_code=status.HTTP_201_CREATED)
async def create_scheduled_message(
    payload: ScheduledMessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify conversation membership
    is_member = await check_membership(payload.conversation_id, current_user.id, db)
    if not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not belong to this conversation"
        )

    # Validate timezone and convert to UTC
    try:
        scheduled_at_utc = validate_and_convert_timezone(payload.scheduled_at, payload.timezone)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    # Check that scheduled_at_utc is in the future
    if scheduled_at_utc <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Scheduled time must be in the future"
        )

    # Create scheduled message record
    db_scheduled = ScheduledMessage(
        conversation_id=payload.conversation_id,
        sender_id=current_user.id,
        content=payload.content,
        message_type=payload.message_type,
        scheduled_at_utc=scheduled_at_utc,
        timezone=payload.timezone,
        status="SCHEDULED"
    )
    db.add(db_scheduled)
    await db.commit()
    await db.refresh(db_scheduled)
    return db_scheduled


@router.get("", response_model=List[ScheduledMessageOut])
async def list_scheduled_messages(
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ScheduledMessage).where(ScheduledMessage.sender_id == current_user.id)
    if status_filter:
        stmt = stmt.where(ScheduledMessage.status == status_filter)
    stmt = stmt.order_by(ScheduledMessage.scheduled_at_utc.asc())
    
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{id}", response_model=ScheduledMessageOut)
async def get_scheduled_message(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ScheduledMessage).where(
        and_(ScheduledMessage.id == id, ScheduledMessage.sender_id == current_user.id)
    )
    result = await db.execute(stmt)
    db_scheduled = result.scalars().first()
    if not db_scheduled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled message not found"
        )
    return db_scheduled


@router.patch("/{id}", response_model=ScheduledMessageOut)
async def update_scheduled_message(
    id: uuid.UUID,
    payload: ScheduledMessageUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ScheduledMessage).where(
        and_(ScheduledMessage.id == id, ScheduledMessage.sender_id == current_user.id)
    )
    result = await db.execute(stmt)
    db_scheduled = result.scalars().first()
    if not db_scheduled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled message not found"
        )

    # Reject edit if not in SCHEDULED status
    if db_scheduled.status != "SCHEDULED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot edit scheduled message with status: {db_scheduled.status}"
        )

    # Update content if provided
    if payload.content is not None:
        db_scheduled.content = payload.content

    # If updating scheduled_at or timezone, validate the new values
    new_dt = payload.scheduled_at or db_scheduled.scheduled_at_utc
    new_tz = payload.timezone or db_scheduled.timezone

    if payload.scheduled_at is not None or payload.timezone is not None:
        try:
            # Reconverts and checks DST boundaries
            scheduled_at_utc = validate_and_convert_timezone(new_dt, new_tz)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )

        if scheduled_at_utc <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Scheduled time must be in the future"
            )

        db_scheduled.scheduled_at_utc = scheduled_at_utc
        if payload.timezone is not None:
            db_scheduled.timezone = payload.timezone

    db_scheduled.updated_at = func.now()
    await db.commit()
    await db.refresh(db_scheduled)
    return db_scheduled


@router.delete("/{id}", response_model=ScheduledMessageOut)
async def cancel_scheduled_message(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Lock the row using FOR UPDATE to prevent race condition with worker claiming it
    stmt = (
        select(ScheduledMessage)
        .where(and_(ScheduledMessage.id == id, ScheduledMessage.sender_id == current_user.id))
        .with_for_update()
    )
    result = await db.execute(stmt)
    db_scheduled = result.scalars().first()
    if not db_scheduled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled message not found"
        )

    # Only cancel if still SCHEDULED
    if db_scheduled.status != "SCHEDULED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel scheduled message in status: {db_scheduled.status}"
        )

    db_scheduled.status = "CANCELLED"
    db_scheduled.cancelled_at = func.now()
    db_scheduled.updated_at = func.now()
    await db.commit()
    await db.refresh(db_scheduled)
    return db_scheduled
