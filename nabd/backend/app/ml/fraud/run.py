"""Fraud run: detect, summarise the networks found, evaluate against the synthetic labels, and prepare the views.

Two approaches are kept for the page (detect.py runs the rest as building blocks and benchmarks):
- ml        gradient-boosted trees giving every account a risk score (scikit-learn's histogram gradient boosting,
            the same family as XGBoost), cross-fitted by ring
- combined  graph detection: money-trail and cycle networks, keeping accounts the ML score agrees with
Each network's pattern (cycle, fan-in, fan-out, layering chain...) is read from its own transfers, never from labels.
"""

from __future__ import annotations

import time

import networkx as nx
import numpy as np
import pandas as pd

from ...core.db import store as kv
from .. import registry
from . import detect, generator

USD_PER_AED = 1 / 3.6725


def _case_summary(i: int, members: set, tx: pd.DataFrame, fast: pd.DataFrame, accounts: pd.DataFrame,
                  scores: pd.Series) -> dict:
    a = accounts.set_index("account")
    inside = tx[tx.src.isin(members) & tx.dst.isin(members)]
    touching = tx[tx.src.isin(members) | tx.dst.isin(members)]
    f_in = fast[fast.src.isin(members) | fast.dst.isin(members)]
    truth = a.loc[list(members)]
    rings = truth[truth.label == 1].ring.value_counts()
    holds = []
    for acc in list(members)[:60]:  # median minutes between money arriving and leaving
        i_t = touching[touching.dst == acc].ts.sort_values().values
        o_t = touching[touching.src == acc].ts.sort_values().values
        if len(i_t) and len(o_t):
            k = np.searchsorted(i_t, o_t, "right") - 1
            d = (o_t[k >= 0] - i_t[k[k >= 0]]) / np.timedelta64(1, "m")
            holds += [x for x in d if 0 < x < 24 * 60]
    return {
        "id": f"C{i + 1:02d}", "size": len(members), "members": sorted(members),
        "banks": int(truth.bank.nunique()), "bank_list": sorted(truth.bank.unique()),
        "flow_aed": round(float(inside.amount.sum()), 0), "transfers": int(len(inside)),
        "pass_through_share": round(len(f_in) / max(len(touching), 1), 3),
        "median_hold_min": round(float(np.median(holds)), 0) if holds else None,
        "first": str(inside.ts.min()) if len(inside) else None, "last": str(inside.ts.max()) if len(inside) else None,
        "score": round(float(scores.reindex(list(members)).max()), 3),
        "truth": {"laundering_accounts": int(truth.label.sum()),
                  "ring": rings.index[0] if len(rings) else None,
                  "typology": truth[truth.label == 1].typology.mode().iloc[0] if truth.label.sum() else None},
    }


SHOWN = ("combined", "ml")
PATTERN = {"cycle": "Circular flow", "fan_in": "Fan-in: many accounts collect into one", "fan_out":
           "Fan-out: one account spreads money to many", "gather_scatter": "Gather then scatter through a hub",
           "scatter_gather": "Scatter then gather", "chain": "Layering chain", "mixed": "Mixed pass-through network"}


def pattern(edges: list[tuple[str, str]]) -> dict:
    """The money pattern of a network, from the direction of its transfers only."""
    G = nx.DiGraph(edges)
    if not len(G):
        return {"key": "mixed", "label": PATTERN["mixed"], "hub": None}
    try:
        cyc = nx.find_cycle(G)
        if len(cyc) >= 3:
            return {"key": "cycle", "label": PATTERN["cycle"], "hub": None, "length": len(cyc)}
    except nx.NetworkXNoCycle:
        pass
    ind, outd = dict(G.in_degree()), dict(G.out_degree())
    hub_in, hub_out = max(ind, key=ind.get), max(outd, key=outd.get)
    sources = [n for n in G if ind[n] == 0]
    sinks = [n for n in G if outd[n] == 0]
    if ind[hub_in] >= 3 and outd[hub_in] >= 3:
        return {"key": "gather_scatter", "label": PATTERN["gather_scatter"], "hub": hub_in}
    if len(sources) == 1 and len(sinks) == 1 and outd[sources[0]] >= 2 and ind[sinks[0]] >= 2:
        return {"key": "scatter_gather", "label": PATTERN["scatter_gather"], "hub": sources[0]}
    if ind[hub_in] >= 3:
        return {"key": "fan_in", "label": PATTERN["fan_in"], "hub": hub_in}
    if outd[hub_out] >= 3:
        return {"key": "fan_out", "label": PATTERN["fan_out"], "hub": hub_out}
    if max(ind.values()) <= 1 and max(outd.values()) <= 1:
        return {"key": "chain", "label": PATTERN["chain"], "hub": None, "length": nx.dag_longest_path_length(G) + 1}
    return {"key": "mixed", "label": PATTERN["mixed"], "hub": None}


