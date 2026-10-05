import asyncio
import json
import logging
import sys
import httpx
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] verify: %(message)s")
logger = logging.getLogger("verify")

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"


async def main():
    async with httpx.AsyncClient() as client:
        import uuid
        suffix = uuid.uuid4().hex[:8]
        u1_username = f"diag_user1_{suffix}"
        u1_email = f"diag_user1_{suffix}@example.com"
        u2_username = f"diag_user2_{suffix}"
        u2_email = f"diag_user2_{suffix}@example.com"

        # 1. Register User 1
        logger.info("Registering diagnostic users...")
        u1_payload = {
            "username": u1_username,
            "email": u1_email,
            "display_name": "Diag User 1",
            "password": "password123"
        }
        await client.post(f"{BASE_URL}/auth/register", json=u1_payload)

        # Register User 2
        u2_payload = {
            "username": u2_username,
            "email": u2_email,
            "display_name": "Diag User 2",
            "password": "password123"
        }
        u2_res = await client.post(f"{BASE_URL}/auth/register", json=u2_payload)
        user2_id = u2_res.json()["id"]

        # 2. Login User 1
        logger.info("Logging in User 1...")
        login_res = await client.post(
            f"{BASE_URL}/auth/login",
            json={"email": u1_email, "password": "password123"}
        )
        if login_res.status_code != 200:
            logger.error(f"Login failed: {login_res.text}")
            sys.exit(1)
        
        token1 = login_res.json()["access_token"]
        headers1 = {"Authorization": f"Bearer {token1}"}

        # Login User 2
        login_res2 = await client.post(
            f"{BASE_URL}/auth/login",
            json={"email": u2_email, "password": "password123"}
        )
        token2 = login_res2.json()["access_token"]

        # 3. Create Conversation
        logger.info("Creating conversation between User 1 and User 2...")
        conv_res = await client.post(
            f"{BASE_URL}/conversations",
            json={"recipient_id": user2_id},
            headers=headers1
        )
        conv = conv_res.json()
        conv_id = conv["id"]

        # 4. Create a Message via API
        logger.info("Sending message to conversation...")
        msg_res = await client.post(
            f"{BASE_URL}/conversations/{conv_id}/messages",
            json={"content": "Diagnostic ping!", "message_type": "TEXT"},
            headers=headers1
        )
        msg = msg_res.json()
        msg_id = msg["id"]

        # 5. Connect User 2 to WebSocket
        logger.info("Opening WebSocket connection for User 2...")
        ws_uri = f"{WS_URL}/ws/{conv_id}?token={token2}"
        
        async with websockets.connect(ws_uri) as ws:
            # 6. Trigger backend internal broadcast
            logger.info("Triggering internal WebSocket broadcast endpoint...")
            import time
            start_post = time.time()
            
            # The worker calls the internal broadcast POST route
            broadcast_res = await client.post(
                f"{BASE_URL}/conversations/internal/broadcast",
                json={"message_id": msg_id}
            )
            
            post_duration = time.time() - start_post
            logger.info(f"Broadcast POST response status: {broadcast_res.status_code}")
            logger.info(f"Broadcast POST took: {post_duration:.4f}s")
            
            if broadcast_res.status_code != 200:
                logger.error(f"Broadcast failed: {broadcast_res.text}")
                sys.exit(1)
                
            res_data = broadcast_res.json()
            logger.info(f"Broadcast Timing Details: t10={res_data.get('t10')}, t11={res_data.get('t11')}")

            # 7. Listen for real-time WebSocket packet
            logger.info("Listening on WebSocket for broadcast packet...")
            try:
                msg_frame = await asyncio.wait_for(ws.recv(), timeout=2.0)
                frame_data = json.loads(msg_frame)
                logger.info(f"Received WebSocket message frame: {frame_data}")
                assert frame_data["event"] == "message"
                assert frame_data["data"]["id"] == msg_id
                logger.info("SUCCESS: Test message successfully reached the WebSocket layer!")
            except asyncio.TimeoutError:
                logger.error("FAILURE: Timeout waiting for WebSocket message frame!")
                sys.exit(1)

        # 8. Assert no artificial timeouts occurred (under 500ms is expected on active connections)
        if post_duration > 0.5:
            logger.warning(f"Warning: Broadcast call duration ({post_duration:.3f}s) is slow (>0.5s)!")
            sys.exit(1)
        else:
            logger.info(f"Confirming no artificial connection delays. Duration: {post_duration * 1000:.2f} ms")


if __name__ == "__main__":
    asyncio.run(main())
