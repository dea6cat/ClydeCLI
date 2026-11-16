from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ManagedTask:
    task_id: str
    stop_event: threading.Event


class TaskManager:
    """Background tasks (sub-agents) by id, so a stop request can reach the one it names."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, ManagedTask] = {}

    def start(self, *, name: str, target: Callable[[threading.Event], None]) -> ManagedTask:
        task = ManagedTask(task_id=str(uuid.uuid4()), stop_event=threading.Event())

        def runner() -> None:
            try:
                target(task.stop_event)
            finally:
                with self._lock:
                    self._tasks.pop(task.task_id, None)

        with self._lock:
            self._tasks[task.task_id] = task
        threading.Thread(target=runner, name=f"tool-task:{name}:{task.task_id}", daemon=True).start()
        return task

    def stop(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            return False
        task.stop_event.set()
        return True
