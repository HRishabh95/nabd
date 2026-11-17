"""Look-through: what the equity mandates hold, name by name, so an idea can underweight a single company.

A reserve portfolio does not short. But it holds NVIDIA, Microsoft and the rest through its index mandates (ESGU,
ESGD), so holding *less* of one than the benchmark is an ordinary active underweight, as long as the cut never
exceeds what is held indirectly. That indirect weight is the mandate's weight in the portfolio times the company's
weight in the mandate.

Source: the funds' official holdings files. iShares publishes them on each fund's page ("Detailed Holdings and
Analytics", CSV) but serves them only through its website, so an analyst downloads them and saves them as
`data/manual/ESGU_holdings.csv` and `data/manual/ESGD_holdings.csv`. Without them, single names can be researched
but not cut, and the screen says so.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from ..core.config import get_settings
from ..data.universe import BY_SYMBOL, UNIVERSE

MANDATES = {"ESGU": "iShares ESG Aware MSCI USA ETF", "ESGD": "iShares ESG Aware MSCI EAFE ETF"}
# Where an analyst gets each file: the fund page on ishares.com, "Detailed Holdings and Analytics" → download.
SOURCE_PAGE = {"ESGU": "https://www.ishares.com/us/products/286007/", "ESGD": None}  # ESGD: search "ESGD" on ishares.com
_SUFFIX = re.compile(r"\b(inc|corp|corporation|co|company|plc|nv|n\.v|sa|ag|se|asa|ltd|limited|group|holdings?|hldgs|"
                     r"class [abc]|cl [abc]|adr|reg|the|financial group|financial)\b")


def _norm(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", name.lower().replace("&", " and "))
    return re.sub(r"\s+", " ", _SUFFIX.sub(" ", s)).strip()


def parse_ishares(text: str) -> tuple[dict[str, dict], str | None]:
    """Holdings from an iShares CSV: {ticker: {name, weight}} with weight as a fraction, plus the as-of date.
    The file has a few lines about the fund, then a table whose header starts with Ticker and has Weight (%)."""
    lines = text.splitlines()
    as_of = None
    for ln in lines[:12]:
        m = re.match(r'\s*"?Fund Holdings as of"?\s*,\s*"?([^"]+)"?', ln)
        if m:
            as_of = m.group(1).strip()
    start = next((i for i, ln in enumerate(lines) if ln.lstrip('"').startswith("Ticker") and "Weight" in ln), None)
    if start is None:
        raise ValueError("not an iShares holdings file: no Ticker / Weight (%) table")
    out: dict[str, dict] = {}
    for row in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        t, w = (row.get("Ticker") or "").strip(), (row.get("Weight (%)") or "").replace(",", "").strip()
        if not t or not w or (row.get("Asset Class") or "Equity").strip().lower() != "equity":
            continue
        try:
            out[t] = {"name": (row.get("Name") or "").strip(), "weight": float(w) / 100}
        except ValueError:
            continue  # footer lines
    return out, as_of


def _match(holdings: dict[str, dict]) -> dict[str, float]:
    """Map a fund's holdings to Nabd's instruments: by ticker, then by company name (foreign listings and ADRs)."""
    names = {_norm(i.name): i.symbol for i in UNIVERSE if i.kind == "equity"}
    out: dict[str, float] = {}
    for ticker, h in holdings.items():
        sym = ticker if ticker in BY_SYMBOL and BY_SYMBOL[ticker].kind == "equity" else None
        if not sym:
            n = _norm(h["name"])
            sym = names.get(n) or next((s for k, s in names.items() if k and (n.startswith(k + " ") or n == k)), None)
        if sym:
            out[sym] = out.get(sym, 0.0) + h["weight"]
    return out


def load(directory: Path | None = None) -> dict:
    """{mandate: {loaded, as_of, weights: {symbol: fraction of the fund}, holdings: n}} for each equity mandate."""
    d = directory or (get_settings().data_dir / "manual")
    out = {}
    for m in MANDATES:
        f = d / f"{m}_holdings.csv"
        if not f.exists():
            out[m] = {"loaded": False, "file": str(f.name), "source": SOURCE_PAGE[m]}
            continue
        try:
            hold, as_of = parse_ishares(f.read_text(encoding="utf-8-sig", errors="replace"))
            out[m] = {"loaded": True, "as_of": as_of, "holdings": len(hold), "weights": _match(hold), "source": SOURCE_PAGE[m]}
        except ValueError as exc:
            out[m] = {"loaded": False, "file": str(f.name), "error": str(exc), "source": SOURCE_PAGE[m]}
    return out


def indirect(held_pct: dict[str, float], lt: dict | None = None) -> dict[str, float]:
    """Each company's indirect weight in the portfolio (% of portfolio) through the mandates held."""
    lt = lt if lt is not None else load()
    out: dict[str, float] = {}
    for m, info in lt.items():
        if not info.get("loaded") or not held_pct.get(m):
            continue
        for s, w in info["weights"].items():
            out[s] = out.get(s, 0.0) + held_pct[m] * w
    return {s: round(v, 4) for s, v in out.items()}
