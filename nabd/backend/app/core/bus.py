"""In-process event bus feeding the SSE channels.

Events are small typed deltas ({type, data, id, ts}), never a full state dump. Each subscriber has a bounded
queue; a slow client drops its oldest events rather than stalling publishers, and recovers by re-fetching state.
A short ring buffer lets a reconnecting client resume from Last-Event-ID.
"""

import asyncio
import itertools
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class Event:
    type: str
    data: dict
    id: int = 0
    ts: float = field(default_factory=time.time)

    def sse(self) -> str:
        import json

        return f"id: {self.id}\nevent: {self.type}\ndata: {json.dumps({'ts': self.ts, **self.data})}\n\n"


class EventBus:
    def __init__(self, history: int = 500, queue_size: int = 200):
        self._ids = itertools.count(1)
        self._history: deque[Event] = deque(maxlen=history)
        self._subscribers: set[asyncio.Queue] = set()
        self._queue_size = queue_size
        self.closing = False  # set on shutdown so open streams end promptly

    def publish(self, type: str, **data) -> Event:
        event = Event(type=type, data=data, id=next(self._ids))
        self._history.append(event)
        for q in list(self._subscribers):
            if q.full():
                q.get_nowait()
            q.put_nowait(event)
        return event

    def subscribe(self, last_id: int | None = None) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(self._queue_size)
        if last_id is not None:
            for e in self._history:
                if e.id > last_id and not q.full():
                    q.put_nowait(e)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


bus = EventBus()
