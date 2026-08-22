from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict, deque
from collections.abc import AsyncIterator

from app.schemas.events import BrainEvent, EventType

#: Terminal events are final. A task may cross into exactly one of these,
#: once - every completion path (TaskRuntime._emit, MissionLoop, engines,
#:
#: anything wired in the future) funnels through EventBus.publish, so THIS
#: is the single structural choke point. Guards that live only in one
#: publisher are bypassed by every other publisher; the trace showed
#: task_completed arriving twice, ~38ms apart, because MissionLoop and
#: TaskRuntime each published their own.
_TERMINAL_TYPES = frozenset({
    EventType.TASK_COMPLETED, EventType.TASK_FAILED, EventType.TASK_CANCELLED,
})


class EventBus:
    def __init__(self, history_size: int = 500):
        self.history: deque[BrainEvent] = deque(maxlen=history_size)
        self.subscribers: set[asyncio.Queue[BrainEvent]] = set()
        #: task_id -> terminal type already delivered. Bounded so a
        #: long-lived Brain cannot grow it without limit.
        self._terminalized: OrderedDict[str, EventType] = OrderedDict()
        #: Counters for LAW 3 (one task, one terminal event). Observable
        #: so tests and diagnostics can assert the invariant, not trust it.
        self.duplicate_terminal_suppressed = 0

    def _is_duplicate_terminal(self, event: BrainEvent) -> bool:
        if event.type not in _TERMINAL_TYPES:
            return False
        previous = self._terminalized.get(event.task_id)
        if previous is None:
            self._terminalized[event.task_id] = event.type
            while len(self._terminalized) > 512:
                self._terminalized.popitem(last=False)
            return False
        # A CANCELLED task can never later be reported COMPLETED or FAILED -
        # cancellation is itself terminal and outranks any late result.
        self.duplicate_terminal_suppressed += 1
        logging.getLogger("vyom.runtime").warning(
            "duplicate terminal event suppressed: task=%s already %s, attempted %s",
            event.task_id, previous.value, event.type.value,
        )
        return True

    async def publish(self, event: BrainEvent) -> None:
        if self._is_duplicate_terminal(event):
            return
        self.history.append(event)
        for queue in tuple(self.subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    async def subscribe(self) -> AsyncIterator[BrainEvent]:
        queue: asyncio.Queue[BrainEvent] = asyncio.Queue(maxsize=200)
        self.subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self.subscribers.discard(queue)

    def register(self) -> tuple[asyncio.Queue[BrainEvent], callable]:
        """Queue-based subscription for callers that must interleave the
        live stream with other awaits (the websocket endpoint replays
        history between subscribing and streaming). Returns the queue and
        an unregister callback."""
        queue: asyncio.Queue[BrainEvent] = asyncio.Queue(maxsize=200)
        self.subscribers.add(queue)

        def unregister() -> None:
            self.subscribers.discard(queue)

        return queue, unregister

    def history_after(self, event_id: str | None) -> list[BrainEvent]:
        """Events published after the given cursor, oldest first.

        A reconnecting client passes the last event_id it saw; events that
        fired while it was disconnected used to be lost entirely - the
        whole point of a durable event stream is that they are not. An
        unknown cursor (Brain restarted, history rolled over) replays the
        entire bounded history; the client deduplicates by event_id."""
        events = list(self.history)
        if event_id is None:
            return []
        for index, event in enumerate(events):
            if event.event_id == event_id:
                return events[index + 1 :]
        return events

