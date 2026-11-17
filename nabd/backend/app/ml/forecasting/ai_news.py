"""AI news signals for the nowcast: an LLM reads UAE business headlines and scores what each one says about activity.

Corpus: GDELT GKG 2.1 bulk files (open, published every 15 minutes since 2015). For each month since 2020, a fixed
random sample of 15-minute files spread over the days and hours of the month; only headlines about the UAE economy
are kept (a UAE place in the title, or a UAE news site writing about a UAE location, plus an economic theme or term).
Raw files are read in memory and discarded. New headlines come from the live 15-minute feed (`news_items`).

Labelling is blind to dates. Headlines from different months are shuffled together and shown without dates or
sources, and the model labels each one from its text alone: relevant or not, sector, and what it implies for UAE
activity (-2 to +2). Shuffling and hiding dates keeps the model from reading a headline in the light of what it knows
happened later, which is the main look-ahead risk when an LLM scores historical news.

Series: for each day, the average direction of the relevant headlines; the nowcast takes the monthly mean, published
with a one-day lag. `ai:nonoil` covers every sector but oil and gas; `ai:oil` covers oil and gas.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import re
import time
import zipfile
from typing import Literal

import httpx
import pandas as pd
from pydantic import BaseModel, Field

from ...core.db import conn
from ...core.db import store as kv
from ...data import store
from ...data.connectors import gkg

PER_MONTH = 16  # 15-minute files sampled per month for the history (about 40 UAE business headlines a month)
START = "2020-01"
SECTORS = ("trade_logistics", "tourism_aviation", "real_estate_construction", "finance_banking", "retail_consumer",
           "industry_manufacturing", "government_investment", "technology", "oil_gas", "other")
SECTOR_LABEL = {"trade_logistics": "Trade and logistics", "tourism_aviation": "Tourism and aviation",
                "real_estate_construction": "Property and construction", "finance_banking": "Finance and banking",
                "retail_consumer": "Retail and consumers", "industry_manufacturing": "Industry",
                "government_investment": "Government and investment", "technology": "Technology",
                "oil_gas": "Oil and gas", "other": "Other"}
UAE_PLACE = re.compile(r"\buae\b|u\.a\.e|emirat|dubai|abu dhabi|sharjah|ajman|ras al khaimah|fujairah|"
                       r"الإمارات|دبي|أبوظبي|الشارقة", re.I)
UAE_SITES = ("gulfnews.com", "khaleejtimes.com", "thenationalnews.com", "wam.ae", "zawya.com", "arabianbusiness.com",
             "gulftoday.ae", "emirates247.com", "gulfbusiness.com", "albayan.ae", "alkhaleej.ae", "emaratalyoum.com",
             "alittihad.ae", "argaam.com")
ECON_TERM = re.compile(r"econom|gdp|growth|trade|export|import|port|shipping|logistic|airline|airport|aviation|"
                       r"touris|hotel|visitor|propert|real estate|housing|construct|bank|lend|loan|credit|invest|"
                       r"fund|ipo|stock|shares|bourse|market|oil|opec|adnoc|crude|gas|refin|retail|consumer|"
                       r"spending|sales|developer|pmi|inflation|price|jobs|employ|hiring|business|compan|profit|revenue|deal|"
                       r"billion|million|dirham|aed|اقتصاد|نمو|تجارة|استثمار|نفط|عقار|سياحة|بنك", re.I)

SQL = """
CREATE TABLE IF NOT EXISTS news_archive (
  id TEXT PRIMARY KEY, month TEXT NOT NULL, ts REAL NOT NULL, title TEXT NOT NULL, source TEXT, url TEXT, lang TEXT
);
CREATE INDEX IF NOT EXISTS news_archive_month ON news_archive(month);
CREATE TABLE IF NOT EXISTS news_archive_files (file TEXT PRIMARY KEY, kept INTEGER, processed REAL);
CREATE TABLE IF NOT EXISTS news_labels (
  id TEXT PRIMARY KEY, relevant INTEGER NOT NULL, sector TEXT, direction INTEGER, model TEXT, labelled REAL
);
"""
_ready = False


def _init():
    global _ready
    if not _ready:
        conn().executescript(SQL)
        _ready = True


def _key(month: str, title: str) -> str:
    norm = re.sub(r"[^a-z0-9؀-ۿ]+", " ", title.lower()).strip()
    return hashlib.sha1(f"{month}|{norm}".encode()).hexdigest()[:16]


def select(df: pd.DataFrame) -> pd.DataFrame:
    """UAE business headlines from one parsed GKG file: title, source, url, lang."""
    c = gkg.COLS
    title = gkg._title(df[c["extras"]]).str.strip()
    src = df[c["source"]].str.lower()
    themes, locs = df[c["themes"]], df[c["locations"]]
    uae_site = src.apply(lambda s: any(s.endswith(d) for d in UAE_SITES))
    about_uae = title.str.contains(UAE_PLACE) | (uae_site & locs.str.contains("#AE", regex=False))
    econ = themes.str.contains("ECON_", regex=False) | title.str.contains(ECON_TERM)
    keep = about_uae & econ & (title.str.len() >= 25)
    lang = df[c["translation"]].str.extract(r"srclc:(\w+)", expand=False).fillna("eng")
    return pd.DataFrame({"title": title[keep], "source": src[keep], "url": df.loc[keep, c["url"]],
                         "lang": lang[keep]})


def _stamps(month: pd.Period, n: int) -> list[pd.Timestamp]:
    """A fixed random sample of 15-minute slots in the month: raising `n` later adds files without changing the rest."""
    slots = pd.date_range(month.start_time, month.end_time.floor("15min"), freq="15min")
    order = random.Random(month.ordinal).sample(range(len(slots)), len(slots))
    now = pd.Timestamp.now() - pd.Timedelta(hours=2)
    return [slots[i] for i in order if slots[i] < now][:n]


def _save(rows: pd.DataFrame, ts: float) -> int:
    month = pd.Timestamp(ts, unit="s").strftime("%Y-%m")
    recs = [(_key(month, r.title), month, ts, r.title, r.source, r.url, r.lang) for r in rows.itertuples()]
    cur = conn().executemany("INSERT OR IGNORE INTO news_archive VALUES(?,?,?,?,?,?,?)", recs)
    return cur.rowcount or 0


async def backfill(start: str = START, per_month: int = PER_MONTH, progress=None) -> dict:
    """Download the sampled GKG files and keep the UAE business headlines. Resumable: done files are skipped."""
    _init()
    months = pd.period_range(start, pd.Timestamp.now().to_period("M"), freq="M")
    done_files = {r[0] for r in conn().execute("SELECT file FROM news_archive_files")}
    urls = [f"{gkg.BASE}/{s.strftime('%Y%m%d%H%M%S')}.gkg.csv.zip" for m in months for s in _stamps(m, per_month)]
    todo = [u for u in urls if u.rsplit("/", 1)[-1] not in done_files]
    kept = done = 0
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=90, headers={"User-Agent": "NabdPOC/0.1"}, follow_redirects=True) as c:
        async def one(u: str):
            nonlocal kept, done
            name = u.rsplit("/", 1)[-1]
            async with sem:
                for attempt in range(3):
                    try:
                        r = await c.get(u)
                        n = 0
                        if r.status_code != 404:
                            r.raise_for_status()
                            rows = select(await asyncio.to_thread(gkg.parse, r.content))
                            n = _save(rows, gkg._file_ts(u))
                        conn().execute("INSERT OR REPLACE INTO news_archive_files VALUES(?,?,?)", (name, n, time.time()))
                        kept += n
                        break
                    except (httpx.HTTPError, zipfile.BadZipFile, ValueError):
                        await asyncio.sleep(3 * (attempt + 1))
            done += 1
            if progress:
                progress(done, len(todo), f"{name}: {kept} headlines kept")
        await asyncio.gather(*(one(u) for u in todo))
    return {"files": len(todo), "kept": kept, "total": archive_size()}


def add_recent() -> int:
    """Copy UAE business headlines from the live 15-minute feed (kept 14 days there) into the archive."""
    _init()
    rows = conn().execute("SELECT DISTINCT url, ts, title, source, lang FROM news_items WHERE theme='uae_economy' "
                          "AND title IS NOT NULL").fetchall()
    n = 0
    for url, ts, title, source, lang in rows:
        if not title or len(title) < 25 or not (ECON_TERM.search(title) or UAE_PLACE.search(title)):
            continue
        month = pd.Timestamp(ts, unit="s").strftime("%Y-%m")
        cur = conn().execute("INSERT OR IGNORE INTO news_archive VALUES(?,?,?,?,?,?,?)",
                             (_key(month, title), month, ts, title, source, url, lang or "eng"))
        n += cur.rowcount or 0
    return n


def archive_size() -> int:
    _init()
    return conn().execute("SELECT COUNT(*) FROM news_archive").fetchone()[0]


# ---- labelling -------------------------------------------------------------------------------------------------

class HeadlineLabel(BaseModel):
    i: int = Field(description="The headline's number")
    rel: bool = Field(description="True if it reports or implies something about current UAE economic activity")
    sector: Literal[SECTORS] = Field(description="Main sector")  # type: ignore[valid-type]
    dir: int = Field(ge=-2, le=2, description="Implication for UAE activity in that sector now: -2 to +2")


class Labels(BaseModel):
    items: list[HeadlineLabel]


RULES = """You label news headlines for a central bank's GDP nowcast for the United Arab Emirates.
For each numbered headline decide, from its text alone:
- rel: true ONLY if it reports something that is happening to economic activity inside the UAE now: volumes,
  traffic, sales, output, lending, hiring or layoffs, project starts, openings, closures, disruptions, company or
  sector results, oil and gas production. False for: appointments, conferences, exhibitions and award ceremonies;
  opinion and advice; product launches without volumes; consumer price tips (for example gold prices for shoppers);
  disputes or events of foreign companies that only mention the UAE; plans, MoUs and talks with no activity yet;
  lifestyle, crime, sport and politics.
