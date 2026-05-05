"""Streaming adapter for the Strands orchestrator agent.

The Strands SDK exposes an async ``stream_async`` method on the ``Agent`` class
that yields incremental events (tokens, tool uses, and a final result). This
module wraps that API in a small adapter so the orchestrator's SSE endpoint
can ``async for`` over plain text tokens while still recovering:

- the final aggregated response text, and
- the list of agents the orchestrator routed to (via ``a2a_send_message``).

Callers pass in a factory that returns the shared ``Agent`` singleton plus the
``_agent_execution_lock`` that serialises agent access (Strands agents are not
safe to invoke concurrently).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Callable
from typing import Any

from strands import Agent

logger = logging.getLogger(__name__)


def _extract_text_from_event(event: Any) -> str | None:
    """Pull a text chunk out of a Strands stream event, if present.

    Strands' ``stream_async`` emits two parallel shapes for the same text:
    - ``{"data": "..."}`` — canonical token chunks.
    - ``{"event": {"contentBlockDelta": ...}}`` — the raw provider event that
      produced the above chunk.

    Reading both would duplicate every token. We only honour ``data`` — the
    canonical, SDK-level representation — and ignore raw provider events.
    Unknown shapes are ignored (no exception raised).
    """
    if not isinstance(event, dict):
        return None

    data = event.get("data")
    if isinstance(data, str) and data:
        return data

    return None


class AgentStreamAdapter:
    """Stream tokens from a shared Strands ``Agent`` over SSE.

    Usage::

        adapter = AgentStreamAdapter(_get_agent, _agent_execution_lock)
        async for token in adapter.run(prompt):
            yield sse_frame("token", {"text": token})
        final_text = adapter.final_text
        routed = adapter.routed_agents(agent_name_map)
    """

    def __init__(
        self,
        agent_factory: Callable[[], Agent],
        execution_lock: threading.Lock,
    ) -> None:
        self._agent_factory = agent_factory
        self._execution_lock = execution_lock
        self._agent: Agent | None = None
        self._final_text: str = ""

    @property
    def final_text(self) -> str:
        return self._final_text

    def routed_agents(self, agent_names: dict[str, str]) -> list[str]:
        """Return the ordered list of agent names routed to during the last run."""
        if self._agent is None:
            return []
        routed: list[str] = []
        for msg in reversed(self._agent.messages):
            for block in msg.get("content", []):
                if isinstance(block, dict) and "toolUse" in block:
                    tool = block["toolUse"]
                    if tool.get("name") == "a2a_send_message":
                        url = tool.get("input", {}).get("target_agent_url", "")
                        name = agent_names.get(url, url)
                        if name not in routed:
                            routed.append(name)
        return routed

    async def run(self, prompt: str) -> AsyncIterator[str]:
        """Async-iterate text tokens as the agent streams its response."""

        # Acquire the execution lock without blocking the event loop.
        await asyncio.to_thread(self._execution_lock.acquire)
        try:
            agent = self._agent_factory()
            self._agent = agent
            agent.messages = []

            if not hasattr(agent, "stream_async"):
                # SDK does not support streaming; fall back to a single-shot call
                # so callers still get a usable response.
                result = await asyncio.to_thread(agent, prompt)
                text = str(result)
                self._final_text = text
                if text:
                    yield text
                return

            buffer: list[str] = []
            async for event in agent.stream_async(prompt):
                # Strands emits a final ``{"result": ...}`` event at the end of
                # the stream. Capture that as the authoritative final text.
                if isinstance(event, dict) and "result" in event:
                    try:
                        self._final_text = str(event["result"])
                    except Exception:
                        self._final_text = "".join(buffer)
                    continue

                token = _extract_text_from_event(event)
                if token is None:
                    continue
                buffer.append(token)
                yield token

            if not self._final_text:
                self._final_text = "".join(buffer)
        finally:
            self._execution_lock.release()
