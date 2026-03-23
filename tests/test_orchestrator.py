"""Tests for the orchestrator query submission lifecycle."""


def test_submit_non_destructive_query(client):
    """Non-destructive query should complete immediately."""
    resp = client.post("/query", json={"query": "Show all tables"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "COMPLETED"
    assert data["request_id"]
    assert data["result"]
    assert data["query"] == "Show all tables"
    assert len(data["events"]) >= 1


def test_submit_destructive_query_is_rejected(client):
    """Destructive query rejected by safety reviewer should be RECOMMENDED_REJECT."""
    resp = client.post("/query", json={"query": "delete all employees"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "RECOMMENDED_REJECT"
    assert "review_verdict" in data


def test_submit_destructive_query_pending_approval(client_approve):
    """Destructive query approved by safety reviewer should be PENDING_APPROVAL."""
    resp = client_approve.post(
        "/query", json={"query": "delete from users where id = 5"}
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "PENDING_APPROVAL"
    assert "APPROVE" in data["review_verdict"]
    assert data["approval_id"] is not None


def test_submit_empty_query_returns_422(client):
    resp = client.post("/query", json={"query": ""})
    assert resp.status_code == 422


# ── Query history endpoints ──────────────────────────────────────────────────


def test_list_queries_empty(client):
    resp = client.get("/queries")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_queries_returns_submitted(client):
    client.post("/query", json={"query": "Show all tables"})
    resp = client.get("/queries")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["query"] == "Show all tables"


def test_get_single_query(client):
    post_resp = client.post("/query", json={"query": "Show all tables"})
    request_id = post_resp.json()["request_id"]

    resp = client.get(f"/queries/{request_id}")
    assert resp.status_code == 200
    assert resp.json()["request_id"] == request_id


def test_get_query_not_found(client):
    resp = client.get("/queries/nonexistent-id")
    assert resp.status_code == 404


# ── Approval / rejection endpoints ──────────────────────────────────────────


def test_approve_pending_query(client_approve):
    """Approving a PENDING_APPROVAL query should execute it."""
    post_resp = client_approve.post(
        "/query", json={"query": "delete from users where id = 5"}
    )
    data = post_resp.json()
    assert data["status"] == "PENDING_APPROVAL"
    approval_id = data["approval_id"]

    resp = client_approve.post(f"/queries/approve/{approval_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "COMPLETED"


def test_reject_pending_query(client_approve):
    """Rejecting a PENDING_APPROVAL query should mark it REJECTED."""
    post_resp = client_approve.post(
        "/query", json={"query": "delete from users where id = 5"}
    )
    data = post_resp.json()
    approval_id = data["approval_id"]

    resp = client_approve.post(f"/queries/reject/{approval_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "REJECTED"


def test_approve_non_pending_returns_409(client_approve):
    """Cannot approve a query that is not PENDING_APPROVAL once resolved."""
    # First create a pending query, then reject it, then try to approve via approval_id
    post_resp = client_approve.post(
        "/query", json={"query": "delete from users where id = 5"}
    )
    data = post_resp.json()
    approval_id = data["approval_id"]

    # Reject it first
    client_approve.post(f"/queries/reject/{approval_id}")

    # Now try to approve the already-rejected query
    resp = client_approve.post(f"/queries/approve/{approval_id}")
    assert resp.status_code == 409


def test_approve_not_found(client):
    resp = client.post("/queries/approve/nonexistent")
    assert resp.status_code == 404


# ── Activity events ─────────────────────────────────────────────────────────


def test_query_has_events(client):
    """Completed query should have activity events."""
    post_resp = client.post("/query", json={"query": "Show all tables"})
    request_id = post_resp.json()["request_id"]

    resp = client.get(f"/queries/{request_id}")
    events = resp.json()["events"]
    assert len(events) >= 2
    assert events[0]["agent"] == "orchestrator"
    assert events[0]["action"] == "received"


# ── Readiness probe ─────────────────────────────────────────────────────────


def test_readiness_probe(client):
    """GET /ready should return 200 when agent can be initialised."""
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ── RECOMMENDED_REJECT override ─────────────────────────────────────────────


def test_recommended_reject_has_events(client):
    """RECOMMENDED_REJECT query should have review events."""
    resp = client.post("/query", json={"query": "delete all employees"})
    data = resp.json()
    assert data["status"] == "RECOMMENDED_REJECT"
    events = data["events"]
    actions = [e["action"] for e in events]
    assert "review_started" in actions
    assert "review_completed" in actions
    assert "recommended_reject" in actions


# ── SSE log stream ───────────────────────────────────────────────────────────


def test_log_stream_endpoint_is_registered(client):
    """The /logs/stream route should be registered in the app."""
    routes = [r.path for r in client.app.routes if hasattr(r, "path")]
    assert "/logs/stream" in routes
