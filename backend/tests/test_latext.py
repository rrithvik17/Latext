import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_auth_and_user_flows(client: AsyncClient):
    # 1. Registration
    reg_data_a = {
        "username": "usera",
        "email": "usera@example.com",
        "display_name": "User A",
        "password": "password123"
    }
    response = await client.post("/auth/register", json=reg_data_a)
    assert response.status_code == 201
    user_a = response.json()
    assert user_a["username"] == "usera"
    assert "password_hash" not in user_a

    # 2. Duplicate registration (username)
    response = await client.post("/auth/register", json=reg_data_a)
    assert response.status_code == 400
    assert "Username already registered" in response.json()["detail"]

    # Duplicate registration (email)
    reg_data_a_dup_email = {
        "username": "usera_new",
        "email": "usera@example.com",
        "display_name": "User A New",
        "password": "password123"
    }
    response = await client.post("/auth/register", json=reg_data_a_dup_email)
    assert response.status_code == 400
    assert "Email already registered" in response.json()["detail"]

    # Register User B
    reg_data_b = {
        "username": "userb",
        "email": "userb@example.com",
        "display_name": "User B",
        "password": "password123"
    }
    response = await client.post("/auth/register", json=reg_data_b)
    assert response.status_code == 201
    user_b = response.json()

    # 3. Login
    login_data = {"email": "usera@example.com", "password": "password123"}
    response = await client.post("/auth/login", json=login_data)
    assert response.status_code == 200
    token_data = response.json()
    assert "access_token" in token_data
    token_a = token_data["access_token"]

    # 4. Invalid login
    bad_login_data = {"email": "usera@example.com", "password": "wrongpassword"}
    response = await client.post("/auth/login", json=bad_login_data)
    assert response.status_code == 401

    # 5. Authenticated user retrieval
    headers_a = {"Authorization": f"Bearer {token_a}"}
    response = await client.get("/users/me", headers=headers_a)
    assert response.status_code == 200
    assert response.json()["username"] == "usera"

    # 6. Unauthorized access
    response = await client.get("/users/me")
    assert response.status_code == 401

    # 7. User search
    response = await client.get("/users/search?q=User", headers=headers_a)
    assert response.status_code == 200
    results = response.json()
    # Should find User B but exclude User A itself
    assert len(results) >= 1
    assert any(u["username"] == "userb" for u in results)
    assert not any(u["username"] == "usera" for u in results)

    # 8. Conversation creation
    conv_payload = {"recipient_id": user_b["id"]}
    response = await client.post("/conversations", json=conv_payload, headers=headers_a)
    assert response.status_code == 201
    conv = response.json()
    assert "id" in conv
    assert len(conv["participants"]) == 2

    # 9. Duplicate 1-to-1 conversation prevention (returns existing)
    response2 = await client.post("/conversations", json=conv_payload, headers=headers_a)
    assert response2.status_code == 201
    assert response2.json()["id"] == conv["id"]

    # 10. Conversation membership authorization
    # Register User C
    reg_data_c = {
        "username": "userc",
        "email": "userc@example.com",
        "display_name": "User C",
        "password": "password123"
    }
    response = await client.post("/auth/register", json=reg_data_c)
    user_c = response.json()

    # Login User C
    response = await client.post("/auth/login", json={"email": "userc@example.com", "password": "password123"})
    token_c = response.json()["access_token"]
    headers_c = {"Authorization": f"Bearer {token_c}"}

    # User C tries to view User A & B's conversation messages
    response = await client.get(f"/conversations/{conv['id']}/messages", headers=headers_c)
    assert response.status_code == 403

    # User C tries to send message to User A & B's conversation
    response = await client.post(f"/conversations/{conv['id']}/messages", json={"content": "spam"}, headers=headers_c)
    assert response.status_code == 403

    # 11. Message creation
    msg_payload = {"content": "Hey, this is our first message!"}
    response = await client.post(f"/conversations/{conv['id']}/messages", json=msg_payload, headers=headers_a)
    assert response.status_code == 201
    msg = response.json()
    assert msg["content"] == "Hey, this is our first message!"
    assert msg["sender_id"] == user_a["id"]
    assert msg["status"] == "SENT"

    # 12. Message retrieval
    response = await client.get(f"/conversations/{conv['id']}/messages", headers=headers_a)
    assert response.status_code == 200
    messages = response.json()
    assert len(messages) == 1
    assert messages[0]["content"] == "Hey, this is our first message!"

    # 13. Unauthorized message access
    response = await client.get(f"/conversations/{conv['id']}/messages")
    assert response.status_code == 401
