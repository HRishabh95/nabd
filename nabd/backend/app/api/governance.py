"""Governance API: AI evaluation, human review of AI outputs, headline-label accuracy, validation packs."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..monitoring import governance as gov

router = APIRouter(prefix="/api/governance")


@router.get("/evaluation")
def evaluation():
    return gov.evaluation()


class Review(BaseModel):
    kind: str = Field(pattern="^(research|fraud_note|ask|thesis|proposal)$")
    ref: str = Field(min_length=1, max_length=120)
    verdict: int = Field(ge=-1, le=1)
    comment: str = Field("", max_length=500)


@router.post("/review")
def review(r: Review):
    if r.verdict == 0:
        raise HTTPException(400, "verdict must be 1 or -1")
    return gov.review(r.kind, r.ref, r.verdict, r.comment)


@router.get("/review/{kind}/{ref}")
def reviews(kind: str, ref: str):
    return gov.reviews_for(kind, ref)


@router.get("/labels/sample")
def label_sample(n: int = 10):
    return {"items": gov.label_sample(max(1, min(n, 30)))}


class Label(BaseModel):
    id: str = Field(min_length=4, max_length=40)
    relevant: bool
    direction: int | None = Field(None, ge=-2, le=2)


@router.post("/labels")
def add_labels(items: list[Label]):
    for x in items[:50]:
        gov.add_label(x.id, x.relevant, x.direction)
    return gov.label_agreement()


@router.get("/pack/{key}", response_class=HTMLResponse)
def pack(key: str):
    try:
        return gov.pack(key)
    except KeyError as exc:
        raise HTTPException(404, "Unknown model") from exc
