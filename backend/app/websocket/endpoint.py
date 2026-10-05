import json
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from jose import jwt, JWTError
from sqlalchemy import and_, select, update
from sqlalchemy.sql import func

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.conversation import Conversation, ConversationParticipant
from app.models.message import Message
from app.models.user import User
from app.websocket.connection_manager import manager

router = APIRouter(tags=["websocket"])


async def get_ws_user(token: str) -> User:
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        user_id = payload.get("sub")
        if not user_id:
            return None
        import uuid
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            return None
        async with SessionLocal() as db:
            result = await db.execute(select(User).where(User.id == user_uuid))
            return result.scalars().first()
    except (JWTError, ValueError):
        return None


@router.websocket("/ws/{conversation_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    conversation_id: uuid.UUID,
    token: str = Query(...)
):
    # Verify user from token in query parameter
    user = await get_ws_user(token)
    if not user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Check conversation membership
    async with SessionLocal() as db:
        member_stmt = select(ConversationParticipant).where(
            and_(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id == user.id
            )
        )
        member_res = await db.execute(member_stmt)
        is_member = member_res.scalars().first() is not None
        if not is_member:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Fetch all participant IDs
        part_stmt = select(ConversationParticipant.user_id).where(
            ConversationParticipant.conversation_id == conversation_id
        )
        part_res = await db.execute(part_stmt)
        participant_ids = part_res.scalars().all()

    # Accept connection and add to manager
    await manager.connect(user.id, websocket)

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            event = payload.get("event")

            if event == "message":
                msg_data = payload.get("data", {})
                content = msg_data.get("content", "")
                if not content or not content.strip():
                    continue

                async with SessionLocal() as db:
                    # Persist message as SENT
                    db_message = Message(
                        conversation_id=conversation_id,
                        sender_id=user.id,
                        content=content,
                        message_type=msg_data.get("message_type", "TEXT"),
                        status="SENT"
                    )
                    db.add(db_message)

                    # Update conversation updated_at
                    conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
                    conv_res = await db.execute(conv_stmt)
                    conversation = conv_res.scalars().first()
                    if conversation:
                        conversation.updated_at = func.now()

                    await db.commit()
                    await db.refresh(db_message)

                    # Publish message.created event to Redis Pub/Sub
                    recipient_id = next((pid for pid in participant_ids if pid != user.id), None)
                    if recipient_id:
                        from app.events.publisher import publish_message_created
                        await publish_message_created(
                            message_id=str(db_message.id),
                            conversation_id=str(conversation_id),
                            recipient_user_id=str(recipient_id),
                            sender_user_id=str(user.id)
                        )

            elif event == "read":
                msg_data = payload.get("data", {})
                message_ids = msg_data.get("message_ids", [])
                if not message_ids:
                    continue

                uuids = []
                for mid in message_ids:
                    try:
                        uuids.append(uuid.UUID(mid))
                    except ValueError:
                        continue

                if not uuids:
                    continue

                async with SessionLocal() as db:
                    # Update status to READ (excluding sender's own messages)
                    stmt = (
                        update(Message)
                        .where(
                            and_(
                                Message.id.in_(uuids),
                                Message.conversation_id == conversation_id,
                                Message.sender_id != user.id
                            )
                        )
                        .values(status="READ")
                    )
                    await db.execute(stmt)
                    await db.commit()

                # Broadcast status update for each read message to Redis Pub/Sub
                recipient_id = next((pid for pid in participant_ids if pid != user.id), None)
                if recipient_id:
                    from app.events.publisher import publish_message_status
                    for mid in message_ids:
                        await publish_message_status(
                            message_id=mid,
                            conversation_id=str(conversation_id),
                            recipient_user_id=str(recipient_id),
                            status="READ"
                        )

    except WebSocketDisconnect:
        manager.disconnect(user.id, websocket)
    except Exception:
        manager.disconnect(user.id, websocket)
