"""SQLite (WAL) for app state: jobs, runs, alerts, audit, the investment pipeline and its memory.

Time series and model outputs go to DuckDB over parquet (added in phase 1).
"""

import json
import sqlite3
import threading
import time

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT NOT NULL,
  action TEXT NOT NULL, subject TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS llm_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, provider TEXT, model TEXT, purpose TEXT,
  ok INTEGER, ms INTEGER, error TEXT
);
"""

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None  # first connection; tests set it to None to ask for fresh connections
_gen = 0
_local = threading.local()


def _open(path: str, schema: bool) -> sqlite3.Connection:
    c = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=15000")
    if schema:
        c.executescript(SCHEMA)
    return c


def conn() -> sqlite3.Connection:
    """One connection per thread. A single shared connection breaks when a background job writes while a request
    reads ("bad parameter or other API misuse"); WAL lets each thread read while one writes."""
    global _conn, _gen
    path = str(get_settings().db_path)
    with _lock:
        if _conn is None or getattr(_local, "path", path) != path:
            _gen += 1
            _conn = _open(path, schema=True)
            _local.c, _local.gen, _local.path = _conn, _gen, path
            return _conn
    if getattr(_local, "c", None) is None or _local.gen != _gen or _local.path != path:
        _local.c, _local.gen, _local.path = _open(path, schema=False), _gen, path
    return _local.c


class Store:
    """Small key-value store (Codex thread ids, settings) plus the audit log."""

    def get(self, key: str):
        row = conn().execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def set(self, key: str, value) -> None:
        conn().execute(
            "INSERT INTO kv(key,value,updated) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
            (key, json.dumps(value), time.time()),
        )

    def audit(self, actor: str, action: str, subject: str | None = None, detail: dict | None = None) -> None:
        conn().execute(
            "INSERT INTO audit(ts,actor,action,subject,detail) VALUES(?,?,?,?,?)",
            (time.time(), actor, action, subject, json.dumps(detail or {})),
        )

    def log_llm(self, provider, model, purpose, ok, ms, error=None) -> None:
        conn().execute(
            "INSERT INTO llm_calls(ts,provider,model,purpose,ok,ms,error) VALUES(?,?,?,?,?,?,?)",
            (time.time(), provider, model, purpose, int(ok), ms, error),
        )


store = Store()
