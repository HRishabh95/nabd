"""One alert store for every module: data, models, forecasting, fraud, investment.

An alert is raised once per (module, subject, rule) while open, streamed to every page, and resolved automatically
when its condition clears. Acknowledging records who looked at it. Each alert carries a link to where it is acted on.
"""

from __future__ import annotations

import json
import time

from ..core.bus import bus
from ..core.db import conn

SQL = """
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, idea_id TEXT, rule TEXT NOT NULL, severity TEXT NOT NULL,
  title TEXT NOT NULL, detail TEXT, status TEXT NOT NULL DEFAULT 'open', acked_by TEXT, acked_ts REAL
);
"""
MODULES = {"data": "Data", "models": "Models", "forecasting": "Forecasting", "fraud": "Fraud network",
           "investment": "Investment"}
_ready = False


def _init():
    global _ready
    if _ready:
        return
    c = conn()
    c.executescript(SQL)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(alerts)")}
    for col, ddl in (("module", "TEXT DEFAULT 'investment'"), ("subject", "TEXT"), ("link", "TEXT"),
                     ("resolved_ts", "REAL")):
        if col not in cols:
            c.execute(f"ALTER TABLE alerts ADD COLUMN {col} {ddl}")
    c.execute("UPDATE alerts SET subject = idea_id WHERE subject IS NULL AND idea_id IS NOT NULL")
    _ready = True


def raise_alert(module: str, subject: str | None, rule: str, severity: str, title: str, detail: dict | None = None,
                link: str | None = None, idea_id: str | None = None) -> bool:
    """Open an alert unless the same one is already open. Severity: high, medium or info."""
    _init()
    if conn().execute("SELECT 1 FROM alerts WHERE module=? AND subject IS ? AND rule=? AND status IN ('open','acknowledged')",
                      (module, subject, rule)).fetchone():
        return False
    cur = conn().execute(
        "INSERT INTO alerts(ts,idea_id,rule,severity,title,detail,module,subject,link) VALUES(?,?,?,?,?,?,?,?,?)",
        (time.time(), idea_id, rule, severity, title, json.dumps(detail or {}, default=str), module, subject, link))
    bus.publish("alert", id=cur.lastrowid, module=module, subject=subject, rule=rule, severity=severity, title=title,
                link=link, idea_id=idea_id)
    return True


def resolve(module: str, subject: str | None, rule: str) -> int:
    _init()
    cur = conn().execute("UPDATE alerts SET status='resolved', resolved_ts=? WHERE module=? AND subject IS ? AND rule=? "
                         "AND status IN ('open','acknowledged')", (time.time(), module, subject, rule))
    if cur.rowcount:
        bus.publish("alert.resolved", module=module, subject=subject, rule=rule)
    return cur.rowcount


def ack(alert_id: int, actor: str) -> None:
    _init()
    conn().execute("UPDATE alerts SET status='acknowledged', acked_by=?, acked_ts=? WHERE id=? AND status='open'",
                   (actor, time.time(), alert_id))
    bus.publish("alert.acked", id=alert_id)


def listing(status: str | None = None, module: str | None = None, limit: int = 100) -> list[dict]:
    _init()
    sql, args = "SELECT * FROM alerts WHERE 1=1", []
    if status == "active":
        sql += " AND status IN ('open','acknowledged')"
    elif status:
        sql += " AND status=?"
        args.append(status)
    if module:
        sql += " AND module=?"
        args.append(module)
    rows = conn().execute(sql + " ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, ts DESC "
                          "LIMIT ?", (*args, limit))
    return [{**dict(r), "detail": json.loads(r["detail"] or "{}"), "module_label": MODULES.get(r["module"], r["module"])}
            for r in rows]


def counts() -> dict:
    _init()
    rows = conn().execute("SELECT module, severity, COUNT(*) n FROM alerts WHERE status='open' GROUP BY module, severity")
    out: dict = {}
    for r in rows:
        out.setdefault(r["module"], {})[r["severity"]] = r["n"]
    return out