- sector: the main sector it is about.
- dir: the direction of that activity now. -2 clearly weaker (closures, sharp falls, disruption), -1 somewhat weaker,
  0 mixed or unclear, +1 somewhat stronger, +2 clearly stronger (records, strong growth, large capacity opening).
Headlines are in English or Arabic. They are shuffled and undated: judge only what each headline says. Do not
guess when it was written and do not use knowledge of later events. Return one item for every headline."""


async def label(batch: int = 60, concurrency: int = 3, limit: int | None = None, progress=None) -> dict:
    """Label every unlabelled headline, in shuffled, undated batches."""
    from ...llm.gateway import gateway

    _init()
    rows = conn().execute("SELECT a.id, a.title FROM news_archive a LEFT JOIN news_labels l ON a.id=l.id "
                          "WHERE l.id IS NULL").fetchall()
    random.Random(7).shuffle(rows)
    rows = rows[:limit] if limit else rows
    batches = [rows[i:i + batch] for i in range(0, len(rows), batch)]
    sem = asyncio.Semaphore(concurrency)
    stats = {"batches": len(batches), "labelled": 0, "failed": 0}

    async def one(b):
        prompt = "Label these headlines.\n\n" + "\n".join(f"{k}. {t}" for k, (_, t) in enumerate(b, 1))
        async with sem:
            try:
                res = await gateway.run("news-label", RULES, prompt, schema=Labels, timeout_seconds=240)
                out = res.parsed if isinstance(res.parsed, Labels) else Labels.model_validate_json(res.text)
            except Exception:  # noqa: BLE001 - a failed batch stays unlabelled and is retried next time
                stats["failed"] += 1
                return
        recs = [(b[x.i - 1][0], int(x.rel), x.sector, x.dir, res.model or "codex", time.time())
                for x in out.items if 1 <= x.i <= len(b)]
        conn().executemany("INSERT OR REPLACE INTO news_labels VALUES(?,?,?,?,?,?)", recs)
        stats["labelled"] += len(recs)
        if progress:
            progress(stats["labelled"], len(rows), f"{stats['labelled']} of {len(rows)} headlines labelled")

    await asyncio.gather(*(one(b) for b in batches))
    return stats


class Reason(BaseModel):
    i: int
    why: str = Field(description="One short phrase (at most 12 words) giving the headline's evidence for its label")


class Reasons(BaseModel):
    items: list[Reason]


REASON_RULES = """Each numbered headline below already has a label: its sector and a direction for UAE activity (-2 clearly
weaker to +2 clearly stronger). For each one, write the short phrase from or about the headline that justifies that
label, for example "record passenger numbers at Dubai airport" or "check-in services suspended". Do not change or
question the label; at most 12 words; no numbers that are not in the headline."""


async def explain_labels(batch: int = 60, concurrency: int = 3, progress=None) -> dict:
    """Write a one-line reason for each relevant headline's existing label (scores are not changed)."""
    from ...llm.gateway import gateway

    _init()
    cols = {r[1] for r in conn().execute("PRAGMA table_info(news_labels)")}
    if "reason" not in cols:
        conn().execute("ALTER TABLE news_labels ADD COLUMN reason TEXT")
    rows = conn().execute("SELECT a.id, a.title, l.sector, l.direction FROM news_archive a JOIN news_labels l ON a.id=l.id "
                          "WHERE l.relevant=1 AND (l.reason IS NULL OR l.reason='')").fetchall()
    batches = [rows[i:i + batch] for i in range(0, len(rows), batch)]
    sem = asyncio.Semaphore(concurrency)
    done = {"n": 0, "failed": 0}

    async def one(b):
        prompt = "\n".join(f"{k}. [{SECTOR_LABEL.get(sec, sec)}, {d:+d}] {t}" for k, (_, t, sec, d) in enumerate(b, 1))
        async with sem:
            try:
                res = await gateway.run("news-reason", REASON_RULES, prompt, schema=Reasons, timeout_seconds=240)
                out = res.parsed if isinstance(res.parsed, Reasons) else Reasons.model_validate_json(res.text)
            except Exception:  # noqa: BLE001
                done["failed"] += 1
                return
        conn().executemany("UPDATE news_labels SET reason=? WHERE id=?",
                           [(x.why.strip()[:160], b[x.i - 1][0]) for x in out.items if 1 <= x.i <= len(b)])
        done["n"] += len(out.items)
        if progress:
            progress(done["n"], len(rows), f"{done['n']} of {len(rows)} reasons written")

    await asyncio.gather(*(one(b) for b in batches))
    return {"rows": len(rows), **done}


