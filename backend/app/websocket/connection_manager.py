import uuid
from typing import Dict, List
from fastapi import WebSocket


class ConnectionManager:
    """
    In-memory connection manager tracking active WebSocket connections per user.
    
    WARNING:
    This manager stores state in application memory, which means it is NOT
    horizontally scalable. If multiple instances of the backend run behind a
    load balancer, clients connected to different instances will not receive
    each other's messages in real-time.
    
    This will be replaced in Phase 2 with a distributed broker (Redis Pub/Sub).
    """

    def __init__(self):
        # Maps user_id -> list of active WebSocket connections (allows multiple devices/tabs per user)
        self.active_connections: Dict[uuid.UUID, List[WebSocket]] = {}

    async def connect(self, user_id: uuid.UUID, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, user_id: uuid.UUID, websocket: WebSocket):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_to_user(self, user_id: uuid.UUID, message: dict):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    # Connection might be dead, it will be cleaned up on disconnect/exception
                    pass

    async def broadcast_to_conversation(
        self,
        participant_ids: List[uuid.UUID],
        message: dict
    ):
        """
        Sends a JSON payload to all active connections belonging to conversation participants.
        """
        for user_id in participant_ids:
            await self.send_to_user(user_id, message)


# Global singleton manager
manager = ConnectionManager()
