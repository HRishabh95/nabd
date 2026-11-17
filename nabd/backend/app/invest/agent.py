"""The LLM's jobs in the investment flow, each with structured output and Nabd tools.

Rule for every task: figures come only from tool results or the supplied pack. Tool results carry an evidence id
(E1, E2, ...) and research points must cite them, so every claim on screen links to the computation behind it.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from ..data import store
from ..data.connectors import edgar, gkg
from ..data.universe import BY_SYMBOL, INVESTABLE_ASSETS, UNIVERSE
from ..llm.codex_session import Tool
from ..llm.gateway import gateway
from ..ml.portfolio import ranker, regime, risk
from . import ideas

SECTORS = sorted({i.sector for i in UNIVERSE if i.asset == "equity" and i.sector not in ("Broad", "Factor")})
REGIONS = sorted({i.region for i in UNIVERSE})
TAGS = sorted({t for i in UNIVERSE for t in i.tags})

BASE_RULES = (
    "You work for the investment team of the Central Bank of the UAE inside Nabd. The portfolio is a notional "
    "commodity book (gold, energy, industrial and precious metals, agriculture, broad commodity indices, and a small "
    "liquidity sleeve of T-bills and inflation-linked bonds), judged against its strategic benchmark and the "
    "Board's active risk budget. Equities are not investable. Never state a number that did not come from a tool result or the supplied data. Do not do arithmetic "
    "on figures yourself; if you need a derived figure, call the tool that computes it. Write plainly for "
    "investment professionals; British English; no hype."
)


# ---------------- thesis ----------------
class Invalidation(BaseModel):
    label: str = Field(description="What would prove the thesis wrong, in plain words")
    series: str | None = Field(description="A Nabd series id to watch, e.g. DCOILBRENTEU, DGS10, VIXCLS, "
                                           "news:hormuz, regime:stress, or an instrument symbol; null if none fits")
    op: Literal[">", "<"] | None
    value: float | None = Field(description="Threshold in the series' own units (price, %, probability 0-1)")


class Thesis(BaseModel):
    title: str = Field(description="Short title, at most 8 words")
    summary: str = Field(description="The thesis in two sentences")
    direction: Literal["overweight", "underweight"]
    implementation: Literal["add", "reduce", "hedge"] = Field(
        description="add: buy exposure to the themes. reduce: cut existing exposure to the themes (a reserve "
                    "portfolio does not short). hedge: keep exposure but add protection that gains when the themes fall")
    hedge_themes: list[str] = Field(description="For reduce or hedge: theme tags of protective assets to add, chosen "
                                                "only from the allowed list (e.g. treasuries, gold, defensive, low "
                                                "volatility); empty for add")
    assumptions: list[str] = Field(description="How you read a short or vague idea, in plain words; empty if clear")
    horizon: Literal["tactical", "strategic"]
    committee: Literal["MRMC", "Board (SAA review)"]
    tranche: Literal["Gold", "Energy", "Industrial metals", "Precious metals", "Agriculture", "Broad commodities", "Liquidity"]
    themes: list[str] = Field(description="Theme tags chosen only from the allowed list")
    sectors: list[str] = Field(description="Sectors chosen only from the allowed list; may be empty")
    regions: list[str] = Field(description="Regions chosen only from the allowed list; may be empty")
    asset_classes: list[Literal["equity", "bond", "gold", "commodity"]]
    prefer_index: bool = Field(description="True when an index exposure suits the idea better than single names")
    drivers: list[str] = Field(description="2-4 drivers the thesis depends on")
    invalidation: list[Invalidation] = Field(description="2-3 conditions that would prove it wrong")
    questions: list[str] = Field(description="1-3 questions research must answer")


async def parse_thesis(idea: dict, on_event=None) -> tuple[Thesis, list[dict]]:
    memory = ideas.search_memory(idea["text"], exclude=idea["id"])
    reg = regime.regime()
    prompt = json.dumps({
        "task": "Turn this investment idea into a structured thesis.",
        "idea": idea["text"], "horizon_chosen_by_user": idea["horizon"],
        "allowed_theme_tags": TAGS, "allowed_sectors": SECTORS, "allowed_regions": REGIONS,
        "current_market_regime": {"state": reg["state"], "probabilities": reg["current"], "as_of": reg["as_of"]},
        "series_you_can_watch": ["DCOILBRENTEU (Brent, USD)", "DGS10 (US 10y yield, %)", "VIXCLS (VIX)",
                                 "DTWEXBGS (dollar index)", "news:hormuz / news:oil / news:uae_economy / "
                                 "news:fed_rates / news:gold / news:ai_capex (daily share of world news, %)",
                                 "regime:stress (probability 0-1)", "any instrument symbol (price)"],
        "related_past_ideas": memory,
        "notes": "Tactical ideas go to the MRMC; strategic ones to the Board's review of the strategic benchmark. A short idea such as "
                 "'oil glut' must still produce a full thesis: read it the way a reserve manager would (here: crude prices "
                 "could fall, so hold less oil or add protection) and list your reading under assumptions. The team "
                 "invests in commodities (gold, oil, gas, metals, agriculture, broad indices), government and other "
                 "bonds, and cash; it does not invest in equities and cannot short. Express a bearish view as hold less "
                 "or protect.",
    }, indent=1)
    res = await gateway.run("thesis", BASE_RULES, prompt, schema=Thesis, on_event=on_event)
    return res.parsed, memory


# ---------------- what to look at ----------------
class Candidate(BaseModel):
    symbol: str = Field(description="A symbol from the instruments list, exactly as written there")
    action: Literal["buy", "hold_less", "protect", "study"] = Field(
        description="buy: add it to express the idea. hold_less: own less of it, only for something the portfolio "
                    "holds or a large company held through the index funds. protect: add it because it should hold up "
                    "if the idea plays out (for a bearish idea) or cushion the downside (for a bullish one). study: "
                    "the idea is about it; research it before deciding")
    reason: str = Field(description="One plain sentence, no figures, on why it belongs here")


class Proposal(BaseModel):
    driver_label: str = Field(description="What the idea is really a bet on, in 2-5 plain words, e.g. 'AI and chip "
                                          "stocks', 'Japanese government bond yields', 'Brent crude'")
    driver_symbols: list[str] = Field(description="3-8 symbols from the instruments list whose moves best stand for "
                                                  "the driver (for a yield or oil driver, the funds or companies that "
                                                  "track it)")
    if_right: str = Field(description="One plain sentence: what happens to the driver if the idea is right")
    candidates: list[Candidate] = Field(description="6-14 instruments for the team to look at, across asset classes "
                                                    "where it helps (commodities, gold, government bonds, cash)")


async def propose(idea: dict, holdings: list[dict], on_event=None) -> Proposal:
    """What the team should look at for this idea. Codex chooses; the screen then measures each choice."""
    instruments = [f"{i.symbol} | {i.name} | {i.asset} | {i.sector} | {', '.join(i.tags)}" for i in UNIVERSE
                   if i.asset in INVESTABLE_ASSETS]
    driver_only = [f"{i.symbol} | {i.name} | {i.asset} | {i.sector}" for i in UNIVERSE if i.asset not in INVESTABLE_ASSETS]
    prompt = json.dumps({
        "task": "Read this investment idea and propose what the reserve-management team should look at.",
        "idea": idea["text"], "thesis": idea.get("thesis"),
        "portfolio_holds_today": [{"symbol": h["symbol"], "name": h["name"], "weight_pct_of_portfolio": h["weight_pct"]}
                                  for h in holdings],
        "instruments (symbol | name | asset | sector | tags); choose candidates only from these": instruments,
        "for measuring the driver only (never as candidates): equities and indices": driver_only[:200],
        "rules": [
            "Use only symbols from the instruments list.",
            "The team invests in commodities, gold, bonds and cash only: candidates must be commodity, gold or bond "
            "funds from the instruments list. Equities may be used only as driver_symbols, to measure the driver.",
            "The portfolio cannot short. To act on a bearish view, hold less of what it owns (its gold, broad "
            "commodities, Brent, silver, copper and bond lines) or add protection.",
            "Prefer broad, liquid funds for the main expression (a broad commodity index, gold) unless one commodity is "
            "the point of the idea.",
            "For protection, offer more than one kind where they make sense (for example longer Treasuries, gold, "
            "inflation-linked bonds, short-dated bills), so the measured evidence can show which actually held up.",
            "Reasons are qualitative: no numbers. Nabd measures every candidate afterwards and shows where the data "
            "disagrees with you.",
        ],
    }, indent=1)
    res = await gateway.run("propose", BASE_RULES, prompt, schema=Proposal, on_event=on_event)
    return res.parsed


# ---------------- research ----------------
class Point(BaseModel):
    text: str
    evidence: list[str] = Field(description="Evidence ids (E1, E2...) from tool results that support the point")


class InstrumentView(BaseModel):
    symbol: str
    stance: Literal["supports", "mixed", "against"]
    points: list[Point]


class ResearchNote(BaseModel):
    summary: str = Field(description="Three sentences: what the evidence says about the thesis")
    instruments: list[InstrumentView]
    news_read: list[Point] = Field(description="What recent news says, citing headline evidence; ignore "
                                               "irrelevant headlines")
    risks: list[Point]
    past_ideas: list[Point] = Field(description="What Nabd's memory of related past ideas suggests; empty if none")
    answers: list[Point] = Field(description="Answers to the thesis questions")


class Evidence:
    """Numbers each tool result with an evidence id and keeps the results for display."""

    def __init__(self):
        self.items: dict[str, dict] = {}

    def add(self, tool: str, args: dict, result) -> dict:
        eid = f"E{len(self.items) + 1}"
        self.items[eid] = {"id": eid, "tool": tool, "args": args, "result": result}
        return {"evidence_id": eid, "result": result}


def research_tools(ev: Evidence, idea: dict) -> list[Tool]:
    def price(symbol: str):
        return ev.add("price_stats", {"symbol": symbol}, risk.price_stats(symbol))

    def betas(symbol: str):
        b = risk.macro_betas([symbol]).get(symbol)
        return ev.add("macro_betas", {"symbol": symbol},
                      {"move_assumed": risk.FACTOR_LABELS, **(b or {"error": "not enough history"})})

    def ml_rank(symbol: str):
        rk = ranker.latest() or {}
        r = rk.get("ranks", {}).get(symbol)
        return ev.add("ml_rank", {"symbol": symbol}, {
            "rank_percentile": r and r["rank_pct"], "as_of": rk.get("as_of"),
            "model_out_of_sample": rk.get("metrics"), "note": "weak signal; one input only"})

    def news(query: str):
        items = gkg.recent_items(None, query, 12)
        return ev.add("news", {"query": query}, [{"title": i["title"], "source": i["source"], "tone": round(i["tone"], 1),
                                                    "lang": i["lang"]} for i in items])

    def theme(theme: str):
        df = store.read_series("gdelt", f"news:{theme}")
        last30 = df.tail(30)
        return ev.add("news_theme", {"theme": theme}, {
            "volume_pct_last7": round(float(last30.volume.tail(7).mean()), 3),
            "volume_pct_prior23": round(float(last30.volume.head(23).mean()), 3),
            "tone_last7": round(float(last30.tone.tail(7).mean()), 2),
            "tone_prior23": round(float(last30.tone.head(23).mean()), 2)})

    async def filings(symbol: str):
        try:
            return ev.add("filings", {"symbol": symbol}, {"facts": await edgar.fundamentals(symbol),
                                                          "recent": await edgar.filings(symbol, 5)})
        except edgar.EdgarDisabled as exc:
            return ev.add("filings", {"symbol": symbol}, {"unavailable": str(exc)})

    def memory(query: str):
        return ev.add("memory", {"query": query}, ideas.search_memory(query, exclude=idea["id"]))

    def reg():
        r = regime.regime()
        return ev.add("regime", {}, {"state": r["state"], "probabilities": r["current"], "as_of": r["as_of"]})

    s = {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"],
         "additionalProperties": False}
    q = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"],
         "additionalProperties": False}
    themes = [t.key for t in gkg.THEMES]
    return [
        Tool("price_stats", "Returns, volatility, drawdown, liquidity for a symbol", s, price),
        Tool("macro_betas", "Sensitivity of a symbol to oil, rates, dollar, VIX and gold, with R²", s, betas),
        Tool("ml_rank", "The return-ranking model's percentile for a symbol and the model's track record", s, ml_rank),
        Tool("news_search", "Recent English and Arabic headlines matching a keyword (last 14 days)", q, news),
        Tool("news_theme", f"Volume and tone trend of a tracked news theme: {', '.join(themes)}",
             {"type": "object", "properties": {"theme": {"type": "string", "enum": themes}}, "required": ["theme"],
              "additionalProperties": False}, theme),
        Tool("filings", "SEC filings and reported fundamentals (US filers)", s, filings),
        Tool("search_memory", "Nabd's memory of past ideas, decisions and lessons", q, memory),
        Tool("market_regime", "Current market regime probabilities", {"type": "object", "properties": {},
                                                                        "additionalProperties": False}, reg),
    ]


async def write_research(idea: dict, on_event=None) -> dict:
    ev = Evidence()
    basket = [b["symbol"] for b in idea["basket"]["items"]]
    names = {s: BY_SYMBOL[s].name for s in basket if s in BY_SYMBOL}
    prompt = json.dumps({
        "task": "Research the selected instruments against the thesis. Use the tools: price_stats, macro_betas "
                "and ml_rank for each symbol; news_search for each company or theme name; news_theme for the "
                "relevant themes; search_memory once; market_regime once; filings for US companies. Then write "
                "the note. Cite evidence ids on every point.",
        "thesis": idea["thesis"], "selected": names,
    }, indent=1)
    res = await gateway.run("research", BASE_RULES, prompt, schema=ResearchNote,
                            tools=research_tools(ev, idea), on_event=on_event)
    note = res.parsed.model_dump()
    return {"note": note, "evidence": ev.items, "model": res.model, "seconds": round(res.ms / 1000, 1)}


# ---------------- committee ----------------
class CoverNote(BaseModel):
    recommendation_framing: str = Field(description="One sentence stating what the committee is asked to decide; "
                                                    "do not recommend approval or rejection")
    case_for: list[str]
    case_against: list[str]
    risk_points: list[str] = Field(description="Points the Risk function should review")
    conditions_to_consider: list[str] = Field(description="Possible conditions on an approval, e.g. size caps")


async def write_cover_note(idea: dict, pack: dict, on_event=None) -> CoverNote:
    prompt = json.dumps({"task": "Draft the cover note for the committee from this pack. Use only figures in the "
                                 "pack, quoted exactly. Do not recommend a decision.", "pack": pack}, indent=1,
                        default=str)
    res = await gateway.run("committee", BASE_RULES, prompt, schema=CoverNote, on_event=on_event)
    return res.parsed


class Lesson(BaseModel):
    outcome: str = Field(description="What happened versus the thesis, using only supplied figures")
    lesson: str = Field(description="One lesson for future ideas, one or two sentences")


async def write_lesson(idea: dict, outcome: dict) -> Lesson:
    prompt = json.dumps({"task": "Write the post-mortem for this closed idea.", "thesis": idea["thesis"],
                         "committee": idea.get("committee"), "outcome": outcome}, indent=1, default=str)
    res = await gateway.run("lesson", BASE_RULES, prompt, schema=Lesson)
    return res.parsed
