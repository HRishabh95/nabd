from pydantic import BaseModel

from app.core.bus import EventBus
from app.llm.codex_session import output_schema, profile_extensions


def test_bus_delivers_and_replays():
    bus = EventBus(history=10)
    first = bus.publish("a", x=1)
    q = bus.subscribe(last_id=0)
    assert q.get_nowait().id == first.id
    bus.publish("b", x=2)
    assert q.get_nowait().type == "b"


def test_bus_drops_oldest_when_full():
    bus = EventBus(queue_size=2)
    q = bus.subscribe()
    for i in range(3):
        bus.publish("e", i=i)
    assert [q.get_nowait().data["i"] for _ in range(2)] == [1, 2]


class Inner(BaseModel):
    v: float | None = None


class Outer(BaseModel):
    name: str
    inner: Inner


def test_output_schema_is_strict():
    s = output_schema(Outer)
    assert s["additionalProperties"] is False and set(s["required"]) == {"name", "inner"}
    inner = s["$defs"]["Inner"]
    assert inner["required"] == ["v"] and "default" not in inner["properties"]["v"]


def test_profile_extensions_missing_file(tmp_path):
    assert profile_extensions(str(tmp_path)) == []