# ---- series ----------------------------------------------------------------------------------------------------

def labelled() -> pd.DataFrame:
    _init()
    cols = {r[1] for r in conn().execute("PRAGMA table_info(news_labels)")}
    reason = ", l.reason" if "reason" in cols else ", NULL AS reason"
    return pd.read_sql_query("SELECT a.id, a.month, a.ts, a.title, a.source, a.url, a.lang, l.relevant, l.sector, "
                             "l.direction" + reason + " FROM news_archive a JOIN news_labels l ON a.id=l.id", conn())


def build_series() -> list[dict]:
    """Daily counts of relevant headlines (stronger, weaker, all), written as `ai:nonoil` and `ai:oil`. The nowcast
    turns them into a monthly diffusion index (data.diffusion); `net` keeps the plain average for reference."""
    df = labelled()
    df = df[df.relevant == 1]
    out = []
    for sid, part, title in (("ai:nonoil", df[df.sector != "oil_gas"], "AI news signal: non-oil activity"),
                             ("ai:oil", df[df.sector == "oil_gas"], "AI news signal: oil and gas")):
        if part.empty:
            continue
        d = part.assign(date=pd.to_datetime(part.ts, unit="s").dt.normalize())
        daily = d.groupby("date").agg(up=("direction", lambda x: int((x > 0).sum())),
                                      down=("direction", lambda x: int((x < 0).sum())),
                                      n=("direction", "size"), net=("direction", "mean")).reset_index()
        out.append(store.write_series("ai_news", sid, daily, kind="news", title=title, freq="daily",
                                      meta={"method": "LLM labels of UAE business headlines, blind to dates; "
                                                      "monthly diffusion index with shrinkage"}))
    kv.set("ai_news:built", {"ts": time.time(), "headlines": int(len(df))})
    return out


