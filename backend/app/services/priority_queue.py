import heapq
from dataclasses import dataclass, field
from typing import Any, List, Iterator

@dataclass(order=True)
class PrioritizedEmail:
    priority_rank: int
    email_id: int = field(compare=False)
    data: Any = field(compare=False, default=None)

class EmailPriorityQueue:
    def __init__(self):
        self._heap: List[PrioritizedEmail] = []

    def push(self, email_id: int, urgency: str, data=None):
        rank = 0 if urgency == 'Urgent' else 1
        heapq.heappush(self._heap, PrioritizedEmail(rank, email_id, data))

    def pop(self) -> PrioritizedEmail | None:
        if not self._heap:
            return None
        return heapq.heappop(self._heap)

    def __len__(self):
        return len(self._heap)

    def __iter__(self) -> Iterator[PrioritizedEmail]:
        return (item for item in sorted(self._heap))
