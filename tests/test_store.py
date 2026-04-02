"""Tests for the InMemoryConversationStore."""

from common.schemas import ActivityEvent, Conversation, ConversationStatus, Message
from common.store import InMemoryConversationStore


def test_create_and_get():
    store = InMemoryConversationStore()
    conv = Conversation(id="c1", title="Test")
    store.create(conv)
    assert store.get("c1") is not None
    assert store.get("c1").title == "Test"


def test_get_missing_returns_none():
    store = InMemoryConversationStore()
    assert store.get("missing") is None


def test_list_all_ordered_by_updated_at():
    store = InMemoryConversationStore()
    c1 = Conversation(id="c1", title="First", updated_at="2024-01-01T00:00:00")
    c2 = Conversation(id="c2", title="Second", updated_at="2024-01-02T00:00:00")
    store.create(c1)
    store.create(c2)
    result = store.list_all()
    assert len(result) == 2
    assert result[0].id == "c2"  # newest first


def test_add_message():
    store = InMemoryConversationStore()
    store.create(Conversation(id="c1", title="T"))
    store.add_message("c1", Message(role="user", content="hello"))
    conv = store.get("c1")
    assert len(conv.messages) == 1
    assert conv.messages[0].content == "hello"


def test_add_message_updates_updated_at():
    store = InMemoryConversationStore()
    conv = Conversation(id="c1", title="T", updated_at="2024-01-01T00:00:00")
    store.create(conv)
    store.add_message("c1", Message(role="user", content="hello"))
    updated = store.get("c1")
    assert updated.updated_at != "2024-01-01T00:00:00"


def test_add_event():
    store = InMemoryConversationStore()
    store.create(Conversation(id="c1", title="T"))
    store.add_event("c1", ActivityEvent(agent="test", action="did"))
    conv = store.get("c1")
    assert len(conv.events) == 1
    assert conv.events[0].agent == "test"


def test_update():
    store = InMemoryConversationStore()
    store.create(Conversation(id="c1", title="T"))
    result = store.update("c1", title="New Title", status=ConversationStatus.AWAITING_APPROVAL)
    assert result is not None
    assert result.title == "New Title"
    assert result.status == ConversationStatus.AWAITING_APPROVAL


def test_update_missing_returns_none():
    store = InMemoryConversationStore()
    assert store.update("missing", title="X") is None


def test_update_updates_updated_at():
    store = InMemoryConversationStore()
    conv = Conversation(id="c1", title="T", updated_at="2024-01-01T00:00:00")
    store.create(conv)
    store.update("c1", title="X")
    assert store.get("c1").updated_at != "2024-01-01T00:00:00"


def test_delete():
    store = InMemoryConversationStore()
    store.create(Conversation(id="c1", title="T"))
    store.delete("c1")
    assert store.get("c1") is None


def test_delete_missing_does_not_raise():
    store = InMemoryConversationStore()
    store.delete("missing")  # should not raise
