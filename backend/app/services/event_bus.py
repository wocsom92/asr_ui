"""In-process pub/sub used to push state changes to connected SSE clients.

The backend runs as a single process, so every job/summary/worker state transition
that the API or the in-process worker performs is observable here. Clients subscribe
per ``owner_user_id`` and receive small JSON envelopes that tell the frontend which
TanStack Query keys to invalidate, replacing most polling.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Bounded so a stalled client cannot grow memory without limit; on overflow we drop
# the oldest events (the frontend always re-syncs via query invalidation + safety poll).
_MAX_QUEUE = 200


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, user_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE)
        self._subscribers[user_id].add(queue)
        return queue

    def unsubscribe(self, user_id: int, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(user_id)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(user_id, None)

    def publish(self, event: dict[str, Any], *, user_id: Optional[int] = None) -> None:
        """Deliver ``event`` to one user (``user_id``) or broadcast to everyone.

        Must be called from the event loop thread.
        """
        if user_id is None:
            target_user_ids = list(self._subscribers.keys())
        else:
            target_user_ids = [user_id]
        for target in target_user_ids:
            for queue in list(self._subscribers.get(target, ())):
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    # Drop the oldest event to make room; clients re-sync anyway.
                    try:
                        queue.get_nowait()
                        queue.put_nowait(event)
                    except Exception:
                        pass


event_bus = EventBus()


def emit_job_event(owner_user_id: Optional[int], job_id: Optional[int] = None, kind: str = "job.updated") -> None:
    if owner_user_id is None:
        return
    event_bus.publish({"type": kind, "job_id": job_id}, user_id=owner_user_id)


def emit_summary_event(owner_user_id: Optional[int], job_id: Optional[int] = None) -> None:
    emit_job_event(owner_user_id, job_id, kind="summary.updated")


def emit_worker_event() -> None:
    # Worker state is admin-global; broadcasting is harmless because clients that do not
    # query workers simply ignore the invalidation.
    event_bus.publish({"type": "worker.updated"})