def _links(cases: list[dict], tx: pd.DataFrame) -> list[dict]:
    """Ties between networks: direct transfers between their members (with the outside accounts both deal with)."""
    mem = {c["id"]: set(c["members"]) for c in cases}
    owner = {a: cid for cid, m in mem.items() for a in m}
    t = tx[tx.src.isin(owner) | tx.dst.isin(owner)]
    direct: dict = {}
    for s, d, amt in t[["src", "dst", "amount"]].itertuples(index=False, name=None):
        a, b = owner.get(s), owner.get(d)
        if a and b and a != b:
            k = tuple(sorted((a, b)))
            direct[k] = direct.get(k, 0.0) + float(amt)
    cps = {cid: set(t[t.src.isin(m)].dst) | set(t[t.dst.isin(m)].src) for cid, m in mem.items()}
    out, ids = [], list(mem)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            shared = (cps[a] & cps[b]) - mem[a] - mem[b]
            if (a, b) in direct:  # shared outside counterparties tie almost every pair (busy merchants), so not used
                out.append({"a": a, "b": b, "direct_aed": round(direct.get((a, b), 0.0)), "shared": len(shared)})
    return out


def run(params: dict | None = None, progress=None) -> dict:
    t0 = time.time()
    accounts, tx = generator.load()
    res = detect.run_all(tx, accounts, params, progress)
    methods = {}
    for m, cases in res["cases"].items():
        cases = sorted(cases, key=lambda c: -float(res["scores"].reindex(list(c)).max()))
        summ = [_case_summary(i, c, tx, res["fast"], accounts, res["scores"]) for i, c in enumerate(cases[:60])]
        for c in summ:
            ins = tx[tx.src.isin(c["members"]) & tx.dst.isin(c["members"])]
            c["pattern"] = pattern(list(ins[["src", "dst"]].drop_duplicates().itertuples(index=False, name=None)))
        methods[m] = {"label": detect.METHODS[m], "eval": res["eval"][m], "cases": summ, "total_cases": len(cases)}
    a = accounts.set_index("account")
    sc = res["scores"]
    combined = methods["combined"]["cases"]
    in_net = set().union(*[set(c["members"]) for c in combined]) if combined else set()
    out = {"created": time.time(), "params": res["params"], "methods": {m: methods[m] for m in SHOWN},
           "benchmarks": {m: {"label": v["label"], "eval": v["eval"]} for m, v in methods.items() if m not in SHOWN},
           "links": _links(combined, tx),
           "scores": {k: round(float(v), 3) for k, v in sc[sc >= 0.2].items()},
           "summary": {"transfers": len(tx), "accounts": len(accounts),
                       "suspicious_transfers": int(sum(c["transfers"] for c in combined)),
                       "suspicious_aed": round(float(sum(c["flow_aed"] for c in combined))),
                       "high_risk_accounts": int((sc >= 0.5).sum()), "networks": len(combined),
                       "accounts_in_networks": len(in_net)},
           "data": {"accounts": len(accounts), "transfers": len(tx), "banks": sorted(accounts.bank.unique()),
                    "days": generator.DAYS, "start": str(generator.START.date()),
                    "laundering_accounts": int(a.label.sum()), "rings": int(a.ring.replace("", np.nan).nunique()),
                    "pass_through_transfers": int(len(res["fast"])), "source": "Synthetic, AMLSim-style (labelled)"},
           "seconds": round(time.time() - t0, 1)}
    best = max(methods, key=lambda k: methods[k]["eval"]["f1"])
    out["run_id"] = registry.record("fraud", res["params"], {k: {x: v["eval"][x] for x in ("precision", "recall", "f1", "cases", "rings_whole")}
                                                              for k, v in methods.items()} | {"best": best}, None, out["data"]["start"])
    kv.set("fraud:latest", out)
    return out


def latest() -> dict | None:
    return kv.get("fraud:latest")


