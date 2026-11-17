"""The notional reserve portfolio: benchmark (SAA), tranches, active risk budget.

ILLUSTRATIVE ONLY. This is not CBUAE's portfolio. It follows the public outline:
- four tranches: money market (liquidity), capital market (return and diversification), gold, long-term investment
  (Central Banking reserve-manager profile);
- mostly high-quality liquid assets, more international government bonds and measured developed-market equity under
  the 2025-2029 SAA, with new passive mandates often on SRI-screened indices (CBUAE Annual Report 2025);
- gold near the published AED 37.9 bn, about 3.5% of USD 285 bn net reserves.
Each line is an ETF standing in for the index a mandate would track. The active risk budget is an assumption.
"""

from __future__ import annotations

from dataclasses import dataclass

NOTIONAL_USD_BN = 285.0
ACTIVE_RISK_BUDGET_BP = 60.0  # ex-ante tracking-error budget against the SAA, bp a year (assumption)


@dataclass(frozen=True)
class Line:
    symbol: str
    tranche: str
    weight: float  # % of the total portfolio
    role: str


SAA: list[Line] = [
    Line("SHV", "Money market", 25.0, "US Treasury bills, daily liquidity"),
    Line("SHY", "Capital market", 18.0, "US Treasuries 1-3y"),
    Line("IEI", "Capital market", 14.0, "US Treasuries 3-7y"),
    Line("IEF", "Capital market", 10.0, "US Treasuries 7-10y"),
    Line("TLT", "Capital market", 3.0, "US Treasuries 20y+"),
    Line("BWX", "Capital market", 6.0, "International government bonds"),
    Line("TIP", "Capital market", 3.0, "US inflation-linked"),
    Line("ESGU", "Capital market", 4.0, "US equity, SRI-screened index (passive mandate)"),
    Line("ESGD", "Capital market", 2.0, "Developed ex-US equity, SRI-screened index (passive mandate)"),
    Line("GLD", "Gold", 4.0, "Gold"),
    Line("ESGU", "Long-term investment", 4.0, "US equity, SRI-screened index"),
    Line("ESGD", "Long-term investment", 3.0, "Developed ex-US equity, SRI-screened index"),
    Line("LQD", "Long-term investment", 2.0, "Investment-grade corporate bonds"),
    Line("EMB", "Long-term investment", 2.0, "Emerging-market sovereign bonds in USD"),
]

TRANCHES = ["Money market", "Capital market", "Gold", "Long-term investment"]


def benchmark_weights() -> dict[str, float]:
    """Benchmark weights by symbol, as fractions summing to 1."""
    w: dict[str, float] = {}
    for line in SAA:
        w[line.symbol] = w.get(line.symbol, 0.0) + line.weight / 100
    return w


def equity_sleeve() -> dict[str, float]:
    """Benchmark equity lines, used to fund an equity tilt pro rata so the tilt is a relative bet."""
    eq = {"ESGU", "ESGD"}
    w = {s: v for s, v in benchmark_weights().items() if s in eq}
    tot = sum(w.values())
    return {s: v / tot for s, v in w.items()}


def describe() -> dict:
    by_tranche: dict[str, float] = {}
    for line in SAA:
        by_tranche[line.tranche] = by_tranche.get(line.tranche, 0.0) + line.weight
    return {
        "notional_usd_bn": NOTIONAL_USD_BN,
        "active_risk_budget_bp": ACTIVE_RISK_BUDGET_BP,
        "lines": [line.__dict__ for line in SAA],
        "tranches": [{"name": t, "weight": by_tranche.get(t, 0.0)} for t in TRANCHES],
        "disclaimer": "Notional and illustrative; not CBUAE's holdings. ETFs stand in for mandate indices.",
    }
