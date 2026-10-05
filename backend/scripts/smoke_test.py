import asyncio
import json
import logging
import sys
import time
import uuid
import httpx
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] smoke: %(message)s")
logger = logging.getLogger("smoke")

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"

async def run_smoke_tests():
    suffix = uuid.uuid4().hex[:6]
    user_a_username = f"smoke_a_{suffix}"
    user_b_username = f"smoke_b_{suffix}"
    
    async with httpx.AsyncClient() as client:
        # 1. Verify health & readiness
        logger.info("Verifying /health endpoint...")
        resp = await client.get(f"{BASE_URL}/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"
        
        logger.info("Verifying /ready endpoint...")
        resp = await client.get(f"{BASE_URL}/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"

        # 2. Registration
        logger.info(f"Registering User A ({user_a_username}) and User B ({user_b_username})...")
        resp_a = await client.post(f"{BASE_URL}/auth/register", json={
            "username": user_a_username,
            "email": f"{user_a_username}@example.com",
            "display_name": "Smoke User A",
            "password": "password123"
        })
        assert resp_a.status_code == 201
        user_a = resp_a.json()

        resp_b = await client.post(f"{BASE_URL}/auth/register", json={
            "username": user_b_username,
            "email": f"{user_b_username}@example.com",
            "display_name": "Smoke User B",
            "password": "password123"
        })
        assert resp_b.status_code == 201
        user_b = resp_b.json()

        # 3. Login
        logger.info("Logging in to get JWT access tokens...")
        login_a = await client.post(f"{BASE_URL}/auth/login", json={
            "email": f"{user_a_username}@example.com",
            "password": "password123"
        })
        assert login_a.status_code == 200
        token_a = login_a.json()["access_token"]
        headers_a = {"Authorization": f"Bearer {token_a}"}

        login_b = await client.post(f"{BASE_URL}/auth/login", json={
            "email": f"{user_b_username}@example.com",
            "password": "password123"
        })
        assert login_b.status_code == 200
        token_b = login_b.json()["access_token"]
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # 4. Conversation creation
        logger.info("Creating a conversation between User A and User B...")
        conv_resp = await client.post(
            f"{BASE_URL}/conversations",
            json={"recipient_id": user_b["id"]},
            headers=headers_a
        )
        assert conv_resp.status_code == 201
        conversation = conv_resp.json()
        conv_id = conversation["id"]

        # 5. Connect WebSocket for User B
        ws_uri = f"{WS_URL}/ws/{conv_id}?token={token_b}"
        logger.info(f"Connecting to WebSocket for User B at {ws_uri}...")
        
        async with websockets.connect(ws_uri) as ws:
            # 6. Send REST message from User A to User B
            logger.info("Sending message from User A via REST...")
            msg_payload = {"content": "Hello via REST smoke test!"}
            send_resp = await client.post(
                f"{BASE_URL}/conversations/{conv_id}/messages",
                json=msg_payload,
                headers=headers_a
            )
            assert send_resp.status_code in (200, 201)
            sent_msg = send_resp.json()
            assert sent_msg["content"] == "Hello via REST smoke test!"

            # 7. Verify WebSocket receives the event
            logger.info("Awaiting message event on User B WebSocket...")
            ws_frame = await asyncio.wait_for(ws.recv(), timeout=5.0)
            ws_event = json.loads(ws_frame)
            logger.info(f"WebSocket received frame: {ws_event}")
            
            assert ws_event["event"] == "message"
            assert ws_event["data"]["id"] == sent_msg["id"]
            assert ws_event["data"]["content"] == "Hello via REST smoke test!"
            
            # 8. Retrieve message history and verify DELIVERED status
            logger.info("Retrieving conversation history to check delivery status...")
            history_resp = await client.get(
                f"{BASE_URL}/conversations/{conv_id}/messages",
                headers=headers_a
            )
            assert history_resp.status_code == 200
            messages = history_resp.json()
            assert len(messages) >= 1
            
            # Find our sent message and check status is DELIVERED (since WS consumed it)
            db_msg = next((m for m in messages if m["id"] == sent_msg["id"]), None)
            assert db_msg is not None
            assert db_msg["status"] in ("DELIVERED", "READ")

            # 9. Test Scheduled Message
            logger.info("Scheduling a message for 2 seconds in the future...")
            # Target 2 seconds in the future
            target_time = (datetime_now_utc() + timedelta_seconds(2)).isoformat()
            sched_payload = {
                "conversation_id": conv_id,
                "content": "Hello scheduled smoke test!",
                "scheduled_at": target_time,
                "timezone": "UTC"
            }
            sched_resp = await client.post(
                f"{BASE_URL}/scheduled-messages",
                json=sched_payload,
                headers=headers_a
            )
            assert sched_resp.status_code == 201
            sched_msg = sched_resp.json()
            assert sched_msg["status"] == "SCHEDULED"

            logger.info("Awaiting scheduled message delivery...")
            # Await delivery event on WebSocket, filtering out other events (like status updates)
            start_time = time.time()
            ws_event2 = None
            while time.time() - start_time < 12.0:
                ws_frame2 = await asyncio.wait_for(ws.recv(), timeout=12.0)
                ws_event2 = json.loads(ws_frame2)
                logger.info(f"WebSocket received frame: {ws_event2}")
                if ws_event2.get("event") == "message":
                    break
            assert ws_event2 is not None
            assert ws_event2["event"] == "message"
            assert ws_event2["data"]["content"] == "Hello scheduled smoke test!"

    logger.info("=========================================")
    logger.info("  ALL SMOKE TESTS PASSED SUCCESSFULLY!   ")
    logger.info("=========================================")

def datetime_now_utc():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)

def timedelta_seconds(s):
    from datetime import timedelta
    return timedelta(seconds=s)

if __name__ == "__main__":
    asyncio.run(run_smoke_tests())
