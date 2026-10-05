import uuid
from fastapi.testclient import TestClient
from app.main import app


def test_websocket_messaging():
    with TestClient(app) as client:
        # Register User A
        reg_a = client.post("/auth/register", json={
            "username": "wsa",
            "email": "wsa@example.com",
            "display_name": "WS User A",
            "password": "password"
        }).json()

        # Register User B
        reg_b = client.post("/auth/register", json={
            "username": "wsb",
            "email": "wsb@example.com",
            "display_name": "WS User B",
            "password": "password"
        }).json()

        # Login User A to get token
        login_a = client.post("/auth/login", json={
            "email": "wsa@example.com",
            "password": "password"
        }).json()
        token_a = login_a["access_token"]

        # Create conversation
        conv = client.post(
            "/conversations",
            json={"recipient_id": reg_b["id"]},
            headers={"Authorization": f"Bearer {token_a}"}
        ).json()
        conv_id = conv["id"]

        # Connect to WebSocket as User A and send message
        with client.websocket_connect(f"/ws/{conv_id}?token={token_a}") as websocket:
            websocket.send_json({
                "event": "message",
                "data": {
                    "content": "Hello via WebSocket!"
                }
            })

        # Verify message was persisted in database and readable via API
        res = client.get(
            f"/conversations/{conv_id}/messages",
            headers={"Authorization": f"Bearer {token_a}"}
        )
        assert res.status_code == 200
        msgs = res.json()
        assert len(msgs) == 1
        assert msgs[0]["content"] == "Hello via WebSocket!"
        assert msgs[0]["sender_id"] == reg_a["id"]
        assert msgs[0]["status"] == "SENT"


