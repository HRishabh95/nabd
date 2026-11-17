"""Screening: rank the universe against a parsed thesis, in the context of what the portfolio already holds.

Returns four things, all computed (the LLM only supplied the thesis fields):
- holdings: the equity the portfolio holds today (benchmark index lines plus approved ideas), each with its
  measured sensitivity (beta) to the idea's theme basket, so the team sees its current exposure to the idea;
- rows: instruments that match the thesis, with thesis fit, factors, the ML rank, liquidity, the SRI flag, and
  portfolio fit: correlation with the equity the portfolio holds and the tracking error each 1% would add;
- reduce: for reduce or hedge ideas, the holdings that can be cut (only down to zero; a reserve portfolio does
  not short), ranked by their exposure to the theme;
- protect: protective instruments ranked by their average return on the theme basket's worst days.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import store
from ..data.universe import BY_SYMBOL, UNIVERSE
from ..ml.portfolio import ranker, reserve, risk
from . import ideas, lookthrough

PROTECTIVE_TAGS = {"treasuries", "gold", "defensive", "low volatility", "safe haven", "inflation", "cash",
                   "short duration", "long duration", "duration", "quality", "healthcare", "utilities"}


def _fit_score(inst, thesis: dict) -> tuple[float, list[str]]:
    reasons, score = [], 0.0
    tags = {t.lower() for t in thesis.get("themes", [])}
    hit = tags & set(inst.tags)
    if hit:
        score += 45 * min(1.0, len(hit) / max(1, min(2, len(tags))))
        reasons.append("theme: " + ", ".join(sorted(hit)))
    sectors = {s.lower() for s in thesis.get("sectors", [])}
    if inst.sector.lower() in sectors:
        score += 25
        reasons.append(f"sector: {inst.sector}")
    regions = {r.lower() for r in thesis.get("regions", [])}
    if inst.region.lower() in regions or inst.country.lower() in regions:
        score += 15
        reasons.append(f"region: {inst.region}")
    assets = {a.lower() for a in thesis.get("asset_classes", [])}
    if not assets or inst.asset in assets:
        score += 10
    else:
        score -= 40  # wrong asset class: an oil fund is not an equity idea
        reasons.append(f"asset class {inst.asset} not in thesis")
    if thesis.get("prefer_index") and inst.kind == "etf":
        score += 5
        reasons.append("index exposure")
    return min(score, 100.0), reasons


def holdings() -> list[dict]:
    """Equity lines held today: benchmark mandates plus the active weights of approved ideas (% of portfolio)."""
    bench = reserve.benchmark_weights()
    active = ideas.active_positions()
    out = {}
    for s, w in bench.items():
        if BY_SYMBOL.get(s) and BY_SYMBOL[s].asset == "equity":
            out[s] = {"symbol": s, "weight_pct": w * 100, "source": "SAA mandate"}
    for s, w in active.items():
        if BY_SYMBOL.get(s) and BY_SYMBOL[s].asset == "equity":
            row = out.setdefault(s, {"symbol": s, "weight_pct": 0.0, "source": "Approved idea"})
            row["weight_pct"] += w * 100
            if row["source"] == "SAA mandate" and abs(w) > 1e-9:
                row["source"] = "SAA mandate, adjusted by approved ideas"
    rows = [r for r in out.values() if r["weight_pct"] > 1e-6]
    for r in rows:
        r["weight_pct"] = round(r["weight_pct"], 3)
        r["name"] = BY_SYMBOL[r["symbol"]].name
    return sorted(rows, key=lambda r: -r["weight_pct"])


def _returns(symbols: list[str]) -> pd.DataFrame:
    return risk.returns(sorted(set(symbols)), lookback=756)


def screen(thesis: dict, limit: int = 40) -> dict:
    ranks = ranker.latest() or {}
    rk = ranks.get("ranks", {})
    impl = thesis.get("implementation") or ("reduce" if thesis.get("direction") == "underweight" else "add")
    rows = []
    for inst in UNIVERSE:
        fit, reasons = _fit_score(inst, thesis)
        if fit < 25:
            continue
        try:
            df = store.read_series("yahoo", inst.symbol)
        except FileNotFoundError:
            continue
        px = df["adjclose"].dropna().values
        if len(px) < 260:
            continue
        r = np.diff(px) / px[:-1]
        fx = 1 / 3.6725 if inst.country == "AE" else 1.0
        rows.append({
            **inst.as_dict(), "fit": round(fit), "reasons": reasons,
            "mom_12_1_pct": round((px[-22] / px[-253] - 1) * 100, 1), "mom_3m_pct": round((px[-1] / px[-64] - 1) * 100, 1),
            "vol_1y_pct": round(r[-252:].std() * np.sqrt(252) * 100, 1),
            "max_dd_1y_pct": round(((px[-252:] / np.maximum.accumulate(px[-252:])) - 1).min() * 100, 1),
            "adv_usd_mn": round(float((df["close"] * df["volume"]).iloc[-20:].mean()) * fx / 1e6, 1),
            "ml_rank_pct": rk.get(inst.symbol, {}).get("rank_pct"),
        })
    direction = -1 if thesis.get("direction") == "underweight" else 1
    rows.sort(key=lambda d: (-d["fit"], -direction * (d["ml_rank_pct"] if d["ml_rank_pct"] is not None else 0.5)))
    rows = rows[:limit]

    # theme basket: the best-fitting equity matches, equal weight, as the yardstick for exposure and protection
    theme_syms = [r["symbol"] for r in rows if r["asset"] == "equity"][:8] or [r["symbol"] for r in rows][:8]
    held = holdings()
    sleeve = {h["symbol"]: h["weight_pct"] for h in held}
    # protection: whatever the thesis names, plus the standard set (Treasuries, gold, defensive equity), always
    hedge_tags = {t.lower() for t in thesis.get("hedge_themes", [])} | PROTECTIVE_TAGS
    prot_candidates = [i.symbol for i in UNIVERSE if set(i.tags) & hedge_tags and i.symbol not in theme_syms]
    syms = set(theme_syms) | set(sleeve) | {r["symbol"] for r in rows} | set(prot_candidates) | set(reserve.equity_sleeve())
    R = _returns(list(syms)).fillna(0.0)
    theme = R[[s for s in theme_syms if s in R]].mean(axis=1) if theme_syms else None
    eq = sum(R[s] * w for s, w in sleeve.items() if s in R) / max(sum(sleeve.values()), 1e-9) if sleeve else None
    worst = theme.nsmallest(max(10, len(theme) // 20)).index if theme is not None else []
    cov, _ = risk.covariance(list(syms | set(reserve.benchmark_weights())))

    def beta(s):
        if theme is None or s not in R or theme.var() == 0:
            return None
        return round(float(R[s].cov(theme) / theme.var()), 2)

    def marginal_te(s, sign=1.0):
        a = risk.active_from_tilt({s: sign * 1.0})
        names = [k for k in a if k in cov.index]
        v = np.array([a[k] for k in names])
        S = cov.loc[names, names].values
        return round(float(np.sqrt(max(v @ S @ v, 0))) * 1e4, 1)

    lt = lookthrough.load()
    via = lookthrough.indirect(sleeve, lt)
    loaded = any(v.get("loaded") for v in lt.values())
    for r in rows:
        s = r["symbol"]
        direct = sleeve.get(s, 0.0)
        # most it can be underweighted: what is held directly plus what the mandates hold of it (never a short)
        r["held_direct_pct"] = round(direct, 3)
        r["held_indirect_pct"] = via.get(s, 0.0) if loaded else None
        r["max_underweight_pct"] = round(direct + (via.get(s, 0.0) if loaded else 0.0), 3)
        r["beta_to_theme"] = beta(s)
        r["corr_with_holdings"] = round(float(R[s].corr(eq)), 2) if eq is not None and s in R else None
        r["te_per_1pct_bp"] = marginal_te(s)
    for h in held:
        b = beta(h["symbol"])
        h["beta_to_theme"] = b
        h["theme_exposure_pct"] = round(h["weight_pct"] * b, 3) if b is not None else None

    reduce = []
    if impl in ("reduce", "hedge"):
        for h in sorted(held, key=lambda h: -(h.get("theme_exposure_pct") or 0)):
            reduce.append({**h, "max_cut_pct": h["weight_pct"], "te_per_1pct_cut_bp": marginal_te(h["symbol"], -1.0)})
    protect = []
    if impl in ("reduce", "hedge") and len(worst):
        for s in prot_candidates:
            if s not in R:
                continue
            inst = BY_SYMBOL[s]
            kind = ("Treasuries" if "treasuries" in inst.tags else "Gold" if inst.asset == "gold" else
                    "Defensive equity" if inst.asset == "equity" else inst.asset.capitalize())
            protect.append({"symbol": s, "name": inst.name, "asset": inst.asset, "kind": inst.kind, "sri": inst.sri, "type": kind,
                            "tags": list(inst.tags), "avg_on_theme_worst_days_pct": round(float(R.loc[worst, s].mean()) * 100, 2),
                            "beta_to_theme": beta(s), "corr_with_holdings": round(float(R[s].corr(eq)), 2) if eq is not None else None,
                            "vol_1y_pct": round(float(R[s].iloc[-252:].std() * np.sqrt(252) * 100), 1),
                            "te_per_1pct_bp": marginal_te(s)})
        protect.sort(key=lambda p: -p["avg_on_theme_worst_days_pct"])
        # keep the best few of each type, so equity protection is not crowded out by a dozen bond funds
        per: dict[str, int] = {}
        kept = []
        for p in protect:
            per[p["type"]] = per.get(p["type"], 0) + 1
            if per[p["type"]] <= 4:
                kept.append(p)
        protect = kept[:12]
    exposure = sum(h.get("theme_exposure_pct") or 0 for h in held)
    return {
        "implementation": impl, "rows": rows, "considered": len(UNIVERSE), "matched": len(rows),
        "holdings": held, "theme_basket": theme_syms,
        "theme_exposure_pct": round(exposure, 2),
        "theme_worst_days": len(worst), "theme_worst_day_avg_pct": round(float(theme.loc[worst].mean()) * 100, 2) if len(worst) else None,
        "reduce": reduce, "protect": protect,
        "lookthrough": {m: {k: v for k, v in info.items() if k != "weights"} for m, info in lt.items()},
        "ranker": {"run_id": ranks.get("run_id"), "as_of": ranks.get("as_of"), "metrics": ranks.get("metrics")},
    }


# ---------------------------------------------------------------- what to look at (LLM proposal + measured evidence)
ACTIONS = ("buy", "hold_less", "protect", "study")


def clean_proposal(p: dict) -> dict:
    """Keep only instruments Nabd has, once each. The LLM chooses; nothing it invents reaches the screen."""
    seen, cands = set(), []
    for c in p.get("candidates", []):
        s = (c.get("symbol") or "").strip().upper()
        if s in BY_SYMBOL and s not in seen and c.get("action") in ACTIONS:
            seen.add(s)
            cands.append({"symbol": s, "action": c["action"], "reason": (c.get("reason") or "").strip()})
    drv = [s for s in dict.fromkeys((x or "").strip().upper() for x in p.get("driver_symbols", [])) if s in BY_SYMBOL]
    if len(drv) < 2:  # a driver needs instruments to measure it by: fall back to what the idea is about
        drv = [c["symbol"] for c in cands if c["action"] in ("study", "buy")][:6]
    return {**p, "candidates": cands, "driver_symbols": drv}


def rules_proposal(thesis: dict) -> dict:
    """The same shape as the LLM's proposal, from the rule-based screen, for when Codex is unavailable."""
    s = screen(thesis)
    bearish = s["implementation"] != "add"
    label = " and ".join(t for t in thesis.get("themes", [])[:2]) or "the idea"
    cands = [{"symbol": h["symbol"], "action": "hold_less", "reason": "Held today and moves with the idea's main names."}
             for h in s["reduce"][:3] if bearish]
    cands += [{"symbol": p["symbol"], "action": "protect", "reason": f"{p.get('type', 'Protective')}: a common hedge."}
              for p in s["protect"][:4] if bearish]
    cands += [{"symbol": r["symbol"], "action": "study" if bearish else "buy",
               "reason": "Matches the idea: " + "; ".join(r["reasons"][:2]) + "."} for r in s["rows"][:6]]
    return {"driver_label": f"{label} names", "driver_symbols": s["theme_basket"][:6],
            "if_right": "These move the way the idea expects.", "candidates": cands}


