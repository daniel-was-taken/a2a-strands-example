"""Langfuse observability integration for the A2A Strands system.

Provides:
- ``get_client()`` — lazy-initialized Langfuse singleton
- ``LangfuseMiddleware`` — creates a Langfuse trace per HTTP request
- ``LangfuseTracingHook`` — Strands ``HookProvider`` that maps agent lifecycle
  events (model calls, tool calls) to Langfuse spans and generations
- ``set_session()`` — propagate conversation context to the current trace

When Langfuse credentials are not configured, all helpers fall back to no-ops.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from core.config import settings

logger = logging.getLogger(__name__)

# ── Paths that should create Langfuse traces ────────────────────────────────

_TRACED_PREFIXES = ("/conversations",)

# ── Langfuse client singleton ───────────────────────────────────────────────

_client: Any = None
_init_attempted = False


def get_client() -> Any:
    """Return the global Langfuse client, or ``None`` if not configured."""
    global _client, _init_attempted

    if _init_attempted:
        return _client

    _init_attempted = True

    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        logger.debug("Langfuse credentials not set — telemetry disabled")
        return None

    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info("Langfuse client initialized (host=%s)", settings.langfuse_host)
        return _client
    except Exception:
        logger.warning("Failed to initialize Langfuse client", exc_info=True)
        return None


def shutdown() -> None:
    """Flush pending events and shut down the Langfuse client."""
    if _client is not None:
        try:
            _client.shutdown()
        except Exception:
            logger.warning("Langfuse shutdown error", exc_info=True)


def get_trace_url() -> str | None:
    """Return the Langfuse URL for the currently active trace, if any."""
    client = get_client()
    if client is None:
        return None
    try:
        return client.get_trace_url()
    except Exception:
        return None


# ── Middleware ──────────────────────────────────────────────────────────────


class LangfuseMiddleware(BaseHTTPMiddleware):
    """Create a Langfuse trace per API request.

    Only traces requests to paths that match ``_TRACED_PREFIXES``.
    Sets ``X-Request-ID`` and ``X-Trace-ID`` response headers.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        client = get_client()
        if client is None or not any(
            request.url.path.startswith(p) for p in _TRACED_PREFIXES
        ):
            return await call_next(request)

        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        trace_name = f"{request.method} {request.url.path}"

        async with client.start_as_current_observation(
            name=trace_name,
            as_type="span",
            input={"method": request.method, "path": str(request.url.path)},
            metadata={"request_id": request_id},
        ) as root_span:
            try:
                response: Response = await call_next(request)
                root_span.update(
                    output={"status_code": response.status_code},
                    level="ERROR" if response.status_code >= 500 else "DEFAULT",
                )
                response.headers["X-Request-ID"] = request_id
                trace_id = client.get_current_trace_id()
                if trace_id:
                    response.headers["X-Trace-ID"] = trace_id
                return response
            except Exception as exc:
                root_span.update(
                    output={"error": str(exc)},
                    level="ERROR",
                    status_message=str(exc),
                )
                raise


def set_session(
    conversation_id: str,
    tags: list[str] | None = None,
    metadata: dict[str, str] | None = None,
) -> Any:
    """Set session-level attributes on the current Langfuse trace.

    Returns a context manager.  Call inside an ``async with`` or ``with``
    block so that the attributes propagate to all child spans.

    Usage::

        async with set_session(conversation_id, tags=["standard"]):
            ...
    """
    client = get_client()
    if client is None:
        return _nullcontext()

    from langfuse._client.propagation import propagate_attributes

    return propagate_attributes(
        session_id=conversation_id,
        tags=tags or [],
        metadata=metadata or {},
    )


# ── Strands Hook ───────────────────────────────────────────────────────────


