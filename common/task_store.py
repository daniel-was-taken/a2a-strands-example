"""Thread-safe in-memory A2A TaskStore.

Implements the ``a2a.server.tasks.task_store.TaskStore`` ABC so it can be
passed directly to ``A2AServer(task_store=...)``.

Production guidance
-------------------
For **multi-replica** deployments (ECS, Cloud Run, Kubernetes) replace this
class with a DynamoDB- or Redis-backed implementation.  The interface is
intentionally minimal — only three methods to override:

    class DynamoDBTaskStore(TaskStore):
        def get(self, task_id, context=None): ...
        def save(self, task, context=None): ...
        def delete(self, task_id, context=None): ...

For **single-replica** deployments ``InMemoryA2ATaskStore`` is sufficient and
has zero external dependencies.
"""

from __future__ import annotations

import threading

from a2a.server.context import ServerCallContext
from a2a.server.tasks.task_store import TaskStore
from a2a.types import Task


class InMemoryA2ATaskStore(TaskStore):
    """Thread-safe dict-backed A2A TaskStore.

    Safe for single-process deployments.  **Not** suitable for multi-replica
    deployments — use a shared store (DynamoDB, ElastiCache) instead.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, Task] = {}

    async def get(
        self,
        task_id: str,
        context: ServerCallContext | None = None,
    ) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    async def save(
        self,
        task: Task,
        context: ServerCallContext | None = None,
    ) -> None:
        with self._lock:
            self._tasks[task.id] = task

    async def delete(
        self,
        task_id: str,
        context: ServerCallContext | None = None,
    ) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)
