"""Bounded log buffer used by HTTP state and WebSocket broadcasts."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time


@dataclass(slots=True)
class LogEntry:
    index: int
    level: str
    message: str
    created_at: float


class LogBuffer:
    """In-memory log ring with monotonically increasing indices."""

    def __init__(self, limit: int) -> None:
        self._entries: deque[LogEntry] = deque(maxlen=max(1, limit))
        self._next_index = 1

    def append(self, level: str, message: str) -> LogEntry:
        entry = LogEntry(
            index=self._next_index,
            level=level,
            message=message,
            created_at=time.time(),
        )
        self._next_index += 1
        self._entries.append(entry)
        return entry

    def to_list(self) -> list[dict[str, object]]:
        return [
            {
                "index": entry.index,
                "level": entry.level,
                "message": entry.message,
                "created_at": entry.created_at,
            }
            for entry in self._entries
        ]