def _check(action: str, bearish: bool, beta: float | None, worst: float | None, label: str) -> dict:
    """Does the data agree with the suggestion? Plain words, so the team sees where the LLM may be wrong."""
    if action == "study" or beta is None:
        return {"agrees": None, "text": ""}
    if action == "hold_less":
        ok = beta >= 0.3
        return {"agrees": ok, "text": f"Falls when {label} fall" if ok else f"Barely moves with {label}"}
    if action == "protect" or (action == "buy" and bearish):
        ok = worst is not None and worst > 0
        return {"agrees": ok, "text": f"Held up on the worst days for {label}" if ok else f"Fell on the worst days for {label} too"}
    ok = beta >= 0.3  # buy, bullish idea
    return {"agrees": ok, "text": f"Rises with {label}" if ok else f"Barely moves with {label}"}


def view(thesis: dict, proposal: dict) -> dict:
    """The proposal with evidence on every candidate: how it moves with the driver, what it did on the driver's
    worst days, what we hold of it, the risk it adds and its liquidity. All computed here, none from the LLM."""
    p = clean_proposal(proposal)
    label = p.get("driver_label") or "the idea"
    bearish = (thesis or {}).get("direction") == "underweight"
    held = holdings()
    sleeve = {h["symbol"]: h["weight_pct"] for h in held}
    cands, drv = p["candidates"], p["driver_symbols"]
    syms = set(drv) | set(sleeve) | {c["symbol"] for c in cands} | set(reserve.equity_sleeve())
    R = _returns(list(syms)).fillna(0.0)
    driver = R[[s for s in drv if s in R]].mean(axis=1) if any(s in R for s in drv) else None
    worst = driver.nsmallest(max(10, len(driver) // 20)).index if driver is not None else []
    eq = sum(R[s] * w for s, w in sleeve.items() if s in R) / max(sum(sleeve.values()), 1e-9) if sleeve else None
    cov, _ = risk.covariance(list(syms | set(reserve.benchmark_weights())))
    lt = lookthrough.load()
    via = lookthrough.indirect(sleeve, lt)
    loaded = any(v.get("loaded") for v in lt.values())
    rk = (ranker.latest() or {}).get("ranks", {})

    def beta(s):
        if driver is None or s not in R or driver.var() == 0:
            return None
        return round(float(R[s].cov(driver) / driver.var()), 2)

    def on_worst(s):
        return round(float(R.loc[worst, s].mean()) * 100, 2) if len(worst) and s in R else None

    def marginal_te(s, sign=1.0):
        a = risk.active_from_tilt({s: sign * 1.0})
        names = [k for k in a if k in cov.index]
        v = np.array([a[k] for k in names])
        return round(float(np.sqrt(max(v @ cov.loc[names, names].values @ v, 0))) * 1e4, 1)

    items = []
    for c in cands:
        s, inst = c["symbol"], BY_SYMBOL[c["symbol"]]
        b, w = beta(s), on_worst(s)
        direct, indirect = sleeve.get(s, 0.0), (via.get(s, 0.0) if loaded else None)
        cap = round(direct + (indirect or 0.0), 3)
        try:
            st = risk.price_stats(s)
        except (FileNotFoundError, KeyError, ValueError):
            st = {}
        tradable = not (c["action"] == "hold_less" and cap <= 0)
        items.append({
            **c, "name": inst.name, "asset": inst.asset, "kind": inst.kind, "sector": inst.sector, "sri": inst.sri,
            "moves_with_driver": b, "on_worst_days_pct": w,
            "held_direct_pct": round(direct, 3), "held_indirect_pct": indirect, "max_cut_pct": cap,
            "tradable": tradable, "note": None if tradable else "We don't hold this directly, so it can be studied but not cut.",
            "check": _check(c["action"], bearish, b, w, label),
            "risk_per_1pct_bp": marginal_te(s, -1.0 if c["action"] == "hold_less" else 1.0) if s in cov.index else None,
            "corr_with_holdings": round(float(R[s].corr(eq)), 2) if eq is not None and s in R else None,
            "vol_1y_pct": st.get("vol_1y_pct"), "adv_usd_mn": st.get("avg_daily_value_traded_usd_mn"),
            "ml_rank_pct": rk.get(s, {}).get("rank_pct"),
        })
    order = ("hold_less", "protect", "buy", "study") if bearish else ("buy", "protect", "hold_less", "study")
    for h in held:
        h["moves_with_driver"] = beta(h["symbol"])
    exposure = sum(h["weight_pct"] * (h["moves_with_driver"] or 0) for h in held)
    return {
        "status": "ready", "source": proposal.get("source", "llm"), "created": proposal.get("created"),
        "driver": {"label": label, "symbols": drv, "if_right": p.get("if_right", "")},
        "bearish": bearish, "holdings": held, "exposure_pct": round(exposure, 2),
        "worst_days": len(worst), "worst_day_avg_pct": round(float(driver.loc[worst].mean()) * 100, 2) if len(worst) else None,
        "groups": [{"action": a, "items": [i for i in items if i["action"] == a]} for a in order
                   if any(i["action"] == a for i in items)],
        "lookthrough_loaded": loaded,
    }
