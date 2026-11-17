"""AI investigation notes for a detected network, grounded in its own transfers and the models' results.

The LLM sees what an investigator would: the network's accounts (bank, type, age, money in and out, ML risk score,
role in the flow), every transfer between them with time and amount, the money that came in from and left to
outside accounts, the graph pattern, and the hold times. It does not see the synthetic labels: those are kept for
scoring the models. Every transfer it cites is checked against the data, and any that does not match is dropped.
"""

from __future__ import annotations

import time

from pydantic import BaseModel, Field

from ...core.db import store as kv

RULES = """You are an anti-money-laundering analyst at the Central Bank of the UAE writing an investigation note on a
network of accounts flagged by Nabd's detection models. The data is synthetic (a demonstration).
Use only the facts given: accounts, transfers, amounts, times, banks, risk scores, roles, the graph pattern and the
hold times. Never invent a transfer, an account, an amount, a name or a customer detail. When you cite a transfer,
copy its time, sender, receiver and amount exactly from the list. Write plainly for a supervisor who is not a data
scientist: short sentences, amounts in AED, times as given. Say what the evidence shows and what it does not."""


class Cited(BaseModel):
    ts: str = Field(description="Transfer time, exactly as listed")
    src: str
    dst: str
    amount: float = Field(description="AED, exactly as listed")
    why: str = Field(description="Why this transfer matters, one sentence")


class Note(BaseModel):
    headline: str = Field(description="One sentence: what this network appears to be doing")
    why_flagged: list[str] = Field(description="2-4 reasons the models flagged it, each tied to a number in the data")
    connections: str = Field(description="Two or three full sentences describing how money moves between these accounts: "
                                         "which account it enters at, which accounts it passes through (hub or loop), "
                                         "where it leaves, and which hops cross banks")
    transfers: list[Cited] = Field(description="The 3-6 most telling transfers")
    next_steps: list[str] = Field(description="3-5 concrete checks an investigator should do next")
    caveats: str = Field(description="What the data cannot show, one or two sentences")


def _facts(d: dict, account: str | None) -> str:
    f = d["flow"]
    lines = [f"Network {d['id']}: {d['size']} accounts across {d['banks']} banks ({', '.join(d['bank_list'])}).",
             f"Graph pattern found by Nabd: {d['pattern']['label']}" + (f" (hub {d['pattern']['hub']})" if d['pattern'].get('hub') else "") + ".",
             f"Moved inside the network: AED {d['flow_aed']:,.0f} in {d['transfers']} transfers, {d['first']} to {d['last']}.",
             f"Money in from outside: AED {d['money_in_aed']:,.0f} from {d['sources_outside']} accounts; "
             f"money out to outside: AED {d['money_out_aed']:,.0f} to {d['exits_outside']} accounts.",
             f"Share of the members' transfers that pass money straight on: {d['pass_through_share']:.0%}; "
             f"median time money sat in an account before moving on: {d['median_hold_min']} minutes.",
             f"Highest ML risk score in the network: {d['score']:.2f} (0 to 1; gradient-boosted trees on account behaviour).",
             "", "Accounts (role in the flow: entry = money enters the network here, pass = passes it on, exit = leaves):"]
    for m in d["members_detail"]:
        lines.append(f"- {m['account']}: {m['bank']}, {m['kind']}, opened {m['opened_days_ago']} days ago, role {m['role']}, "
                     f"ML risk {m['risk']:.2f}, total in AED {m['in_aed']:,.0f}, total out AED {m['out_aed']:,.0f}")
    lines += ["", "Transfers inside the network (time, from, to, AED, cross-bank):"]
    for t in d["timeline"][:80]:
        lines.append(f"- {t['ts']} | {t['src']} -> {t['dst']} | {t['amount']:,.0f} | {'cross-bank' if t['cross_bank'] else 'same bank'}")
    lines += ["", "Largest flows from outside into members (receiver, AED, transfers, first):"]
    lines += [f"- into {e['d']}: {e['amount']:,.0f} in {e['n']}, first {e['first']}" for e in f["in_edges"]]
    lines += ["Largest flows from members to outside (sender, AED, transfers, first):"]
    lines += [f"- from {e['s']}: {e['amount']:,.0f} in {e['n']}, first {e['first']}" for e in f["out_edges"]]
    if account:
        lines += ["", f"The investigator selected account {account}: focus the note on its part in the network."]
    return "\n".join(lines)


def _grounded(note: Note, d: dict) -> Note:
    real = {(t["src"], t["dst"], round(t["amount"])): t for t in d["timeline"]}
    ok = []
    for c in note.transfers:
        t = real.get((c.src, c.dst, round(c.amount)))
        if t:
            ok.append(c.model_copy(update={"ts": t["ts"], "amount": t["amount"]}))
    return note.model_copy(update={"transfers": ok})


def cached(run_id: str, case_id: str, account: str | None) -> dict | None:
    return kv.get(f"fraud:note:{run_id}:{case_id}:{account or ''}")


async def explain(d: dict, run_id: str, account: str | None = None) -> dict:
    from ...llm.gateway import gateway

    key = f"fraud:note:{run_id}:{d['id']}:{account or ''}"
    if (hit := kv.get(key)):
        return hit
    res = await gateway.run("fraud-note", RULES, "Write the investigation note.\n\n" + _facts(d, account),
                            schema=Note, timeout_seconds=240)
    note = res.parsed if isinstance(res.parsed, Note) else Note.model_validate_json(res.text)
    cited = len(note.transfers)
    note = _grounded(note, d)
    out = {**note.model_dump(), "checked": {"cited": cited, "matched": len(note.transfers)},
           "model": res.model, "created": time.time(), "case": d["id"], "account": account}
    kv.set(key, out)
    return out
