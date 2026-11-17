"""Health, doctor, and an LLM smoke test that proves tool calling and streaming end to end."""

import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.bus import bus
from ..core.config import get_settings
from ..core.doctor import checks
from ..llm.codex_session import Tool
from ..llm.gateway import gateway

router = APIRouter(prefix="/api/system")
STARTED = time.time()


@router.get("/health")
def health():
    s = get_settings()
    return {"ok": True, "uptime_s": int(time.time() - STARTED), "llm_provider": s.llm_provider,
            "subscribers": bus.subscriber_count}


@router.get("/doctor")
def doctor():
    return {"checks": checks()}


class SmokeAnswer(BaseModel):
    answer: str = Field(description="One sentence answer to the user")
    figure_usd_bn: float = Field(description="The figure returned by the tool, unchanged")
    source: str = Field(description="The source string returned by the tool")


def _reserves_fact(year: int) -> dict:
    facts = {2024: 231.0, 2025: 285.0}
    if year not in facts:
        raise ValueError("only 2024 and 2025 are available")
    return {"year": year, "net_fx_reserves_usd_bn": facts[year], "source": "CBUAE Annual Report 2025"}


RESERVES_TOOL = Tool(
    name="reserves_fact",
    description="Net foreign-currency reserves of the CBUAE at year end, in USD billions, with its source.",
    parameters={"type": "object", "properties": {"year": {"type": "integer"}}, "required": ["year"],
                "additionalProperties": False},
    fn=_reserves_fact,
)


@router.post("/llm-test")
async def llm_test():
    """Codex must call the backend tool to get the figure; progress streams on /api/stream as llm.* events."""
    run_id = f"smoke-{int(time.time())}"
    bus.publish("llm.start", run_id=run_id, purpose="smoke")

    def relay(kind, data):
        bus.publish(f"llm.{kind}", run_id=run_id, **{k: v for k, v in data.items() if k != "result"},
                    **({"result": data["result"]} if kind == "tool.result" else {}))

    try:
        result = await gateway.run(
            "smoke",
            "You are Nabd's test harness. Use the reserves_fact tool for any figure; never state a number "
            "the tool did not return.",
            "By how much did CBUAE net FX reserves change from 2024 to 2025? Call the tool for both years.",
            schema=SmokeAnswer,
            tools=[RESERVES_TOOL],
            on_event=relay,
        )
    except Exception as exc:
        bus.publish("llm.error", run_id=run_id, error=str(exc))
        raise HTTPException(502, str(exc)) from exc
    bus.publish("llm.done", run_id=run_id, ms=result.ms)
    return {"run_id": run_id, "model": result.model, "ms": result.ms, "answer": result.parsed.model_dump(),
            "tool_calls": [{k: c[k] for k in ("tool", "args", "ok", "ms")} for c in result.tool_calls]}
