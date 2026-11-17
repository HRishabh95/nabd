"""Background jobs with a row per run and progress streamed as job.* events.

Every number on screen can link back to a job id: inputs, timings, outcome and summary are stored.
CPU-heavy model runs will use a process pool (phase 2); data refreshes are I/O-bound and run on the event loop.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable

from ..core.bus import bus
from ..core.db import conn

SQL = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, label TEXT, params TEXT, status TEXT NOT NULL,
  started REAL, finished REAL, progress REAL DEFAULT 0, message TEXT, summary TEXT, error TEXT
);
"""
_ready = False
_running: dict[str, asyncio.Task] = {}
_by_key: dict[str, str] = {}


def _init():
    global _ready
    if not _ready:
        conn().executescript(SQL)
        # a job still marked running belongs to a previous process that stopped
        conn().execute("UPDATE jobs SET status='interrupted', finished=? WHERE status='running'", (time.time(),))
        _ready = True


class Progress:
    """Throttled progress reporter handed to the job body: report(done, total, message)."""

    def __init__(self, job_id: str, kind: str, params: dict):
        self.job_id, self.kind, self.params, self._last = job_id, kind, params, 0.0

    def __call__(self, done: int, total: int, message: str = ""):
        now = time.monotonic()
        frac = done / total if total else 1.0
        if now - self._last < 0.25 and done < total:
            return
        self._last = now
        conn().execute("UPDATE jobs SET progress=?, message=? WHERE id=?", (frac, message, self.job_id))
        bus.publish("job.progress", job_id=self.job_id, kind=self.kind, done=done, total=total,
                    progress=round(frac, 4), message=message, params=self.params)


def start(kind: str, label: str, body: Callable[[Progress], Awaitable[dict]], params: dict | None = None,
          key: str | None = None) -> str:
    """Start a job unless one with the same key is already running; returns the job id."""
    _init()
    if key and key in _by_key and not _running[_by_key[key]].done():
        return _by_key[key]
    loop = asyncio.get_running_loop()  # fail before writing a row if called off the event loop
    job_id = f"{kind}-{uuid.uuid4().hex[:8]}"
    conn().execute("INSERT INTO jobs(id,kind,label,params,status,started) VALUES(?,?,?,?, 'running', ?)",
                   (job_id, kind, label, json.dumps(params or {}), time.time()))
    bus.publish("job.started", job_id=job_id, kind=kind, label=label, params=params or {})

    async def run():
        try:
            summary = await body(Progress(job_id, kind, params or {}))
            conn().execute("UPDATE jobs SET status='done', finished=?, progress=1, summary=? WHERE id=?",
                           (time.time(), json.dumps(summary, default=str), job_id))
            bus.publish("job.done", job_id=job_id, kind=kind, label=label, summary=summary, params=params or {})
        except Exception as exc:
            conn().execute("UPDATE jobs SET status='failed', finished=?, error=? WHERE id=?",
                           (time.time(), f"{type(exc).__name__}: {exc}"[:500], job_id))
            bus.publish("job.failed", job_id=job_id, kind=kind, label=label, error=str(exc)[:300],
                        params=params or {})

    task = loop.create_task(run(), name=job_id)
    _running[job_id] = task
    if key:
        _by_key[key] = job_id
    return job_id


def get(job_id: str) -> dict | None:
    _init()
    row = conn().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    for k in ("params", "summary"):
        d[k] = json.loads(d[k]) if d[k] else None
    return d


def recent(limit: int = 20) -> list[dict]:
    _init()
    rows = conn().execute("SELECT id FROM jobs ORDER BY started DESC LIMIT ?", (limit,)).fetchall()
    return [get(r["id"]) for r in rows]


async def shutdown():
    for t in _running.values():
        t.cancel()
