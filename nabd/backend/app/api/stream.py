"""Global SSE channel: alerts, data refreshes, job progress, LLM progress, heartbeat.

The client reconnects with Last-Event-ID and falls back to polling /api/system/health if the stream goes quiet.
"""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..core.bus import bus
from ..core.config import get_settings

router = APIRouter()


@router.get("/api/stream")
async def stream(request: Request):
    last = request.headers.get("last-event-id")
    q = bus.subscribe(int(last) if last and last.isdigit() else None)
    beat = get_settings().heartbeat_seconds

    async def gen():
        try:
            yield "retry: 3000\n\n"
            while not bus.closing:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), beat)
                    yield event.sse()
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
