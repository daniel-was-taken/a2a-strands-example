"""Strands Agent lifecycle hooks.

Provides an ``OrchestratorHook`` that logs before/after each agent invocation
and optionally pushes those events to the SSE broadcaster.

Usage::

    from hooks import OrchestratorHook
    agent = Agent(..., hooks=OrchestratorHook())
"""

from __future__ import annotations

import logging

from strands.hooks import HookProvider, HookEvent

from log_stream import broadcaster

logger = logging.getLogger(__name__)


class OrchestratorHook(HookProvider):
    """Log agent invocation lifecycle events."""

    def register_hooks(self, registry) -> None:
        """Wire before/after invocation events."""
        from strands.hooks import BeforeInvocationEvent, AfterInvocationEvent

        registry.add_callback(BeforeInvocationEvent, self._before)
        registry.add_callback(AfterInvocationEvent, self._after)

    def _before(self, event) -> None:
        logger.info("Agent invocation started")
        broadcaster.publish('{"level":"INFO","logger":"hooks","message":"Agent invocation started"}')

    def _after(self, event) -> None:
        logger.info("Agent invocation completed")
        broadcaster.publish('{"level":"INFO","logger":"hooks","message":"Agent invocation completed"}')
