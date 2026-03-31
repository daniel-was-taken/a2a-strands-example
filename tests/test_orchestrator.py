# tests/test_orchestrator.py
"""Tests for the orchestrator conversation lifecycle."""


# ── Conversation CRUD ──────────────────────────────────────────────────────


def test_create_conversation(client):
    """POST /conversations should create an empty conversation."""
    resp = client.post("/conversations")
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"]
    assert data["title"] == "New conversation"
    assert data["status"] == "active"
    assert data["messages"] == []
    assert data["events"] == []


def test_list_conversations_empty(client):
    resp = client.get("/conversations")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_conversations_returns_summaries(client):
    """GET /conversations should return summaries without messages."""
    client.post("/conversations")
    resp = client.get("/conversations")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "New conversation"
    assert "messages" not in data[0]
    assert "events" not in data[0]


def test_get_conversation(client):
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    resp = client.get(f"/conversations/{conv_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == conv_id
    assert "messages" in resp.json()


def test_get_conversation_not_found(client):
    resp = client.get("/conversations/nonexistent")
    assert resp.status_code == 404


def test_delete_conversation(client):
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    resp = client.delete(f"/conversations/{conv_id}")
    assert resp.status_code == 204
    assert client.get(f"/conversations/{conv_id}").status_code == 404


def test_delete_conversation_not_found(client):
    resp = client.delete("/conversations/nonexistent")
    assert resp.status_code == 404


# ── Message sending ────────────────────────────────────────────────────────


def test_send_message(client):
    """Non-destructive message should get an agent response."""
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    resp = client.post(
        f"/conversations/{conv_id}/messages", json={"content": "Show all tables"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][0]["content"] == "Show all tables"
    assert data["messages"][1]["role"] == "agent"


def test_send_message_updates_title(client):
    """First message should set the conversation title."""
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    client.post(
        f"/conversations/{conv_id}/messages",
        json={"content": "Show all tables in the database"},
    )
    resp = client.get(f"/conversations/{conv_id}")
    assert resp.json()["title"] == "Show all tables in the database"


def test_send_message_title_truncated(client):
    """Long first message should be truncated to 50 chars in title."""
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    long_msg = "A" * 80
    client.post(f"/conversations/{conv_id}/messages", json={"content": long_msg})
    resp = client.get(f"/conversations/{conv_id}")
    title = resp.json()["title"]
    assert len(title) == 53  # 50 chars + "..."
    assert title.endswith("...")


def test_send_message_not_found(client):
    resp = client.post(
        "/conversations/nonexistent/messages", json={"content": "hello"}
    )
    assert resp.status_code == 404


def test_send_empty_message_returns_422(client):
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    resp = client.post(f"/conversations/{conv_id}/messages", json={"content": ""})
    assert resp.status_code == 422


def test_send_message_to_awaiting_returns_409(client_approve):
    """Cannot send messages while conversation is awaiting approval."""
    create_resp = client_approve.post("/conversations")
    conv_id = create_resp.json()["id"]
    client_approve.post(
        f"/conversations/{conv_id}/messages",
        json={"content": "delete from users where id = 5"},
    )
    resp = client_approve.post(
        f"/conversations/{conv_id}/messages", json={"content": "hello"}
    )
    assert resp.status_code == 409


def test_multi_turn_conversation(client):
    """Multiple messages should accumulate in the thread."""
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    client.post(
        f"/conversations/{conv_id}/messages", json={"content": "Show all tables"}
    )
    resp = client.post(
        f"/conversations/{conv_id}/messages", json={"content": "How many rows?"}
    )
    data = resp.json()
    assert len(data["messages"]) == 4  # 2 per turn


def test_agent_context_isolation(client):
    """Messages from conversation A must not leak into conversation B."""
    # Conversation A
    create_a = client.post("/conversations")
    conv_a_id = create_a.json()["id"]
    client.post(
        f"/conversations/{conv_a_id}/messages", json={"content": "Show all tables"}
    )

    # Conversation B
    create_b = client.post("/conversations")
    conv_b_id = create_b.json()["id"]
    resp = client.post(
        f"/conversations/{conv_b_id}/messages", json={"content": "Count employees"}
    )

    # Conv B should only have its own messages
    data = resp.json()
    assert len(data["messages"]) == 2
    assert data["messages"][0]["content"] == "Count employees"


# ── Destructive queries & approval ─────────────────────────────────────────


def test_destructive_message_recommended_reject(client):
    """Safety reviewer rejection should set awaiting_approval + recommended_reject."""
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    resp = client.post(
        f"/conversations/{conv_id}/messages",
        json={"content": "delete all employees"},
    )
    data = resp.json()
    assert data["status"] == "awaiting_approval"
    assert data["review_recommended_reject"] is True
    assert data["review_verdict"]
    assert data["pending_query"] == "delete all employees"


def test_destructive_message_pending_approval(client_approve):
    """Safety reviewer approval should set awaiting_approval without recommended_reject."""
    create_resp = client_approve.post("/conversations")
    conv_id = create_resp.json()["id"]
    resp = client_approve.post(
        f"/conversations/{conv_id}/messages",
        json={"content": "delete from users where id = 5"},
    )
    data = resp.json()
    assert data["status"] == "awaiting_approval"
    assert data["review_recommended_reject"] is False
    assert "APPROVE" in data["review_verdict"]
    assert data["approval_id"] is not None


def test_approve_conversation(client_approve):
    """Approving should execute the query and return to active."""
    create_resp = client_approve.post("/conversations")
    conv_id = create_resp.json()["id"]
    client_approve.post(
        f"/conversations/{conv_id}/messages",
        json={"content": "delete from users where id = 5"},
    )
    resp = client_approve.post(f"/conversations/{conv_id}/approve")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert data["approval_id"] is None
    assert data["pending_query"] is None
    assert any(m["role"] == "agent" and m["content"] != "" for m in data["messages"])


def test_reject_conversation(client_approve):
    """Rejecting should add rejection message and return to active."""
    create_resp = client_approve.post("/conversations")
    conv_id = create_resp.json()["id"]
    client_approve.post(
        f"/conversations/{conv_id}/messages",
        json={"content": "delete from users where id = 5"},
    )
    resp = client_approve.post(f"/conversations/{conv_id}/reject")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert data["approval_id"] is None
    assert data["messages"][-1]["content"] == "Query rejected by user."


def test_approve_not_awaiting_returns_409(client):
    """Cannot approve a conversation that is not awaiting approval."""
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    resp = client.post(f"/conversations/{conv_id}/approve")
    assert resp.status_code == 409


def test_approve_not_found(client):
    resp = client.post("/conversations/nonexistent/approve")
    assert resp.status_code == 404


def test_reject_not_found(client):
    resp = client.post("/conversations/nonexistent/reject")
    assert resp.status_code == 404


# ── Activity events ────────────────────────────────────────────────────────


def test_message_has_events(client):
    """Processed message should have activity events."""
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    client.post(
        f"/conversations/{conv_id}/messages", json={"content": "Show all tables"}
    )
    resp = client.get(f"/conversations/{conv_id}")
    events = resp.json()["events"]
    assert len(events) >= 2
    assert events[0]["agent"] == "orchestrator"
    assert events[0]["action"] == "received"


def test_destructive_message_has_review_events(client):
    """Destructive message should have safety review events."""
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    client.post(
        f"/conversations/{conv_id}/messages",
        json={"content": "delete all employees"},
    )
    resp = client.get(f"/conversations/{conv_id}")
    events = resp.json()["events"]
    actions = [e["action"] for e in events]
    assert "review_started" in actions
    assert "review_completed" in actions


# ── Health & infrastructure ────────────────────────────────────────────────


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readiness_probe(client):
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_log_stream_endpoint_is_registered(client):
    routes = [r.path for r in client.app.routes if hasattr(r, "path")]
    assert "/logs/stream" in routes
