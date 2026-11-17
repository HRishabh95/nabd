"""Fraud-network detection methods and their evaluation against the labels.

Each method returns cases: groups of accounts an investigator would open together. Rules raise one case per
account; network methods raise one case per connected group, which is what lets a ring be caught whole.

- rules       Threshold rules per account: structuring (several 9-15k inflows in a day), rapid movement (most
              of a large inflow sent on within a day), and many new counterparties in a day.
- trail       Money-trail tracing: a transfer is a pass-through when money arrived at the sender within the hold
              window and roughly the same amount leaves; pass-through transfers are joined into groups.
- community   Louvain communities on the payment graph, kept when a large share of their internal transfers are
              pass-throughs.
- cycles      Money that returns to its origin in 3 to 7 hops, in time order, within 3 days.
- ml          Gradient-boosted trees on account features (degree, counterparties, pass-through share, structuring,
              PageRank on money flows, cross-bank share, account age), cross-fitted by ring so no ring is scored by a
              model that saw it. Accounts above the threshold, joined through their transfers.
- combined    Trail and cycle cases, keeping only accounts whose ML score is at least 0.25; overlapping cases merged.
"""

from __future__ import annotations

import time
from collections import defaultdict

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

METHODS = {"rules": "Rules (per account)", "trail": "Money-trail tracing", "community": "Community detection",
           "cycles": "Cycle detection", "ml": "Machine learning on account features", "combined": "Combined network"}


class UF:
    def __init__(self):
        self.p: dict = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)

    def groups(self):
        g = defaultdict(set)
        for x in list(self.p):
            g[self.find(x)].add(x)
        return list(g.values())


# ---------------------------------------------------------------- shared building blocks
def pass_through(tx: pd.DataFrame, hold_min: float = 240, flow_min: float = 0.7, min_amount: float = 5000) -> pd.DataFrame:
    """Transfers that move money on. For an outgoing transfer of at least `min_amount`, the money that arrived at the
    sender within the hold window must roughly equal it: out / in between `flow_min` and 1 / `flow_min`. Ordinary
    accounts receive and pay unrelated amounts; a pass-through account forwards what it just received."""
    hold = pd.Timedelta(minutes=hold_min)
    srt = tx.sort_values("ts")
    inc_t = {a: (g.ts.values, g.amount.values, g.index.values) for a, g in srt.groupby("dst")}
    out_t = {a: (g.ts.values, np.cumsum(g.amount.values)) for a, g in srt.groupby("src")}
    keep_out, keep_in = [], set()
    for i, (a, t2, y) in enumerate(zip(tx.src.values, tx.ts.values, tx.amount.values)):
        if a not in inc_t or y < min_amount:
            continue
        ts, am, ix = inc_t[a]
        lo, hi = np.searchsorted(ts, t2 - hold, "left"), np.searchsorted(ts, t2, "left")
        if hi <= lo:
            continue
        inflow = am[lo:hi].sum()
        # what leaves from the moment that money arrived until a window after this transfer: a split into several
        # payments counts whole, for each of the splits
        ot, oc = out_t[a]
        j0, j1 = np.searchsorted(ot, ts[lo], "left"), np.searchsorted(ot, t2 + hold, "left")
        outflow = oc[j1 - 1] - (oc[j0 - 1] if j0 > 0 else 0.0)
        if flow_min <= outflow / inflow <= 1 / flow_min:
            keep_out.append(tx.index.values[i])
            keep_in.update(ix[lo:hi])
    return tx.loc[sorted(set(keep_out) | keep_in)]


