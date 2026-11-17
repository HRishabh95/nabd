"""Who is asking: a persona that shapes emphasis, and a memory the user controls.

The persona changes what an answer leads with (a commodity desk wants the book and the risk budget; an economist wants
data sources and uncertainty), never the evidence. Memory holds short facts the user chose to save ("we report in
AED", "I sit on the MRMC"); every item is listed, editable and deletable, and is sent with each question so the
answer can use it. Nothing is remembered unless the user saves it.
"""

from __future__ import annotations

import time
import uuid

from ..core.db import conn

PERSONAS = {
    "investment": {"label": "Investment team (commodities)",
                   "style": "Lead with what it means for the commodity book: positions, the risk budget, sizing and "
                            "risks. Use AED or USD as the user prefers."},
    "economics": {"label": "Economics and research",
                  "style": "Lead with the economics: data sources and their dates, methods and uncertainty. Name the "
                           "source of every series."},
    "aml": {"label": "AML and fraud",
            "style": "Lead with accounts, transfers and patterns, and what an investigator should check next."},
    "risk": {"label": "Risk and model governance",
             "style": "Lead with limits, tests and their results, and what the model cannot show. Be conservative."},
    "executive": {"label": "Executive",
                  "style": "Answer in two or three plain sentences first, with at most two key numbers, then details "
                           "only if asked. No jargon."},
}
SQL = """
CREATE TABLE IF NOT EXISTS user_profile (id TEXT PRIMARY KEY, role TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS user_memory (id TEXT PRIMARY KEY, ts REAL NOT NULL, text TEXT NOT NULL, source TEXT);
"""
_ready = False


def _init():
    global _ready
    if not _ready:
        conn().executescript(SQL)
        _ready = True


def profile() -> dict:
    _init()
    r = conn().execute("SELECT role FROM user_profile WHERE id='me'").fetchone()
    role = r["role"] if r and r["role"] in PERSONAS else "investment"
    return {"role": role, **PERSONAS[role], "personas": {k: v["label"] for k, v in PERSONAS.items()}, "memory": memory()}


def set_role(role: str) -> dict:
    _init()
    if role not in PERSONAS:
        raise KeyError(role)
    conn().execute("INSERT OR REPLACE INTO user_profile VALUES('me', ?, ?)", (role, time.time()))
    return profile()


def memory() -> list[dict]:
    _init()
    return [dict(r) for r in conn().execute("SELECT id, ts, text, source FROM user_memory ORDER BY ts DESC")]


def remember(text: str, source: str = "user") -> list[dict]:
    _init()
    conn().execute("INSERT INTO user_memory VALUES(?,?,?,?)", (f"mem-{uuid.uuid4().hex[:8]}", time.time(), text.strip()[:300], source))
    return memory()


def forget(mem_id: str) -> list[dict]:
    _init()
    conn().execute("DELETE FROM user_memory WHERE id=?", (mem_id,))
    return memory()


def for_prompt() -> dict:
    p = profile()
    return {"role": p["label"], "how_to_answer": p["style"], "remembered_about_the_user": [m["text"] for m in p["memory"][:20]]}
