"""Tests for the conversation data models."""

import pytest
from pydantic import ValidationError

from common.schemas import (
    ActivityEvent,
    Conversation,
    ConversationStatus,
    ConversationSummary,
    Message,
    MessageRequest,
)


def test_conversation_defaults():
    conv = Conversation(id="c1", title="Test")
    assert conv.status == ConversationStatus.ACTIVE
    assert conv.messages == []
    assert conv.events == []
    assert conv.approval_id is None
    assert conv.review_verdict is None
    assert conv.review_recommended_reject is False
    assert conv.pending_query is None
    assert conv.created_at  # auto-generated
    assert conv.updated_at  # auto-generated


def test_conversation_with_messages():
    conv = Conversation(
        id="c1",
        title="Test",
        messages=[Message(role="user", content="hello")],
    )
    assert len(conv.messages) == 1
    assert conv.messages[0].role == "user"


def test_conversation_awaiting_approval():
    conv = Conversation(
        id="c1",
        title="Test",
        status=ConversationStatus.AWAITING_APPROVAL,
        approval_id="abc123",
        review_verdict="APPROVE: scoped",
        pending_query="delete from users where id = 5",
    )
    assert conv.status == ConversationStatus.AWAITING_APPROVAL
    assert conv.approval_id == "abc123"


def test_conversation_summary():
    s = ConversationSummary(
        id="c1",
        title="Test",
        status=ConversationStatus.ACTIVE,
        created_at="2024-01-01T00:00:00",
        updated_at="2024-01-01T00:00:00",
    )
    assert s.id == "c1"
    assert s.title == "Test"


def test_message_request_valid():
    m = MessageRequest(content="hello")
    assert m.content == "hello"


def test_message_request_empty_rejected():
    with pytest.raises(ValidationError):
        MessageRequest(content="")


def test_message_unchanged():
    """Message model keeps role/content/timestamp fields."""
    m = Message(role="user", content="test")
    assert m.role == "user"
    assert m.content == "test"
    assert m.timestamp  # auto-generated


def test_activity_event_unchanged():
    """ActivityEvent model stays the same."""
    e = ActivityEvent(agent="orchestrator", action="received", detail="test")
    assert e.agent == "orchestrator"