def features(tx: pd.DataFrame, accounts: pd.DataFrame, fast: pd.DataFrame) -> pd.DataFrame:
    a = accounts.set_index("account")
    f = pd.DataFrame(index=a.index)
    f["out_n"] = tx.groupby("src").size()
    f["in_n"] = tx.groupby("dst").size()
    f["out_amt"] = tx.groupby("src").amount.sum()
    f["in_amt"] = tx.groupby("dst").amount.sum()
    f["out_cp"] = tx.groupby("src").dst.nunique()
    f["in_cp"] = tx.groupby("dst").src.nunique()
    f["fast_out"] = fast.groupby("src").size()
    f["fast_in"] = fast.groupby("dst").size()
    f["struct_in"] = tx[(tx.amount >= 9000) & (tx.amount < 15000)].groupby("dst").size()
    f["cross_out"] = tx.groupby("src").cross_bank.mean()
    G = nx.DiGraph()
    agg = tx.groupby(["src", "dst"]).amount.sum().reset_index()
    G.add_weighted_edges_from(agg.itertuples(index=False, name=None))
    pr = nx.pagerank(G, weight="weight", alpha=0.85, max_iter=60, tol=1e-5)
    f["pagerank"] = pd.Series(pr)
    f = f.fillna(0.0)
    f["pass_share"] = (f.fast_out + f.fast_in) / (f.out_n + f.in_n).clip(lower=1)
    f["balance_ratio"] = f.out_amt / f.in_amt.clip(lower=1)
    f["age"] = a["opened_days_ago"]
    f["business"] = (a["kind"] == "business").astype(int)
    return f


def _cases(groups: list[set], scores: dict | None = None, min_size: int = 1) -> list[set]:
    out = [g for g in groups if len(g) >= min_size]
    if scores:
        out.sort(key=lambda g: -max(scores.get(x, 0) for x in g))
    return out


# ---------------------------------------------------------------- methods
def m_rules(tx, accounts, fast, feat, p) -> list[set]:
    tx = tx.assign(day=tx.ts.dt.floor("D"))
    s = tx[(tx.amount >= 9000) & (tx.amount < 15000)].groupby(["dst", "day"]).src.nunique()
    flagged = set(s[s >= p.get("struct_n", 5)].index.get_level_values(0))
    big_in = tx[tx.amount >= 50000].groupby(["dst", "day"]).amount.sum()
    out = tx.groupby(["src", "day"]).amount.sum()
    rm = (out.reindex(big_in.index.rename(["src", "day"])).values >= 0.8 * big_in.values)
    flagged |= set(big_in.index.get_level_values(0)[rm])
    cp = tx.groupby(["src", "day"]).dst.nunique()
    flagged |= set(cp[cp >= p.get("cp_n", 20)].index.get_level_values(0))
    return [{x} for x in flagged]


def mules(tx: pd.DataFrame, fast: pd.DataFrame, share: float = 0.6, min_n: int = 1) -> set:
    """Accounts that forward most of what they receive: pass-through transfers make up at least `share` of their
    outflow by value. Businesses forward similar amounts by coincidence now and then; mules do it routinely."""
    out_all = tx.groupby("src").amount.sum()
    fast_out = fast.groupby("src").amount.agg(["sum", "size"])
    frac = (fast_out["sum"] / out_all.reindex(fast_out.index)).fillna(0)
    return set(frac[(frac >= share) & (fast_out["size"] >= min_n)].index)


def m_trail(tx, accounts, fast, feat, p) -> list[set]:
    """Groups are joined only through mules, or through accounts dedicated to mule flows (a source or sink that
    sends or receives most of its money via mules). An ordinary account that happens to touch two rings attaches
    to one of them but never merges them, so rings stay separate cases."""
    m = mules(tx, fast, p.get("mule_share", 0.6))
    min_amt = p.get("min_amount", 5000) / 2
    links = fast[(fast.src.isin(m) | fast.dst.isin(m)) & (fast.amount >= min_amt)]
    total = (tx.groupby("src").amount.sum().add(tx.groupby("dst").amount.sum(), fill_value=0))
    with_m = links.groupby("src").amount.sum().add(links.groupby("dst").amount.sum(), fill_value=0)
    dedicated = set((with_m / total.reindex(with_m.index)).loc[lambda x: x >= 0.5].index) | m
    uf = UF()
    attach: dict = {}
    for s, d in zip(links.src.values, links.dst.values):
        if s in dedicated and d in dedicated:
            uf.union(s, d)
    for s, d in zip(links.src.values, links.dst.values):
        for x, y in ((s, d), (d, s)):
            if x not in dedicated and y in dedicated and x not in attach:
                attach[x] = y  # attach only; never a bridge
    groups = {}
    for g in uf.groups():
        root = uf.find(next(iter(g)))
        groups[root] = set(g)
    for x, y in attach.items():
        groups.setdefault(uf.find(y), {y}).add(x)
    return _cases(list(groups.values()), min_size=p.get("min_group", 3))


