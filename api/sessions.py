from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

MAX_SESSIONS = 500
IDLE_SECONDS = 3600


@dataclass
class Session:
    id: str
    history: list[tuple[str, str]] = field(default_factory=list)
    touched: float = field(default_factory=time.time)


class SessionStore:
    def __init__(self) -> None:
        self._data: dict[str, Session] = {}
        self._lock = threading.Lock()

    def _evict(self) -> None:
        cutoff = time.time() - IDLE_SECONDS
        stale = [k for k, s in self._data.items() if s.touched < cutoff]
        for k in stale:
            del self._data[k]
        if len(self._data) > MAX_SESSIONS:
            ordered = sorted(self._data.items(), key=lambda kv: kv[1].touched)
            for k, _ in ordered[: len(self._data) - MAX_SESSIONS]:
                del self._data[k]

    def get(self, session_id: str | None) -> Session:
        with self._lock:
            self._evict()
            if session_id and session_id in self._data:
                s = self._data[session_id]
                s.touched = time.time()
                return s
            s = Session(id=session_id or uuid.uuid4().hex[:16])
            self._data[s.id] = s
            return s

    def reset(self, session_id: str) -> Session:
        with self._lock:
            s = self._data.get(session_id)
            if s:
                s.history.clear()
                s.touched = time.time()
                return s
            s = Session(id=session_id)
            self._data[s.id] = s
            return s

    def count(self) -> int:
        return len(self._data)
