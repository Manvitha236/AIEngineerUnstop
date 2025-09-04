import asyncio
from typing import AsyncIterator, Set, Callable

class EventBroadcaster:
    def __init__(self):
        self._queues: Set[asyncio.Queue] = set()

    async def subscribe(self) -> AsyncIterator[str]:  # pragma: no cover (async generator)
        q: asyncio.Queue = asyncio.Queue()
        self._queues.add(q)
        try:
            while True:
                msg = await q.get()
                yield msg
        finally:
            self._queues.discard(q)

    def publish(self, event: str, data: str):
        payload = f"event: {event}\ndata: {data}\n\n"
        for q in list(self._queues):
            if not q.full():
                q.put_nowait(payload)

broadcaster = EventBroadcaster()