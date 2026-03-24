"""Tests for the InMemoryStore."""

from schemas import ActivityEvent, Message, QueryResponse, RequestStatus
from store import InMemoryStore


def test_save_and_get():
    store = InMemoryStore()
    rec = QueryResponse(request_id="r1", status=RequestStatus.COMPLETED, query="q")
    store.save(rec)
    assert store.get("r1") is not None
    assert store.get("r1").query == "q"


def test_get_missing_returns_none():
    store = InMemoryStore()
    assert store.get("missing") is None


def test_list_all_ordered_by_created_at():
    store = InMemoryStore()
    r1 = QueryResponse(request_id="r1", status=RequestStatus.COMPLETED, query="q1", created_at="2024-01-01T00:00:00")
    r2 = QueryResponse(request_id="r2", status=RequestStatus.COMPLETED, query="q2", created_at="2024-01-02T00:00:00")
    store.save(r1)
    store.save(r2)
    result = store.list_all()
    assert len(result) == 2
    assert result[0].request_id == "r2"  # newest first


def test_update_status():
    store = InMemoryStore()
    store.save(QueryResponse(request_id="r1", status=RequestStatus.COMPLETED, query="q"))
    rec = store.update_status("r1", RequestStatus.FAILED, result="error")
    assert rec is not None
    assert rec.status == RequestStatus.FAILED
    assert rec.result == "error"


def test_update_status_review_verdict_and_approval_id():
    store = InMemoryStore()
    store.save(QueryResponse(request_id="r1", status=RequestStatus.COMPLETED, query="q"))
    rec = store.update_status(
        "r1", RequestStatus.PENDING_APPROVAL,
        review_verdict="APPROVE: ok",
        approval_id="abcd1234",
    )
    assert rec.review_verdict == "APPROVE: ok"
    assert rec.approval_id == "abcd1234"


def test_get_by_approval_id():
    store = InMemoryStore()
    store.save(QueryResponse(request_id="r1", status=RequestStatus.PENDING_APPROVAL, query="q"))
    store.update_status("r1", RequestStatus.PENDING_APPROVAL, approval_id="abc123")
    rec = store.get_by_approval_id("abc123")
    assert rec is not None
    assert rec.request_id == "r1"


def test_get_by_approval_id_missing():
    store = InMemoryStore()
    assert store.get_by_approval_id("missing") is None


def test_add_event():
    store = InMemoryStore()
    store.save(QueryResponse(request_id="r1", status=RequestStatus.COMPLETED, query="q"))
    store.add_event("r1", ActivityEvent(agent="test", action="did_thing"))
    rec = store.get("r1")
    assert len(rec.events) == 1
    assert rec.events[0].agent == "test"


def test_add_message():
    store = InMemoryStore()
    store.save(QueryResponse(request_id="r1", status=RequestStatus.COMPLETED, query="q"))
    store.add_message("r1", Message(role="user", content="hello"))
    store.add_message("r1", Message(role="agent", content="world"))
    rec = store.get("r1")
    assert len(rec.messages) == 2
    assert rec.messages[0].role == "user"
    assert rec.messages[0].content == "hello"
    assert rec.messages[1].role == "agent"
