"""Investment ideas, their immutable event log, and Nabd's institutional memory.

An idea moves through stages: idea → screening → research → fit → stress → committee → position → closed.
Every change is appended to idea_events (never updated or deleted), which is the audit trail. The memory index
(SQLite FTS5) holds each idea's thesis, research, committee decision and rationale, exit and lesson, so later
ideas can retrieve what was looked at before and what was decided.
"""

from __future__ import annotations

import json
import time

from ..core.bus import bus
from ..core.db import conn

STAGES = ["idea", "screening", "research", "fit", "stress", "committee", "position", "closed"]
STAGE_LABELS = {"idea": "Idea", "screening": "Screening", "research": "Research", "fit": "Portfolio fit",
                "stress": "Stress", "committee": "Committee", "position": "Monitoring", "closed": "Closed"}
JSON_FIELDS = ("thesis", "basket", "research", "fit", "stress", "committee", "exit_plan", "position", "memory_hits",
               "proposal")

SQL = """
CREATE TABLE IF NOT EXISTS ideas (
  id TEXT PRIMARY KEY, seq INTEGER NOT NULL, title TEXT, text TEXT NOT NULL, horizon TEXT NOT NULL,
  owner TEXT, stage TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created REAL NOT NULL, updated REAL NOT NULL,
  funding TEXT DEFAULT 'equity', thesis TEXT, basket TEXT, research TEXT, fit TEXT, stress TEXT, committee TEXT,
  exit_plan TEXT, position TEXT, memory_hits TEXT, seeded INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS idea_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, idea_id TEXT NOT NULL, ts REAL NOT NULL, actor TEXT NOT NULL,
  stage TEXT, action TEXT NOT NULL, detail TEXT
);
CREATE INDEX IF NOT EXISTS idea_events_idea ON idea_events(idea_id, ts);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(idea_id UNINDEXED, kind UNINDEXED, ts UNINDEXED, text);
"""
_ready = False


def _init():
    global _ready
    if not _ready:
        conn().executescript(SQL)
        cols = {r["name"] for r in conn().execute("PRAGMA table_info(ideas)")}
        if "proposal" not in cols:  # added after phase 7: what Nabd proposes to look at
            conn().execute("ALTER TABLE ideas ADD COLUMN proposal TEXT")
        _ready = True


def _row(r) -> dict:
    d = dict(r)
    for f in JSON_FIELDS:
        d[f] = json.loads(d[f]) if d.get(f) else None
    d["stage_label"] = STAGE_LABELS.get(d["stage"], d["stage"])
    return d


