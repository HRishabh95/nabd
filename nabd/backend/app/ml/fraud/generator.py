"""Synthetic, labelled payment network for the fraud POC (AMLSim-style).

Real interbank payment data is not public, so Nabd generates two weeks of instant payments across six banks, using
the laundering typologies defined by IBM AMLSim (fan-in, fan-out, cycle, scatter-gather, gather-scatter, stacked
layering) plus a cross-bank mule ring, on top of ordinary activity: salaries, merchant payments, bills and
person-to-person transfers. Legitimate look-alikes are included on purpose (payroll processors, money exchanges,
busy merchants), because they are what simple rules flag wrongly. Every laundering transfer carries its typology
and ring id, so detection methods can be scored. IBM AMLSim's own output, or CBUAE data, can replace these files.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ...core.config import get_settings

BANKS = ["Bank A", "Bank B", "Bank C", "Bank D", "Bank E", "Bank F"]
DAYS = 14
START = pd.Timestamp("2026-11-02")


def _ts(rng, n, day=None, hour_lo=7, hour_hi=23):
    d = rng.integers(0, DAYS, n) if day is None else np.full(n, day)
    minutes = rng.integers(hour_lo * 60, hour_hi * 60, n)
    return START + pd.to_timedelta(d, "D") + pd.to_timedelta(minutes, "m")


def generate(n_accounts: int = 6000, seed: int = 11) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    kinds = rng.choice(["individual", "business"], n_accounts, p=[0.86, 0.14])
    accounts = pd.DataFrame({
        "account": [f"AC{i:05d}" for i in range(n_accounts)],
        "bank": rng.choice(BANKS, n_accounts, p=[0.26, 0.22, 0.18, 0.14, 0.12, 0.08]),
        "kind": kinds,
        "opened_days_ago": rng.integers(30, 3000, n_accounts),
        "label": 0, "typology": "", "ring": "",
    })
    ind = accounts.index[accounts.kind == "individual"].to_numpy()
    biz = accounts.index[accounts.kind == "business"].to_numpy()
    rows: list[tuple] = []

    def add(src, dst, amt, ts, typ="", ring=""):
        for s, d, a, t in zip(np.atleast_1d(src), np.atleast_1d(dst), np.atleast_1d(amt), np.atleast_1d(ts)):
            if s != d:
                rows.append((int(s), int(d), float(round(a, 2)), t, typ, ring))

    # --- ordinary activity -------------------------------------------------------------------------------
    employers = rng.choice(biz, 120, replace=False)
    emp_of = rng.choice(employers, len(ind))
    pay_day = rng.integers(0, DAYS, len(employers))
    for e, d in zip(employers, pay_day):  # salaries: one payroll run per employer in the window
        staff = ind[emp_of == e]
        add(np.full(len(staff), e), staff, rng.lognormal(9.3, 0.5, len(staff)), _ts(rng, len(staff), day=d, hour_lo=8, hour_hi=11))
    merchants = rng.choice(biz, 300, replace=False)
    n = len(ind) * 9  # card-like payments to merchants
    add(rng.choice(ind, n), rng.choice(merchants, n, p=_pareto(rng, len(merchants))), rng.lognormal(5.0, 1.0, n), _ts(rng, n))
    contacts = {a: rng.choice(ind, rng.integers(3, 12)) for a in ind}  # person-to-person within small circles
    n = len(ind) * 3
    src = rng.choice(ind, n)
    add(src, [rng.choice(contacts[s]) for s in src], rng.lognormal(6.3, 1.0, n), _ts(rng, n))
    n = len(biz) * 25  # business-to-business
    add(rng.choice(biz, n), rng.choice(biz, n), rng.lognormal(9.0, 1.2, n), _ts(rng, n, hour_lo=8, hour_hi=18))

    # --- legitimate look-alikes that simple rules flag ----------------------------------------------------
    used = set(employers) | set(merchants)
    free_biz = np.array([b for b in biz if b not in used])
    decoys = rng.choice(free_biz, 24, replace=False)
    for k, dcy in enumerate(decoys):
        if k % 3 == 0:  # payroll processor: large inflow from clients, same-day fan-out to many staff
            clients = rng.choice(biz, 6)
            amt = rng.lognormal(12.0, 0.3, 6)
            day = int(rng.integers(0, DAYS - 1))
            add(clients, np.full(6, dcy), amt, _ts(rng, 6, day=day, hour_lo=8, hour_hi=10))
            staff = rng.choice(ind, 60)
            add(np.full(60, dcy), staff, np.full(60, amt.sum() * 0.98 / 60) * rng.uniform(0.7, 1.3, 60), _ts(rng, 60, day=day, hour_lo=12, hour_hi=16))
        elif k % 3 == 1:  # exchange house: many small inflows, quick large outflow to a bank partner
            senders = rng.choice(ind, 80)
            add(senders, np.full(80, dcy), rng.lognormal(7.5, 0.6, 80), _ts(rng, 80))
            add(np.full(4, dcy), rng.choice(biz, 4), rng.lognormal(11.5, 0.3, 4), _ts(rng, 4))
        else:  # busy merchant with rapid settlement out
            payers = rng.choice(ind, 150)
            add(payers, np.full(150, dcy), rng.lognormal(5.5, 0.8, 150), _ts(rng, 150))
            add(np.full(14, dcy), rng.choice(biz, 14), rng.lognormal(10.5, 0.3, 14), _ts(rng, 14))

    # --- laundering typologies (labelled) -----------------------------------------------------------------
    pool = list(rng.permutation(ind))
    ring_no = 0

    def take(k):
        return np.array([pool.pop() for _ in range(k)])

    def label(ids, typ, ring):
        accounts.loc[ids, ["label", "typology", "ring"]] = [1, typ, ring]

    def t0():
        return START + pd.Timedelta(days=int(rng.integers(0, DAYS - 2)), hours=int(rng.integers(8, 20)))

    def hop(t, lo=5, hi=90):
        return t + pd.Timedelta(minutes=int(rng.integers(lo, hi)))

    for _ in range(5):  # fan-in then out: many feeders to one collector who forwards quickly
        ring_no += 1
        r = f"R{ring_no:02d}"
        feeders, coll, exit_ = take(int(rng.integers(8, 15))), take(1)[0], take(1)[0]
        t = t0()
        amts = rng.uniform(9000, 14000, len(feeders))  # just under a 15k reporting-style threshold
        add(feeders, np.full(len(feeders), coll), amts, [hop(t, 0, 240) for _ in feeders], "fan_in", r)
        add(coll, exit_, amts.sum() * 0.97, hop(t, 250, 330), "fan_in", r)
        label(np.r_[feeders, coll, exit_], "fan_in", r)
    for _ in range(4):  # fan-out: one source splits to many mules who each forward
        ring_no += 1
        r = f"R{ring_no:02d}"
        src, mules, sink = take(1)[0], take(int(rng.integers(8, 14))), take(1)[0]
        t = t0()
        total = rng.uniform(250000, 500000)
        split = total * rng.dirichlet(np.ones(len(mules)))
        add(np.full(len(mules), src), mules, split, [hop(t) for _ in mules], "fan_out", r)
        add(mules, np.full(len(mules), sink), split * 0.96, [hop(t, 120, 400) for _ in mules], "fan_out", r)
        label(np.r_[src, mules, sink], "fan_out", r)
    for _ in range(5):  # cycles: money returns to its origin through 4 to 7 accounts
        ring_no += 1
        r = f"R{ring_no:02d}"
        ids = take(int(rng.integers(4, 8)))
        t, amt = t0(), rng.uniform(80000, 200000)
        for i in range(len(ids)):
            t = hop(t, 10, 180)
            add(ids[i], ids[(i + 1) % len(ids)], amt, t, "cycle", r)
            amt *= rng.uniform(0.96, 0.99)
        label(ids, "cycle", r)
    for _ in range(4):  # scatter-gather: source to intermediates to one sink
        ring_no += 1
        r = f"R{ring_no:02d}"
        src, mid, sink = take(1)[0], take(int(rng.integers(5, 10))), take(1)[0]
        t, total = t0(), rng.uniform(150000, 400000)
        split = total * rng.dirichlet(np.ones(len(mid)))
        add(np.full(len(mid), src), mid, split, [hop(t) for _ in mid], "scatter_gather", r)
        add(mid, np.full(len(mid), sink), split * 0.97, [hop(t, 100, 500) for _ in mid], "scatter_gather", r)
        label(np.r_[src, mid, sink], "scatter_gather", r)
    for _ in range(3):  # gather-scatter: many to one hub, then out to many
        ring_no += 1
        r = f"R{ring_no:02d}"
        ins, hub, outs = take(int(rng.integers(5, 9))), take(1)[0], take(int(rng.integers(5, 9)))
        t = t0()
        amts = rng.uniform(20000, 60000, len(ins))
        add(ins, np.full(len(ins), hub), amts, [hop(t, 0, 200) for _ in ins], "gather_scatter", r)
        add(np.full(len(outs), hub), outs, amts.sum() * 0.96 * rng.dirichlet(np.ones(len(outs))), [hop(t, 220, 400) for _ in outs], "gather_scatter", r)
        label(np.r_[ins, hub, outs], "gather_scatter", r)
    for _ in range(4):  # stacked layering: parallel chains across banks, short holds
        ring_no += 1
        r = f"R{ring_no:02d}"
        chains = [take(int(rng.integers(4, 6))) for _ in range(3)]
        t = t0()
        for ch in chains:
            amt, tt = rng.uniform(60000, 150000), t
            for a, b in zip(ch[:-1], ch[1:]):
                tt = hop(tt, 8, 120)
                add(a, b, amt, tt, "layering", r)
                amt *= rng.uniform(0.97, 0.995)
            label(ch, "layering", r)
    ring_no += 1  # the mule ring: ~40 accounts across all six banks, recruited victims feeding it
    r = f"R{ring_no:02d}"
    ring = take(40)
    accounts.loc[ring, "bank"] = np.resize(BANKS, len(ring))
    victims = take(25)
    t = t0()
    layers = [ring[:12], ring[12:24], ring[24:34], ring[34:]]
    for v in victims:  # victims pay the first layer over the morning
        add(v, rng.choice(layers[0]), rng.uniform(5000, 40000), hop(t, 0, 180), "mule_ring", r)
    base = t + pd.Timedelta(minutes=200)
    held = {a: 0.0 for a in ring}
    for v_amt, dst in [(x[2], x[1]) for x in rows if x[4] == "mule_ring" and x[5] == r]:
        held[dst] = held.get(dst, 0.0) + v_amt
    for i in range(3):  # each layer forwards what it received within the hour, split across two accounts
        for a in layers[i]:
            amt = held.get(a, 0.0) or rng.uniform(15000, 40000)
            nxt = rng.choice(layers[i + 1], 2, replace=False)
            for b, share in zip(nxt, rng.dirichlet([2, 2])):
                add(a, b, amt * share * rng.uniform(0.96, 0.99), base + pd.Timedelta(minutes=int(i * 60 + rng.integers(5, 50))),
                    "mule_ring", r)
                held[b] = held.get(b, 0.0) + amt * share * 0.97
    label(ring, "mule_ring", r)  # victims are not launderers; they stay unlabelled

    tx = pd.DataFrame(rows, columns=["src", "dst", "amount", "ts", "typology", "ring"])
    tx["src"] = accounts.account.values[tx.src]
    tx["dst"] = accounts.account.values[tx.dst]
    tx = tx.sort_values("ts").reset_index(drop=True)
    tx.insert(0, "tx_id", [f"TX{i:07d}" for i in range(len(tx))])
    tx["laundering"] = (tx.typology != "").astype(int)
    tx["cross_bank"] = (accounts.set_index("account").bank.reindex(tx.src).values !=
                        accounts.set_index("account").bank.reindex(tx.dst).values).astype(int)
    return accounts, tx


def _pareto(rng, n):
    w = rng.pareto(1.3, n) + 1
    return w / w.sum()


def path():
    p = get_settings().data_dir / "fraud"
    p.mkdir(parents=True, exist_ok=True)
    return p


def build(seed: int = 11) -> dict:
    accounts, tx = generate(seed=seed)
    accounts.to_parquet(path() / "accounts.parquet", index=False)
    tx.to_parquet(path() / "transactions.parquet", index=False)
    return {"accounts": len(accounts), "transactions": len(tx), "laundering_accounts": int(accounts.label.sum()),
            "rings": int(accounts.ring.replace("", np.nan).nunique()), "laundering_transfers": int(tx.laundering.sum())}


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not (path() / "transactions.parquet").exists():
        build()
    return pd.read_parquet(path() / "accounts.parquet"), pd.read_parquet(path() / "transactions.parquet")
