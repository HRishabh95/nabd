"""Verification of deep-research claims, before anything reaches the committee.

Two independent checks per claim:
1. Mechanical (no LLM): every cited evidence id exists, and every figure written in the claim can be found in the
   cited evidence (allowing for rounding, % versus fraction, and sign written as words).
2. A separate verifier model reads each claim next to its cited evidence and judges support.
A claim the verifier rejects, or that cites no valid evidence, is removed from the report and listed as removed.
Web sources outside the official allowlist are flagged.
"""

from __future__ import annotations

import json
import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel

from ..llm.gateway import gateway
from . import agent

NUM = re.compile(r"(?<![A-Za-z0-9])[-−+]?\d[\d,]*(?:\.\d+)?")


def claims(state: dict) -> list[dict]:
    out = []
    for hid, f in (state.get("findings") or {}).items():
        for side in ("evidence_for", "evidence_against"):
            for i, p in enumerate(f.get(side) or []):
                out.append({"id": f"{hid}.{'for' if side == 'evidence_for' else 'against'}.{i}", "text": p["text"],
                            "evidence": p.get("evidence") or []})
    for i, p in enumerate((state.get("red_team") or {}).get("points") or []):
        out.append({"id": f"RT.{i}", "text": p["text"], "evidence": p.get("evidence") or []})
    return out


def _numbers_in_text(text: str) -> list[tuple[float, int]]:
    out = []
    for m in NUM.finditer(text):
        raw = m.group(0).replace(",", "").replace("−", "-").lstrip("+")
        try:
            v = float(raw)
        except ValueError:
            continue
        dec = len(raw.split(".")[1]) if "." in raw else 0
        if dec == 0 and (abs(v) < 10 or 1990 <= v <= 2100):  # small counts and years are not checked
            continue
        out.append((v, dec))
    return out


