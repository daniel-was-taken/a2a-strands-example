"""Tests for the orchestrator query submission lifecycle."""


def test_submit_non_destructive_query(client):
    """Non-destructive query should complete immediately."""
    resp = client.post("/query", json={"query": "Show all tables"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "COMPLETED"
    assert data["request_id"]
    assert data["result"]


def test_submit_destructive_query_is_rejected(client):
    """Destructive query should be blocked by safety review."""
    resp = client.post("/query", json={"query": "delete all employees"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "REJECTED"
    assert "review_verdict" in data


def test_submit_empty_query_returns_422(client):
    resp = client.post("/query", json={"query": ""})
    assert resp.status_code == 422
