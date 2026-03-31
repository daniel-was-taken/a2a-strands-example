"""End-to-end tests — orchestrator → specialist agent round-trip.

These tests require live infrastructure (Neon DB, Gemini API key) and are
skipped by default unless the E2E_TESTS environment variable is set.

Usage:
    E2E_TESTS=1 DATABASE_AGENT_URL=http://localhost:8001/ \\
        GRAPH_AGENT_URL=http://localhost:8002/ \\
        pytest tests/e2e/ -v

Pre-requisites:
    1. Start all services:  python run_system.py
    2. Set required env vars in .env
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("E2E_TESTS"),
    reason="Set E2E_TESTS=1 to run end-to-end tests (requires live infra)",
)


@pytest.mark.asyncio
async def test_orchestrator_health():
    """Orchestrator /health should return 200."""
    import httpx

    orchestrator_url = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8000")
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{orchestrator_url}/health", timeout=10)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_db_agent_card_reachable():
    """Database Agent AgentCard should be reachable from orchestrator."""
    import httpx

    db_agent_url = os.environ.get("DATABASE_AGENT_URL", "http://localhost:8001/")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{db_agent_url.rstrip('/')}/.well-known/agent-card.json",
            timeout=10,
        )
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "Database Agent"


@pytest.mark.asyncio
async def test_graph_agent_card_reachable():
    """Graph Agent AgentCard should be reachable from orchestrator."""
    import httpx

    graph_agent_url = os.environ.get("GRAPH_AGENT_URL", "http://localhost:8002/")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{graph_agent_url.rstrip('/')}/.well-known/agent-card.json",
            timeout=10,
        )
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "Graph Agent"


@pytest.mark.asyncio
async def test_full_schema_query_round_trip():
    """Full round-trip: orchestrator → database agent → response."""
    import httpx

    orchestrator_url = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8000")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{orchestrator_url}/query",
            json={"query": "List all tables in the database"},
            timeout=120,
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "COMPLETED"
    assert data["result"]
