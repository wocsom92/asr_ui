from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.auth.deps import get_current_user
from app.models.user import User
from app.services.event_bus import event_bus

router = APIRouter(prefix="/api/v1/events", tags=["events"])

# Heartbeat keeps the connection (and any intervening proxies) alive when idle.
_HEARTBEAT_SECONDS = 25.0


@router.get("")
async def stream_events(request: Request, user: User = Depends(get_current_user)):
    queue = event_bus.subscribe(user.id)

    async def event_generator():
        try:
            # Prompt the client to (re)sync immediately on connect.
            yield "event: ready\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            event_bus.unsubscribe(user.id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
