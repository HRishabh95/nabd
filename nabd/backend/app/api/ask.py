"""Ask Nabd API. Answers run as background jobs and stream as ask.tool, ask.text and ask.done events."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..agents import ask

router = APIRouter(prefix="/api/ask")


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    thread_id: str | None = None
    context: dict = {}


@router.post("")
async def post(q: Question):
    return ask.ask(q.question, q.thread_id, q.context)


@router.get("/threads")
def threads():
    return {"threads": ask.threads()}


@router.get("/threads/{thread_id}")
def thread(thread_id: str):
    msgs = ask.history(thread_id, 100)
    if not msgs:
        raise HTTPException(404, "unknown thread")
    return {"thread_id": thread_id, "messages": msgs}
