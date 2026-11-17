"""Nabd backend: FastAPI app and its background loops."""

import asyncio
import contextlib
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import ask, data, forecast, fraud, governance, invest, markets, monitor, stream, system
from .core.bus import bus
from .core.config import get_settings
from .core.db import conn
from .data.refresh import scheduler_loop
from .invest.monitor import monitor_loop
from .jobs import runner


async def heartbeat_loop():
    beat = get_settings().heartbeat_seconds
    while True:
        bus.publish("heartbeat", server_time=time.time(), subscribers=bus.subscriber_count)
        await asyncio.sleep(beat)


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn()
    from .invest.deep import resume_interrupted
    resume_interrupted()
    tasks = [asyncio.create_task(heartbeat_loop(), name="heartbeat"),
             asyncio.create_task(scheduler_loop(), name="scheduler"),
             asyncio.create_task(monitor_loop(), name="monitor")]
    try:
        yield
    finally:
        bus.closing = True
        await runner.shutdown()
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t


app = FastAPI(title="Nabd", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().allowed_origins, allow_methods=["*"],
                   allow_headers=["*"])
app.include_router(system.router)
app.include_router(stream.router)
app.include_router(data.router)
app.include_router(markets.router)
app.include_router(invest.router)
app.include_router(ask.router)
app.include_router(forecast.router)
app.include_router(fraud.router)
app.include_router(monitor.router)
app.include_router(governance.router)
