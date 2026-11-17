"""`nabd seed`: bring an empty data folder to a working demo, step by step, printing what it does.

Idempotent: each step skips work that is already fresh. Order matters (models need data first).
"""

from __future__ import annotations

import asyncio
import time


def _step(name: str, fn):
    t = time.time()
    print(f"  → {name} …", flush=True)
    try:
        out = fn()
        print(f"    done in {time.time() - t:.0f}s {out if isinstance(out, str) else ''}", flush=True)
        return True
    except Exception as exc:  # keep going; the summary says what failed
        print(f"    FAILED: {type(exc).__name__}: {exc}"[:300], flush=True)
        return False


def _report(results: list[dict], unit: str) -> str:
    """'(2 of 2 series)', or raise with each failure's reason so the step shows as failed."""
    bad = [r for r in results if not r.get("ok")]
    if bad:
        raise RuntimeError(f"{len(results) - len(bad)} of {len(results)} {unit} loaded; "
                           + "; ".join(f"{r.get('id')}: {str(r.get('error'))[:120]}" for r in bad))
    return f"({len(results)} of {len(results)} {unit})"


def seed(full: bool = False) -> int:
    from .core.db import conn
    from .core.db import store as kv
    from .data import refresh
    from .data.connectors import docs, fred, gkg, portwatch, yahoo
    from .data.universe import FRED_SERIES, UNIVERSE

    conn()
    print("Nabd seed: open data and first model runs", flush=True)
    titles = {i.symbol: i.name for i in UNIVERSE}

    def prices():
        r = asyncio.run(yahoo.refresh(list(titles), titles))
        return f"({sum(x['ok'] for x in r)} of {len(r)} instruments)"

    def news():
        r = asyncio.run(gkg.ingest_latest())
        return f"({r['articles']} articles)"

    def ranker():
        from .ml.portfolio import ranker as rk
        if rk.latest() and kv.get("ranker:trained_ts") and time.time() - kv.get("ranker:trained_ts") < 7 * 86400:
            return "(fresh, skipped)"
        out = rk.train()
        kv.set("ranker:trained_ts", time.time())
        return f"(IC {out['metrics']['mean_ic']:+.3f} over {out['metrics']['months']} months)"

    def fraud():
        from .ml.fraud import run as fr
        o = fr.run()
        e = o["methods"]["combined"]["eval"]
        return f"({e['cases']} cases, precision {e['precision']:.2f})"

    def nowcast():
        from .ml.forecasting import ai_eval
        o = ai_eval.run()
        v = o["targets"]["non_oil"]["latest"].get(o["targets"]["non_oil"]["pending"], {}).get("models", {})
        return f"(non-oil {o['targets']['non_oil']['pending']}: {(v.get('kalman_ai') or v.get('kalman') or {}).get('value')})"

    def monitor():
        from .invest import monitor as m
        from .monitoring import rules
        m.run_once()
        return f"({rules.run_once()})"

    steps = [
        ("Market prices, 10 years (Yahoo Finance)", prices),
        ("Macro series (FRED)", lambda: f"({sum(x['ok'] for x in asyncio.run(fred.refresh(FRED_SERIES)))} series)"),
        ("Markets: indices, rates, commodities, FX (Yahoo Finance)",
         lambda: f"({asyncio.run(refresh._markets(None))['ok']} of {len(refresh.MARKETS)} markets)"),
        ("Shipping: Hormuz transits and UAE ports (IMF PortWatch)", lambda: _report(asyncio.run(portwatch.refresh()), "series")),
        ("Central-bank releases (Fed, ECB, BoJ, BIS)", lambda: f"({asyncio.run(docs.refresh())['total']} documents)"),
        ("Latest world news (GDELT, 15-minute files)", news),
    ]
    if full:
        steps += [("News, last 30 days (GDELT sample)", lambda: str(asyncio.run(gkg.backfill(30, 4)))),
                  ("News history since 2019 (weekly sample, ~1 GB)", lambda: str(asyncio.run(gkg.history())))]
    steps += [("Return-ranking model (walk-forward)", ranker), ("Fraud network: generate and detect", fraud),
              ("GDP nowcast and backtest", nowcast), ("Monitoring check", monitor)]
    ok = [_step(n, f) for n, f in steps]
    print(f"Seed finished: {sum(ok)} of {len(ok)} steps succeeded.", flush=True)
    if not all(ok):
        print("Failed steps can be rerun with `nabd seed`; the app also refreshes data on its own schedule.")
    return 0 if all(ok) else 1