def _short(text: str, n: int = 70) -> str:
    """Placeholder title until the thesis names the idea: whole words, with an ellipsis."""
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def create(text: str, horizon: str, owner: str = "Investment team", seeded: bool = False) -> dict:
    _init()
    seq = (conn().execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM ideas").fetchone()[0])
    idea_id = f"IDEA-{seq:04d}"
    now = time.time()
    conn().execute("INSERT INTO ideas(id,seq,title,text,horizon,owner,stage,created,updated,seeded) "
                   "VALUES(?,?,?,?,?,?, 'idea', ?, ?, ?)",
                   (idea_id, seq, _short(text), text, horizon, owner, now, now, int(seeded)))
    log(idea_id, owner, "idea", "created", {"text": text, "horizon": horizon})
    remember(idea_id, "idea", text)
    return get(idea_id)


def get(idea_id: str) -> dict | None:
    _init()
    r = conn().execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
    return _row(r) if r else None


def all_ideas(include_deleted: bool = False) -> list[dict]:
    _init()
    sql = "SELECT * FROM ideas" + ("" if include_deleted else " WHERE status != 'deleted'") + " ORDER BY created DESC"
    return [_row(r) for r in conn().execute(sql)]


def delete(idea_id: str, actor: str, reason: str = "") -> dict:
    """Remove an idea from the pipeline. The row and its audit trail are kept (status 'deleted') so the record of
    what was considered survives; it is hidden from lists, memory search and monitoring."""
    _init()
    conn().execute("UPDATE ideas SET status='deleted', updated=? WHERE id=?", (time.time(), idea_id))
    conn().execute("DELETE FROM memory_fts WHERE idea_id=?", (idea_id,))
    log(idea_id, actor, None, "deleted", {"reason": reason})
    bus.publish("idea.updated", idea_id=idea_id, stage="deleted", action="deleted")
    return {"id": idea_id, "status": "deleted"}


def update(idea_id: str, actor: str, action: str, *, stage: str | None = None, status: str | None = None,
           **fields) -> dict:
    """Set fields (JSON fields are serialised), optionally move stage, log the event, notify the stream."""
    _init()
    sets, args = ["updated=?"], [time.time()]
    for k, v in fields.items():
        sets.append(f"{k}=?")
        args.append(json.dumps(v, default=str) if k in JSON_FIELDS else v)
    if stage:
        sets.append("stage=?")
        args.append(stage)
    if status:
        sets.append("status=?")
        args.append(status)
    conn().execute(f"UPDATE ideas SET {', '.join(sets)} WHERE id=?", (*args, idea_id))
    idea = get(idea_id)
    log(idea_id, actor, idea["stage"], action, {k: v for k, v in fields.items() if k not in ("research", "stress")})
    bus.publish("idea.updated", idea_id=idea_id, stage=idea["stage"], action=action)
    return idea


def log(idea_id: str, actor: str, stage: str | None, action: str, detail: dict | None = None) -> None:
    conn().execute("INSERT INTO idea_events(idea_id,ts,actor,stage,action,detail) VALUES(?,?,?,?,?,?)",
                   (idea_id, time.time(), actor, stage, action, json.dumps(detail or {}, default=str)[:20000]))


def events(idea_id: str) -> list[dict]:
    _init()
    rows = conn().execute("SELECT * FROM idea_events WHERE idea_id=? ORDER BY ts", (idea_id,))
    return [{**dict(r), "detail": json.loads(r["detail"] or "{}")} for r in rows]


# ---------------- memory ----------------
def remember(idea_id: str, kind: str, text: str) -> None:
    _init()
    if text:
        conn().execute("INSERT INTO memory_fts(idea_id, kind, ts, text) VALUES(?,?,?,?)",
                       (idea_id, kind, time.time(), text[:8000]))


def search_memory(query: str, exclude: str | None = None, limit: int = 6) -> list[dict]:
    """Full-text search over past ideas, research, decisions and lessons (BM25 ranking)."""
    _init()
    terms = [t for t in "".join(c if c.isalnum() else " " for c in query.lower()).split() if len(t) > 2]
    if not terms:
        return []
    # prefix match ("japan*" finds "Japanese"); FTS5 needs each term quoted before the star
    q = " OR ".join(f'"{t}"*' if len(t) >= 4 else f'"{t}"' for t in dict.fromkeys(terms))
    rows = conn().execute(
        "SELECT idea_id, kind, ts, snippet(memory_fts, 3, '[', ']', ' … ', 18) AS snippet, bm25(memory_fts) AS score "
        "FROM memory_fts WHERE memory_fts MATCH ? ORDER BY score LIMIT ?", (q, limit * 3)).fetchall()
    out, seen = [], set()
    for r in rows:
        if r["idea_id"] == exclude or (r["idea_id"], r["kind"]) in seen:
            continue
        seen.add((r["idea_id"], r["kind"]))
        idea = get(r["idea_id"])
        out.append({"idea_id": r["idea_id"], "title": idea["title"] if idea else None,
                    "stage": idea["stage_label"] if idea else None, "kind": r["kind"],
                    "decision": ((idea.get("committee") or {}).get("decision") or {}).get("decision") if idea else None,
                    "when": time.strftime("%d %b %Y", time.localtime(r["ts"])), "snippet": r["snippet"],
                    "seeded": bool(idea and idea.get("seeded"))})
        if len(out) >= limit:
            break
    return out


def active_positions() -> dict[str, float]:
    """Sum of active weights of every approved idea being monitored (fractions of the portfolio)."""
    from ..ml.portfolio.risk import active_from_tilt

    total: dict[str, float] = {}
    for idea in all_ideas():
        if idea["stage"] == "position" and idea.get("basket"):
            tilt = {b["symbol"]: b["weight_pct"] for b in idea["basket"]["items"] if not b.get("research_only") and b["weight_pct"]}
            for s, w in active_from_tilt(tilt, idea.get("funding") or "equity").items():
                total[s] = total.get(s, 0.0) + w
    return total
