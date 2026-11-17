"""The notional commodity book: benchmark (strategic allocation), sleeves, active risk budget.

ILLUSTRATIVE ONLY. This is not CBUAE's portfolio. The investment team asked for a commodity focus, so the benchmark
is a commodity book: gold, energy, industrial and precious metals, agriculture and broad commodity indices, with a
small liquidity sleeve (Treasury bills and inflation-linked bonds) to fund trades and hold collateral. Each line is an
ETF standing in for the index or futures programme a mandate would hold. Sizes and the risk budget are assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass

NOTIONAL_USD_BN = 25.0
ACTIVE_RISK_BUDGET_BP = 150.0  # ex-ante tracking-error budget against the benchmark, bp a year (assumption;
# commodities move 15-35% a year, so a reserve-style 60 bp budget would leave no room for any tilt)


@dataclass(frozen=True)
class Line:
    symbol: str
    tranche: str
    weight: float  # % of the total portfolio
    role: str


SAA: list[Line] = [
    Line("GLD", "Gold", 30.0, "Physical gold"),
    Line("BNO", "Energy", 12.0, "Brent crude futures"),
    Line("USO", "Energy", 6.0, "WTI crude futures"),
    Line("UNG", "Energy", 4.0, "Natural gas futures"),
    Line("CPER", "Industrial metals", 8.0, "Copper futures"),
    Line("DBB", "Industrial metals", 6.0, "Aluminium, zinc and copper futures"),
    Line("SLV", "Precious metals", 6.0, "Physical silver"),
    Line("PPLT", "Precious metals", 3.0, "Physical platinum"),
    Line("DBA", "Agriculture", 6.0, "Grains, softs and livestock futures"),
    Line("DBC", "Broad commodities", 7.0, "Diversified commodity index"),
    Line("GSG", "Broad commodities", 3.0, "S&P GSCI (energy-weighted index)"),
    Line("SHV", "Liquidity", 6.0, "US Treasury bills: margin, collateral and dry powder"),
    Line("TIP", "Liquidity", 3.0, "US inflation-linked Treasuries"),
]

TRANCHES = ["Gold", "Energy", "Industrial metals", "Precious metals", "Agriculture", "Broad commodities", "Liquidity"]


def benchmark_weights() -> dict[str, float]:
    """Benchmark weights by symbol, as fractions summing to 1."""
    w: dict[str, float] = {}
    for line in SAA:
        w[line.symbol] = w.get(line.symbol, 0.0) + line.weight / 100
    return w


def risk_sleeve() -> dict[str, float]:
    """Benchmark commodity and gold lines, pro rata. A tilt is funded from them so it is a relative bet within the book
    (the "equity" funding key is kept for stored ideas; it now means this sleeve)."""
    lines = {line.symbol for line in SAA if line.tranche != "Liquidity"}
    w = {s: v for s, v in benchmark_weights().items() if s in lines}
    total = sum(w.values()) or 1.0
    return {s: v / total for s, v in w.items()}


equity_sleeve = risk_sleeve


def describe() -> dict:
    by_tranche: dict[str, float] = {}
    for line in SAA:
        by_tranche[line.tranche] = by_tranche.get(line.tranche, 0.0) + line.weight
    return {
        "notional_usd_bn": NOTIONAL_USD_BN,
        "active_risk_budget_bp": ACTIVE_RISK_BUDGET_BP,
        "lines": [line.__dict__ for line in SAA],
        "tranches": [{"name": t, "weight": by_tranche.get(t, 0.0)} for t in TRANCHES],
        "disclaimer": "Notional commodity book, illustrative; not CBUAE's holdings. ETFs stand in for the indices and futures a mandate would hold.",
    }