def monthly_summary() -> list[dict]:
    """Per month: headlines kept, relevant, and the balance (stronger minus weaker, %), overall and by sector."""
    from .data import SHRINK

    df = labelled()
    if df.empty:
        return []

    def bal(x: pd.DataFrame) -> float | None:
        return round(100 * (int((x.direction > 0).sum()) - int((x.direction < 0).sum())) / (len(x) + SHRINK), 1) if len(x) else None
    out = []
    for m, g in df.groupby("month"):
        r = g[g.relevant == 1]
        out.append({"month": m, "headlines": int(len(g)), "relevant": int(len(r)),
                    "nonoil": bal(r[r.sector != "oil_gas"]), "oil": bal(r[r.sector == "oil_gas"]),
                    "up": int((r.direction > 0).sum()), "down": int((r.direction < 0).sum()),
                    "sectors": {s: {"n": int(len(x)), "balance": bal(x)} for s, x in r.groupby("sector")}})
    return out


def headlines(month: str, limit: int = 200) -> list[dict]:
    df = labelled()
    df = df[df.month == month].sort_values(["relevant", "direction"], ascending=[False, True])
    return [{"title": r.title, "source": r.source, "url": r.url, "lang": r.lang, "date":
             pd.Timestamp(r.ts, unit="s").strftime("%Y-%m-%d"), "relevant": bool(r.relevant), "sector": r.sector,
             "sector_label": SECTOR_LABEL.get(r.sector, r.sector), "direction": int(r.direction),
             "reason": r.reason if isinstance(r.reason, str) else None}
            for r in df.head(limit).itertuples()]


async def update(progress=None, backfill_history: bool = True) -> dict:
    """Bring the AI news signal up to date: fetch sampled files, add the live feed, label, rebuild the series."""
    t = time.time()
    got = await backfill(progress=progress) if backfill_history else {"kept": 0}
    recent = add_recent()
    lab = await label(progress=progress)
    series = build_series()
    out = {"new_from_files": got["kept"], "new_from_feed": recent, "labelled": lab["labelled"],
           "failed_batches": lab["failed"], "archive": archive_size(), "series": len(series),
           "seconds": round(time.time() - t, 1)}
    kv.set("ai_news:last", {"ts": time.time(), **out})
    return out