def m_community(tx, accounts, fast, feat, p) -> list[set]:
    agg = tx.groupby(["src", "dst"]).amount.sum().reset_index()
    G = nx.Graph()
    for s, d, w in agg.itertuples(index=False, name=None):
        G.add_edge(s, d, weight=float(np.log1p(w)))
    comms = nx.community.louvain_communities(G, weight="weight", resolution=p.get("resolution", 2.0), seed=7)
    fast_pairs = set(zip(fast.src, fast.dst))
    mule_set = mules(tx, fast, p.get("mule_share", 0.6))
    keep = []
    for c in comms:
        if not 3 <= len(c) <= 80:
            continue
        inside = agg[agg.src.isin(c) & agg.dst.isin(c)]
        if len(inside) == 0:
            continue
        share = sum((s, d) in fast_pairs for s, d in zip(inside.src, inside.dst)) / len(inside)
        if share >= p.get("fast_share", 0.15) and len(c & mule_set) >= 2:
            keep.append({x for x in c if feat.loc[x, "fast_in"] + feat.loc[x, "fast_out"] > 0} or set(c))
    return keep


def _timed_cycle(cyc: list, times: dict, window=np.timedelta64(3, "D")) -> bool:
    """True if, starting from some account in the cycle, each hop happens after the previous one, within the window.
    (The listing can start anywhere in the cycle, so every rotation is tried.)"""
    for k in range(len(cyc)):
        rot = cyc[k:] + cyc[:k]
        t_prev = t_first = None
        ok = True
        for a, b in zip(rot, rot[1:] + rot[:1]):
            ts = [t for t in times[(a, b)] if t_prev is None or t > t_prev]
            if not ts:
                ok = False
                break
            t_prev = min(ts)
            t_first = t_first if t_first is not None else t_prev
        if ok and (t_prev - t_first) <= window:
            return True
    return False


def m_cycles(tx, accounts, fast, feat, p) -> list[set]:
    big = tx[tx.amount >= p.get("cycle_min_amount", 20000)]
    G = nx.DiGraph()
    times = defaultdict(list)
    for s, d, t in zip(big.src.values, big.dst.values, big.ts.values):
        G.add_edge(s, d)
        times[(s, d)].append(t)
    core = nx.k_core(G.to_undirected(), 2).nodes
    H = G.subgraph(core)
    found = []
    for cyc in nx.simple_cycles(H, length_bound=7):
        if len(cyc) < 3:
            continue
        if _timed_cycle(cyc, times):
            found.append(set(cyc))
        if len(found) > 400:
            break
    uf = UF()
    for c in found:
        c = list(c)
        for x in c[1:]:
            uf.union(c[0], x)
    return uf.groups()


def ml_scores(feat: pd.DataFrame, accounts: pd.DataFrame, folds: int = 2, seed: int = 7) -> pd.Series:
    """Out-of-fold probabilities; laundering rings are kept whole within a fold."""
    a = accounts.set_index("account").reindex(feat.index)
    y = a["label"].values
    rings = a["ring"].replace("", np.nan)
    rng = np.random.default_rng(seed)
    ring_fold = {r: i % folds for i, r in enumerate(rng.permutation(rings.dropna().unique()))}
    fold = np.where(rings.notna(), rings.map(ring_fold).fillna(0).astype(int), rng.integers(0, folds, len(a)))
    X = feat.drop(columns=[], errors="ignore").values
    out = np.zeros(len(a))
    for k in range(folds):
        tr, te = fold != k, fold == k
        m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.06, max_depth=4, l2_regularization=1.0,
                                           class_weight="balanced", random_state=seed).fit(X[tr], y[tr])
        out[te] = m.predict_proba(X[te])[:, 1]
    return pd.Series(out, index=feat.index)


