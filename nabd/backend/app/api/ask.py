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



# ---- who is asking: persona and memory ---------------------------------------------------------------------------

@router.get("/profile")
def get_profile():
    from ..agents import profile
    return profile.profile()


class Role(BaseModel):
    role: str = Field(pattern="^(investment|economics|aml|risk|executive)$")


@router.put("/profile")
def put_profile(r: Role):
    from ..agents import profile
    return profile.set_role(r.role)


class Memory(BaseModel):
    text: str = Field(min_length=3, max_length=300)


@router.post("/memory")
def add_memory(m: Memory):
    from ..agents import profile
    return {"memory": profile.remember(m.text)}


@router.delete("/memory/{mem_id}")
def del_memory(mem_id: str):
    from ..agents import profile
    return {"memory": profile.forget(mem_id)}
