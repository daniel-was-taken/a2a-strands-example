"""Tests for the InMemoryConversationStore."""

import pytest

from core.schemas import ActivityEvent, Conversation, ConversationStatus, Message
from core.store import InMemoryConversationStore


@pytest.mark.asyncio
async def test_create_and_get():
    store = InMemoryConversationStore()
    conv = Conversation(id="c1", title="Test")
    await store.create(conv)
    assert await store.get("c1") is not None
    result = await store.get("c1")
    assert result.title == "Test"


@pytest.mark.asyncio
async def test_get_missing_returns_none():
    store = InMemoryConversationStore()
    assert await store.get("missing") is None


@pytest.mark.asyncio
async def test_list_all_ordered_by_updated_at():
    store = InMemoryConversationStore()
    c1 = Conversation(id="c1", title="First", updated_at="2024-01-01T00:00:00")
    c2 = Conversation(id="c2", title="Second", updated_at="2024-01-02T00:00:00")
    await store.create(c1)
    await store.create(c2)
    result = await store.list_all()
    assert len(result) == 2
    assert result[0].id == "c2"  # newest first


@pytest.mark.asyncio
async def test_add_message():
    store = InMemoryConversationStore()
    await store.create(Conversation(id="c1", title="T"))
    await store.add_message("c1", Message(role="user", content="hello"))
    conv = await store.get("c1")
    assert len(conv.messages) == 1
    assert conv.messages[0].content == "hello"


@pytest.mark.asyncio
async def test_add_message_updates_updated_at():
    store = InMemoryConversationStore()
    conv = Conversation(id="c1", title="T", updated_at="2024-01-01T00:00:00")
    await store.create(conv)
    await store.add_message("c1", Message(role="user", content="hello"))
    updated = await store.get("c1")
    assert updated.updated_at != "2024-01-01T00:00:00"


@pytest.mark.asyncio
async def test_add_event():
    store = InMemoryConversationStore()
    await store.create(Conversation(id="c1", title="T"))
    await store.add_event("c1", ActivityEvent(agent="test", action="did"))
    conv = await store.get("c1")
    assert len(conv.events) == 1
    assert conv.events[0].agent == "test"


@pytest.mark.asyncio
async def test_update():
    store = InMemoryConversationStore()
    await store.create(Conversation(id="c1", title="T"))
    result = await store.update(
        "c1", title="New Title", status=ConversationStatus.AWAITING_APPROVAL
    )
    assert result is not None
    assert result.title == "New Title"
    assert result.status == ConversationStatus.AWAITING_APPROVAL


@pytest.mark.asyncio
async def test_update_missing_returns_none():
    store = InMemoryConversationStore()
    assert await store.update("missing", title="X") is None


@pytest.mark.asyncio
async def test_update_updates_updated_at():
    store = InMemoryConversationStore()
    conv = Conversation(id="c1", title="T", updated_at="2024-01-01T00:00:00")
    await store.create(conv)
    await store.update("c1", title="X")
    result = await store.get("c1")
    assert result.updated_at != "2024-01-01T00:00:00"


@pytest.mark.asyncio
async def test_delete():
    store = InMemoryConversationStore()
    await store.create(Conversation(id="c1", title="T"))
    await store.delete("c1")
    assert await store.get("c1") is None


@pytest.mark.asyncio
async def test_delete_missing_does_not_raise():
    store = InMemoryConversationStore()
    await store.delete("missing")  # should not raise
