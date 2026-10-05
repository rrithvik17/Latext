import uuid
import time
from typing import List
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.conversation import Conversation, ConversationParticipant
from app.models.message import Message
from app.models.user import User
from app.schemas.conversation import ConversationCreate, ConversationOut
from app.schemas.message import MessageCreate, MessageOut
from app.websocket.connection_manager import manager

router = APIRouter(prefix="/conversations", tags=["conversations"])


async def check_membership(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession
) -> bool:
    """Helper to check if a user belongs to a conversation."""
    stmt = select(ConversationParticipant).where(
        and_(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == user_id
        )
    )
    result = await db.execute(stmt)
    return result.scalars().first() is not None


@router.get("", response_model=List[ConversationOut])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Fetch conversations where current user is a participant
    stmt = (
        select(Conversation)
        .join(ConversationParticipant)
        .where(ConversationParticipant.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
    )
    result = await db.execute(stmt)
    conversations = result.scalars().all()
    return conversations


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    recipient_id = payload.recipient_id

    if current_user.id == recipient_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot start a conversation with yourself"
        )

    # Verify recipient exists
    recipient_stmt = select(User).where(User.id == recipient_id)
    recipient_result = await db.execute(recipient_stmt)
    recipient = recipient_result.scalars().first()
    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recipient user not found"
        )

    # Check if a 1-to-1 conversation already exists
    # Find conversation IDs that have BOTH participants
    exist_stmt = (
        select(ConversationParticipant.conversation_id)
        .where(ConversationParticipant.user_id.in_([current_user.id, recipient_id]))
        .group_by(ConversationParticipant.conversation_id)
        .having(func.count(ConversationParticipant.conversation_id) == 2)
    )
    exist_result = await db.execute(exist_stmt)
    existing_conv_id = exist_result.scalars().first()

    if existing_conv_id:
        # Load and return the existing conversation
        full_stmt = select(Conversation).where(Conversation.id == existing_conv_id)
        full_result = await db.execute(full_stmt)
        return full_result.scalars().first()

    # Create new conversation
    conversation = Conversation()
    db.add(conversation)
    await db.flush()  # Gen ID

    # Add participants
    part_self = ConversationParticipant(
        conversation_id=conversation.id,
        user_id=current_user.id
    )
    part_other = ConversationParticipant(
        conversation_id=conversation.id,
        user_id=recipient_id
    )
    db.add_all([part_self, part_other])
    await db.commit()

    # Refresh and return
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation.id)
    )
    return result.scalars().first()


@router.get("/{conversation_id}/messages", response_model=List[MessageOut])
async def list_messages(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify authorization
    is_member = await check_membership(conversation_id, current_user.id, db)
    if not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not belong to this conversation"
        )

    # Fetch messages
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return messages


@router.post("/{conversation_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def send_message(
    conversation_id: uuid.UUID,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify authorization
    is_member = await check_membership(conversation_id, current_user.id, db)
    if not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not belong to this conversation"
        )

    # Generate message ID explicitly
    msg_id = uuid.uuid4()
    
    # Create message
    db_message = Message(
        id=msg_id,
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content=payload.content,
        message_type=payload.message_type,
        status="SENT"
    )
    db.add(db_message)

    # Update conversation updated_at
    conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv_result = await db.execute(conv_stmt)
    conversation = conv_result.scalars().first()
    if conversation:
        conversation.updated_at = func.now()

    # Fetch participant IDs to identify the recipient
    participant_stmt = select(ConversationParticipant.user_id).where(
        ConversationParticipant.conversation_id == conversation_id
    )
    part_res = await db.execute(participant_stmt)
    participant_ids = part_res.scalars().all()
    recipient_id = next((pid for pid in participant_ids if pid != current_user.id), None)

    # Insert Outbox Event
    if recipient_id:
        import json
        import time
        from app.models.outbox import OutboxEvent
        
        event_payload = {
            "event_type": "message.created",
            "version": 1,
            "timestamp": time.time(),
            "message_id": str(msg_id),
            "conversation_id": str(conversation_id),
            "recipient_user_id": str(recipient_id),
            "sender_user_id": str(current_user.id)
        }
        
        outbox_event = OutboxEvent(
            event_type="message.created",
            event_version=1,
            aggregate_id=str(msg_id),
            payload=json.dumps(event_payload)
        )
        db.add(outbox_event)

    await db.commit()
    await db.refresh(db_message)

    # Trigger outbox publisher to deliver immediately in background
    if recipient_id:
        from app.events.outbox_publisher import trigger_outbox_publish
        trigger_outbox_publish()

    return db_message


class InternalBroadcastPayload(BaseModel):
    message_id: uuid.UUID


@router.post("/internal/broadcast", status_code=status.HTTP_200_OK, deprecated=True)
async def internal_broadcast(
    payload: InternalBroadcastPayload,
    db: AsyncSession = Depends(get_db)
):
    # Fetch the message
    msg_stmt = select(Message).where(Message.id == payload.message_id)
    msg_res = await db.execute(msg_stmt)
    db_message = msg_res.scalars().first()
    if not db_message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )
        
    # Fetch participants
    participant_stmt = select(ConversationParticipant.user_id).where(
        ConversationParticipant.conversation_id == db_message.conversation_id
    )
    part_res = await db.execute(participant_stmt)
    participant_ids = part_res.scalars().all()
    
    # Check if recipient is online
    recipient_id = next((pid for pid in participant_ids if pid != db_message.sender_id), None)
    is_recipient_online = recipient_id in manager.active_connections if recipient_id else False

    if is_recipient_online and db_message.status == "SENT":
        db_message.status = "DELIVERED"
        await db.commit()
        await db.refresh(db_message)

    start_route = time.time()
    # Format JSON payload
    ws_payload = {
        "event": "message",
        "data": {
            "id": str(db_message.id),
            "conversation_id": str(db_message.conversation_id),
            "sender_id": str(db_message.sender_id),
            "content": db_message.content,
            "message_type": db_message.message_type,
            "status": db_message.status,
            "created_at": db_message.created_at.isoformat(),
            "updated_at": db_message.updated_at.isoformat(),
        }
    }
    t10 = time.time()
    await manager.broadcast_to_conversation(participant_ids, ws_payload)
    t11 = time.time()
    
    from app.queue.metrics import backend_internal_broadcast_latency, websocket_broadcast_latency
    websocket_broadcast_latency.observe(t11 - t10)
    backend_internal_broadcast_latency.observe(time.time() - start_route)

    return {
        "status": "broadcasted",
        "message_status": db_message.status,
        "t10": t10,
        "t11": t11
    }
