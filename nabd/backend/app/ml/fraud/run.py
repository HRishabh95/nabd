"""Fraud run: detect with every method, summarise cases, evaluate against labels, lay out the network for viewing."""

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


def layout(accounts: pd.DataFrame, tx: pd.DataFrame, focus: set, cap: int = 900) -> dict:
    """Positions for the flagged accounts, the true launderers and a sample of their neighbours."""
    a = accounts.set_index("account")
    nodes = set(focus) | set(a.index[a.label == 1])
    nb = tx[tx.src.isin(nodes) ^ tx.dst.isin(nodes)]
    extra = pd.concat([nb.src, nb.dst]).value_counts()
    extra = [x for x in extra.index if x not in nodes][: max(0, cap - len(nodes))]
    nodes |= set(extra)
    sub = tx[tx.src.isin(nodes) & tx.dst.isin(nodes)]
    agg = sub.groupby(["src", "dst"]).agg(amount=("amount", "sum"), n=("amount", "size")).reset_index()
    G = nx.Graph()
    G.add_nodes_from(nodes)
    for s, d, amt, n in agg.itertuples(index=False, name=None):
        G.add_edge(s, d, weight=float(np.log1p(amt)) / 5)
    pos = nx.spring_layout(G, k=1.6 / np.sqrt(max(len(G), 1)), iterations=80, seed=7, weight="weight")
    return {"nodes": [{"id": n, "x": round(float(pos[n][0]), 4), "y": round(float(pos[n][1]), 4),
                       "bank": a.loc[n, "bank"], "kind": a.loc[n, "kind"], "truth": int(a.loc[n, "label"])}
                      for n in G.nodes],
            "edges": [{"s": s, "d": d, "amount": round(float(amt), 0), "n": int(n)} for s, d, amt, n in
                      agg.sort_values("amount", ascending=False).head(4000).itertuples(index=False, name=None)]}


def run(params: dict | None = None, progress=None) -> dict:
    t0 = time.time()
    accounts, tx = generator.load()
    res = detect.run_all(tx, accounts, params, progress)
    methods = {}
    focus: set = set()
    for m, cases in res["cases"].items():
        cases = sorted(cases, key=lambda c: -float(res["scores"].reindex(list(c)).max()))
        summ = [_case_summary(i, c, tx, res["fast"], accounts, res["scores"]) for i, c in enumerate(cases[:60])]
        methods[m] = {"label": detect.METHODS[m], "eval": res["eval"][m], "cases": summ, "total_cases": len(cases)}
        if m != "rules":
            focus |= set().union(*cases) if cases else set()
    focus |= set().union(*res["cases"]["rules"][:200]) if res["cases"]["rules"] else set()
    lay = layout(accounts, tx, focus)
    a = accounts.set_index("account")
    out = {"created": time.time(), "params": res["params"], "methods": methods, "layout": lay,
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
    return {**case, "members_detail": members, "flow": _flow(m, inside, into, outof, a),
            "timeline": [{"ts": str(r.ts), "src": r.src, "dst": r.dst, "amount": round(float(r.amount), 0),
                          "cross_bank": int(r.cross_bank)} for r in inside.head(200).itertuples()],
            "money_in_aed": round(float(into.amount.sum()), 0), "money_out_aed": round(float(outof.amount.sum()), 0),
            "sources_outside": int(into.src.nunique()), "exits_outside": int(outof.dst.nunique())}
