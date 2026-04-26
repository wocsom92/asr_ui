from __future__ import annotations

import asyncio

_lock = asyncio.Lock()
_events: dict[int, asyncio.Event] = {}


async def prepare_job_cancel_event(job_id: int) -> asyncio.Event:
    """Return a fresh event for this job run (used by the worker before claiming the row)."""
    async with _lock:
        ev = _events.get(job_id)
        if ev is None:
            ev = asyncio.Event()
            _events[job_id] = ev
        ev.clear()
        return ev


async def signal_job_cancel(job_id: int) -> None:
    """Request cooperative cancellation for a running job (idempotent)."""
    async with _lock:
        ev = _events.get(job_id)
        if ev is None:
            ev = asyncio.Event()
            _events[job_id] = ev
        ev.set()


async def dispose_job_cancel_event(job_id: int) -> None:
    async with _lock:
        _events.pop(job_id, None)