def _flow(m: set, inside: pd.DataFrame, into: pd.DataFrame, outof: pd.DataFrame, a: pd.DataFrame,
          min_outside: float = 5000, max_outside: int = 6) -> dict:
    """How the money moved through a case, for the flow view: roles, layers, arrows and a replayable timeline.

    Roles come from the transfers inside the case: an account that only sends inside is where money enters, one that
    only receives is where it leaves, the rest pass it on. A pure cycle has no entry, so its first sender starts it.
    Layers are steps from the entry along inside transfers (breadth first), which places accounts left to right.
    """
    ins = inside.groupby("src").size().reindex(list(m), fill_value=0)
    outs = inside.groupby("dst").size().reindex(list(m), fill_value=0)
    role = {}
    for acc in m:
        role[acc] = ("entry" if outs[acc] == 0 and ins[acc] > 0 else "exit" if ins[acc] == 0 and outs[acc] > 0
                     else "pass" if ins[acc] or outs[acc] else "single")
    starts = [x for x in m if role[x] == "entry"]
    if not starts and len(inside):
        first = inside.iloc[0].src
        role[first], starts = "start", [first]
    nxt = inside.groupby("src")["dst"].apply(lambda d: list(dict.fromkeys(d))).to_dict()
    layer = {x: 0 for x in starts}
    frontier = list(starts)
    while frontier:
        new = []
        for x in frontier:
            for y in nxt.get(x, []):
                if y not in layer:
                    layer[y] = layer[x] + 1
                    new.append(y)
        frontier = new
    for x in m:  # accounts not reached from the entry (separate strands) sit by their role
        layer.setdefault(x, max(layer.values(), default=0) if role[x] == "exit" else 0)

    def agg(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
        return df.groupby(by).agg(amount=("amount", "sum"), n=("amount", "size"), first=("ts", "min"),
                                  last=("ts", "max"), cross=("cross_bank", "max")).reset_index()

    edges = [{"s": r.src, "d": r.dst, "amount": round(float(r.amount)), "n": int(r.n), "first": str(r.first),
              "last": str(r.last), "cross_bank": int(r.cross)} for r in agg(inside, ["src", "dst"]).itertuples()]
    big_in = into[into.amount >= min_outside]
    big_out = outof[outof.amount >= min_outside]
    in_e = agg(big_in, ["dst"]).sort_values("amount", ascending=False).head(max_outside)
    out_e = agg(big_out, ["src"]).sort_values("amount", ascending=False).head(max_outside)
    # same-minute ties replay in the order money moves: arrives from outside, moves inside, leaves
    events = pd.concat([big_in[big_in.dst.isin(set(in_e.dst))].assign(kind="in"), inside.assign(kind="inside"),
                        big_out[big_out.src.isin(set(out_e.src))].assign(kind="out")]).sort_values("ts", kind="stable").head(300)
    return {
        "nodes": [{"id": x, "bank": a.loc[x, "bank"], "role": role[x], "layer": int(layer[x])} for x in m],
        "edges": edges,
        "in_edges": [{"d": r.dst, "amount": round(float(r.amount)), "n": int(r.n), "first": str(r.first)}
                     for r in in_e.itertuples()],
        "out_edges": [{"s": r.src, "amount": round(float(r.amount)), "n": int(r.n), "first": str(r.first)}
                      for r in out_e.itertuples()],
        "events": [{"ts": str(r.ts), "src": r.src, "dst": r.dst, "amount": round(float(r.amount)), "kind": r.kind,
                    "cross_bank": int(r.cross_bank)} for r in events.itertuples()],
        "min_outside": min_outside,
    }


def case_detail(method: str, case_id: str) -> dict | None:
    out = latest()
    if not out or method not in out["methods"]:
        return None
    case = next((c for c in out["methods"][method]["cases"] if c["id"] == case_id), None)
    if not case:
        return None
    accounts, tx = generator.load()
    a = accounts.set_index("account")
    m = set(case["members"])
    inside = tx[tx.src.isin(m) & tx.dst.isin(m)].sort_values("ts")
    into = tx[~tx.src.isin(m) & tx.dst.isin(m)]
    outof = tx[tx.src.isin(m) & ~tx.dst.isin(m)]
    members = []
    for acc in case["members"]:
        members.append({"account": acc, "bank": a.loc[acc, "bank"], "kind": a.loc[acc, "kind"],
                        "opened_days_ago": int(a.loc[acc, "opened_days_ago"]),
                        "in_aed": round(float(tx[tx.dst == acc].amount.sum()), 0),
                        "out_aed": round(float(tx[tx.src == acc].amount.sum()), 0),
                        "truth": {"label": int(a.loc[acc, "label"]), "typology": a.loc[acc, "typology"], "ring": a.loc[acc, "ring"]}})
    scores = out.get("scores", {})
    for x in members:
        x["risk"] = scores.get(x["account"], 0.0)
    flow = _flow(m, inside, into, outof, a)
    roles = {n["id"]: n["role"] for n in flow["nodes"]}
    for x in members:
        x["role"] = roles.get(x["account"])
    return {**case, "members_detail": members, "flow": flow,
            "timeline": [{"ts": str(r.ts), "src": r.src, "dst": r.dst, "amount": round(float(r.amount), 0),
                          "cross_bank": int(r.cross_bank)} for r in inside.head(200).itertuples()],
            "money_in_aed": round(float(into.amount.sum()), 0), "money_out_aed": round(float(outof.amount.sum()), 0),
            "sources_outside": int(into.src.nunique()), "exits_outside": int(outof.dst.nunique())}