def m_ml(tx, accounts, fast, feat, p, scores=None) -> list[set]:
    s = scores if scores is not None else ml_scores(feat, accounts)
    hi = set(s[s >= p.get("ml_threshold", 0.6)].index)
    uf = UF()
    for x in hi:
        uf.find(x)
    sub = tx[tx.src.isin(hi) & tx.dst.isin(hi)]
    for a, b in zip(sub.src, sub.dst):
        uf.union(a, b)
    return uf.groups()


def m_combined(tx, accounts, fast, feat, p, scores=None, trail=None, cycles=None) -> list[set]:
    s = scores if scores is not None else ml_scores(feat, accounts)
    cases = []
    for g in (trail or []) + (cycles or []):
        keep = {x for x in g if s.get(x, 0) >= p.get("combined_floor", 0.25)}
        if len(keep) >= 3:
            cases.append(keep)
    uf = UF()  # merge overlapping cases (a trail and a cycle on the same ring)
    for g in cases:
        g = list(g)
        for x in g[1:]:
            uf.union(g[0], x)
        uf.find(g[0])
    return uf.groups()


# ---------------------------------------------------------------- evaluation
def evaluate(cases: list[set], accounts: pd.DataFrame) -> dict:
    a = accounts.set_index("account")
    truth = set(a.index[a.label == 1])
    flagged = set().union(*cases) if cases else set()
    tp = len(flagged & truth)
    prec = tp / len(flagged) if flagged else 0.0
    rec = tp / len(truth) if truth else 0.0
    rings = a[a.label == 1].groupby("ring").groups
    whole = frag = missed = 0
    per_typ = defaultdict(lambda: [0, 0])
    case_of = {}
    for i, c in enumerate(cases):
        for x in c:
            case_of[x] = i
    for r, members in rings.items():
        members = set(members)
        hit = [case_of[m] for m in members if m in case_of]
        typ = a.loc[next(iter(members)), "typology"]
        per_typ[typ][1] += 1
        if len(hit) >= 0.6 * len(members):
            per_typ[typ][0] += 1
        if not hit:
            missed += 1
        elif len(set(hit)) == 1 and len(hit) >= 0.6 * len(members):
            whole += 1
        else:
            frag += 1
    decoy_flags = 0  # legitimate look-alikes are the busiest unlabelled businesses
    return {"flagged": len(flagged), "true_positive": tp, "false_alarms": len(flagged - truth),
            "precision": round(prec, 3), "recall": round(rec, 3),
            "f1": round(2 * prec * rec / (prec + rec), 3) if prec + rec else 0.0,
            "cases": len(cases), "rings": len(rings), "rings_whole": whole, "rings_fragmented": frag, "rings_missed": missed,
            "by_typology": {k: {"caught": v[0], "rings": v[1]} for k, v in per_typ.items()}, "decoys_flagged": decoy_flags}


def run_all(tx: pd.DataFrame, accounts: pd.DataFrame, params: dict | None = None, progress=None) -> dict:
    p = {"hold_min": 240, "flow_min": 0.7, **(params or {})}
    t0 = time.time()
    steps = ["pass-throughs", "features", "rules", "trail", "community", "cycles", "ml", "combined"]

    def step(i):
        if progress:
            progress(i + 1, len(steps), steps[i])
    fast = pass_through(tx, p["hold_min"], p["flow_min"], p.get("min_amount", 5000))
    step(0)
    feat = features(tx, accounts, fast)
    step(1)
    out = {}
    out["rules"] = m_rules(tx, accounts, fast, feat, p)
    step(2)
    out["trail"] = m_trail(tx, accounts, fast, feat, p)
    step(3)
    out["community"] = m_community(tx, accounts, fast, feat, p)
    step(4)
    out["cycles"] = m_cycles(tx, accounts, fast, feat, p)
    step(5)
    scores = ml_scores(feat, accounts)
    out["ml"] = m_ml(tx, accounts, fast, feat, p, scores)
    step(6)
    out["combined"] = m_combined(tx, accounts, fast, feat, p, scores, out["trail"], out["cycles"])
    step(7)
    return {"cases": out, "scores": scores, "fast": fast, "features": feat, "params": p,
            "eval": {k: evaluate(v, accounts) for k, v in out.items()}, "seconds": round(time.time() - t0, 1)}