def _numbers_in(obj, acc: list[float]):
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        acc.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers_in(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _numbers_in(v, acc)
    elif isinstance(obj, str):
        for v, _ in _numbers_in_text(obj):
            acc.append(v)


def traced(n: float, dec: int, pool: list[float]) -> bool:
    tol = 0.5 * 10 ** (-dec) + 1e-9
    a = abs(n)
    for v in pool:
        for cand in (abs(v), abs(v) * 100, abs(v) / 1000, abs(v) * 1000):
            if abs(cand - a) <= tol * max(1.0, 1.0 if cand < 1000 else cand / 1000):
                return True
    return False


def mechanical(claim: dict, evidence: dict) -> dict:
    valid = [e for e in claim["evidence"] if e in evidence]
    pool: list[float] = []
    for e in valid:
        _numbers_in(evidence[e]["result"], pool)
        _numbers_in(evidence[e]["args"], pool)
    nums = _numbers_in_text(claim["text"])
    untraced = [f"{v:g}" for v, d in nums if not traced(v, d, pool)]
    return {"valid_evidence": valid, "missing_evidence": [e for e in claim["evidence"] if e not in evidence],
            "numbers": len(nums), "untraced": untraced}


class ClaimCheck(BaseModel):
    id: str
    status: Literal["supported", "partly", "unsupported"]
    note: str


class Checks(BaseModel):
    checks: list[ClaimCheck]


def _claim_terms(claim: str) -> list[str]:
    return [m.group(0) for m in NUM.finditer(claim) if len(m.group(0)) >= 3] + re.findall(r"[A-Za-z]{6,}", claim)[:10]


def _relevant(result, claim: str):
    """For evidence holding page text, keep only the passages that bear on this claim (its figures and words).
    For document searches, read the cached full text of each hit rather than the query-matched snippet."""
    from ..core.db import conn
    from ..data.connectors import docs
    terms = _claim_terms(claim)
    if isinstance(result, dict) and isinstance(result.get("page"), dict) and result["page"].get("text"):
        page = dict(result["page"])
        page["text"] = docs.passages(page["text"], terms, n=4, width=600)
        return {**{k: v for k, v in result.items() if k not in ("page", "passages")}, "page": page}
    if isinstance(result, list) and result and isinstance(result[0], dict) and result[0].get("url"):
        out = []
        for h in result[:4]:
            row = conn().execute("SELECT text FROM doc_text WHERE url=?", (h["url"],)).fetchone()
            text = row["text"] if row else ""
            out.append({"title": h.get("title"), "source": h.get("source"), "published": h.get("published"),
                        "passages": docs.passages(text, terms, n=3, width=500) if text else h.get("passages")})
        return out
    return result


def _page_texts(evidence: dict) -> dict[str, str]:
    out = {}
    for eid, e in evidence.items():
        r = e["result"]
        if isinstance(r, dict) and isinstance(r.get("page"), dict) and r["page"].get("text"):
            out[eid] = r["page"]["text"]
    return out


def autolink(claim: dict, evidence: dict, pages: dict[str, str]) -> list[str]:
    """For a claim citing nothing, find captured pages that contain most of its figures."""
    nums = [n for n, _ in _numbers_in_text(claim["text"])]
    if len(nums) < 2:
        return []
    hits = []
    for eid, text in pages.items():
        pool = [v for v, _ in _numbers_in_text(text)]
        found = sum(traced(n, 1, pool) for n in nums)
        if found >= max(2, len(nums) // 2):
            hits.append((found, eid))
    return [eid for _, eid in sorted(hits, reverse=True)[:2]]


def _compact(result, limit: int = 2400) -> str:
    s = json.dumps(result, default=str)
    if len(s) <= limit:
        return s
    if isinstance(result, dict) and "page" not in result:  # drop chart arrays first; long and not needed
        result = {k: v for k, v in result.items() if k != "chart"}
        s = json.dumps(result, default=str)
    return s[:limit] + "…"


async def verify(state: dict, evidence: dict, on_event=None) -> dict:
    cs = claims(state)
    pages = _page_texts(evidence)
    for c in cs:  # claims that cite nothing: link pages Nabd captured that contain their figures
        if not [e for e in c["evidence"] if e in evidence]:
            linked = autolink(c, evidence, pages)
            if linked:
                c["evidence"], c["auto_linked"] = linked, linked
    mech = {c["id"]: mechanical(c, evidence) for c in cs}
    packet = [{"id": c["id"], "claim": c["text"],
               "evidence": {e: {"tool": evidence[e]["tool"], "args": evidence[e]["args"],
                                "result": _compact(_relevant(evidence[e]["result"], c["text"]))}
                            for e in mech[c["id"]]["valid_evidence"]},
               "figures_not_found_in_evidence": mech[c["id"]]["untraced"]} for c in cs]
    llm: dict[str, dict] = {}
    if packet:
        res = await gateway.run("deep-verify", agent.BASE_RULES + (
            " You are an independent verifier. For each claim, judge only whether the cited evidence supports it. "
            "'supported': the evidence clearly backs the claim, figures match. 'partly': direction right but a figure "
            "or nuance is off, or it overstates. 'unsupported': the evidence does not back it or is missing. "
            "Be strict; one short note per claim."),
            json.dumps({"claims": packet}, indent=1, default=str), schema=Checks, on_event=on_event,
            timeout_seconds=420)
        llm = {c.id: c.model_dump() for c in res.parsed.checks}
    results = []
    for c in cs:
        m, v = mech[c["id"]], llm.get(c["id"], {"status": "partly", "note": "not reviewed"})
        status = v["status"]
        if not m["valid_evidence"]:
            status = "unsupported"
        elif status == "supported" and m["untraced"]:
            status = "partly"
        results.append({"id": c["id"], "text": c["text"], "status": status, "note": v["note"],
                        "auto_linked": c.get("auto_linked", []), **m})
    web = [e for e in evidence.values() if e["tool"] == "web_search"]
    urls = [r.get("url") for e in web for r in (e["result"].get("results") or []) if isinstance(r, dict) and r.get("url")]
    from .deep import OFFICIAL_DOMAINS
    non_official = sorted({u for u in urls if not any(urlparse(u).netloc.endswith(d) for d in OFFICIAL_DOMAINS)})
    n_nums = sum(r["numbers"] for r in results)
    n_untraced = sum(len(r["untraced"]) for r in results)
    stats = {"claims": len(results), "supported": sum(r["status"] == "supported" for r in results),
             "partly": sum(r["status"] == "partly" for r in results),
             "unsupported": sum(r["status"] == "unsupported" for r in results),
             "figures_checked": n_nums, "figures_traced": n_nums - n_untraced,
             "auto_linked": sum(bool(r["auto_linked"]) for r in results),
             "evidence_items": len(evidence), "web_searches": len(web), "non_official_urls": non_official[:10]}
    return {"stats": stats, "claims": results}


def filtered_findings(state: dict) -> dict:
    """Findings with unsupported claims removed and partly-supported claims annotated."""
    status = {c["id"]: c for c in (state.get("verification") or {}).get("claims", [])}
    out = {}
    for hid, f in (state.get("findings") or {}).items():
        g = dict(f)
        for side, tag in (("evidence_for", "for"), ("evidence_against", "against")):
            kept = []
            for i, p in enumerate(f.get(side) or []):
                c = status.get(f"{hid}.{tag}.{i}")
                if c and c["status"] == "unsupported":
                    continue
                kept.append({**p, "check": c["status"] if c else None})
            g[side] = kept
        out[hid] = g
    return out