class LangfuseTracingHook:
    """Strands ``HookProvider`` that maps agent events to Langfuse observations.

    Register on any Strands Agent via ``agent.hooks.add_hook(hook)``.

    Creates:
    - An **agent** span per invocation (``BeforeInvocationEvent`` / ``AfterInvocationEvent``)
    - A **generation** per model call with token usage
      (``BeforeModelCallEvent`` / ``AfterModelCallEvent``)
    - A **tool** span per tool call (``BeforeToolCallEvent`` / ``AfterToolCallEvent``)
    """

    # Keys used in invocation_state to carry span references across events.
    _INV_SPAN = "_lf_inv_span"
    _INV_START = "_lf_inv_start"
    _MODEL_SPAN = "_lf_model_span"
    _MODEL_START = "_lf_model_start"

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name

    # ── HookProvider protocol ──────────────────────────────────────────

    def register_hooks(self, registry: Any, **kwargs: Any) -> None:
        from strands.hooks.events import (
            AfterInvocationEvent,
            AfterModelCallEvent,
            AfterToolCallEvent,
            BeforeInvocationEvent,
            BeforeModelCallEvent,
            BeforeToolCallEvent,
        )

        registry.add_callback(BeforeInvocationEvent, self._on_before_invocation)
        registry.add_callback(AfterInvocationEvent, self._on_after_invocation)
        registry.add_callback(BeforeModelCallEvent, self._on_before_model_call)
        registry.add_callback(AfterModelCallEvent, self._on_after_model_call)
        registry.add_callback(BeforeToolCallEvent, self._on_before_tool_call)
        registry.add_callback(AfterToolCallEvent, self._on_after_tool_call)

    # ── Invocation lifecycle ───────────────────────────────────────────

    def _on_before_invocation(self, event: Any) -> None:
        client = get_client()
        if client is None:
            return
        span = client.start_observation(
            name=f"agent:{self.agent_name}",
            as_type="agent",
            input={"messages_count": len(event.messages) if event.messages else 0},
            metadata={"agent_name": self.agent_name},
        )
        event.invocation_state[self._INV_SPAN] = span
        event.invocation_state[self._INV_START] = time.perf_counter()

    def _on_after_invocation(self, event: Any) -> None:
        span = event.invocation_state.pop(self._INV_SPAN, None)
        start = event.invocation_state.pop(self._INV_START, None)
        if span is None:
            return

        output: dict[str, Any] = {}
        result = event.result
        if result is not None:
            output["stop_reason"] = result.stop_reason
            try:
                usage = result.metrics.accumulated_usage
                span.update(usage_details={
                    "input": usage.get("inputTokens", 0),
                    "output": usage.get("outputTokens", 0),
                    "total": usage.get("totalTokens", 0),
                })
            except Exception:
                pass

        if start is not None:
            output["duration_ms"] = round((time.perf_counter() - start) * 1000, 1)

        span.update(output=output)
        span.end()

    # ── Model call lifecycle ───────────────────────────────────────────

    def _on_before_model_call(self, event: Any) -> None:
        parent = event.invocation_state.get(self._INV_SPAN)
        if parent is None:
            return
        gen = parent.start_observation(
            name=f"llm:{self.agent_name}",
            as_type="generation",
            model=settings.gemini_model_id,
        )
        event.invocation_state[self._MODEL_SPAN] = gen
        event.invocation_state[self._MODEL_START] = time.perf_counter()

    def _on_after_model_call(self, event: Any) -> None:
        gen = event.invocation_state.pop(self._MODEL_SPAN, None)
        start = event.invocation_state.pop(self._MODEL_START, None)
        if gen is None:
            return

        if event.exception:
            gen.update(
                level="ERROR",
                status_message=str(event.exception),
            )
        elif event.stop_response:
            gen.update(output={"stop_reason": event.stop_response.stop_reason})

        if start is not None:
            gen.update(metadata={"duration_ms": round((time.perf_counter() - start) * 1000, 1)})

        gen.end()

    # ── Tool call lifecycle ────────────────────────────────────────────

    @staticmethod
    def _tool_key(tool_use_id: str) -> str:
        return f"_lf_tool_{tool_use_id}"

    @staticmethod
    def _tool_start_key(tool_use_id: str) -> str:
        return f"_lf_tool_s_{tool_use_id}"

    def _on_before_tool_call(self, event: Any) -> None:
        parent = event.invocation_state.get(self._INV_SPAN)
        if parent is None:
            return

        tool_name = event.tool_use.get("name", "unknown")
        tool_input = _safe_serialize(event.tool_use.get("input", {}))
        tool_use_id = event.tool_use["toolUseId"]

        span = parent.start_observation(
            name=f"tool:{tool_name}",
            as_type="tool",
            input=tool_input,
        )
        event.invocation_state[self._tool_key(tool_use_id)] = span
        event.invocation_state[self._tool_start_key(tool_use_id)] = time.perf_counter()

    def _on_after_tool_call(self, event: Any) -> None:
        tool_use_id = event.tool_use["toolUseId"]
        span = event.invocation_state.pop(self._tool_key(tool_use_id), None)
        start = event.invocation_state.pop(self._tool_start_key(tool_use_id), None)
        if span is None:
            return

        if event.exception:
            span.update(
                level="ERROR",
                status_message=str(event.exception),
            )
        else:
            content = event.result.get("content", [])
            output = _safe_serialize(content)
            status = event.result.get("status", "unknown")
            span.update(
                output=output,
                metadata={"status": status},
            )

        if start is not None:
            span.update(metadata={"duration_ms": round((time.perf_counter() - start) * 1000, 1)})

        span.end()


# ── Helpers ─────────────────────────────────────────────────────────────────


def _safe_serialize(obj: Any) -> Any:
    """Best-effort conversion to a JSON-safe structure for Langfuse."""
    try:
        json.dumps(obj, default=str)
        return obj
    except (TypeError, ValueError):
        return str(obj)


class _nullcontext:
    """No-op context manager for when Langfuse is disabled."""

    def __enter__(self):
        return self

    def __exit__(self, *exc: Any):
        return False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc: Any):
        return False
