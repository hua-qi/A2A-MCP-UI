import asyncio
import json
import uuid
from datetime import datetime
from typing import AsyncGenerator

_queues: list[asyncio.Queue] = []
_loop: asyncio.AbstractEventLoop | None = None

def _now() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def _emit_raw(source: str, target: str, msg_type: str, detail: str,
              span_id: str | None = None, direction: str | None = None) -> None:
    event = json.dumps({
        "time": _now(),
        "source": source,
        "target": target,
        "type": msg_type,
        "detail": detail,
        "span_id": span_id,
        "direction": direction,
    })
    for q in list(_queues):
        if _loop is not None and _loop.is_running():
            _loop.call_soon_threadsafe(q.put_nowait, event)
        else:
            try:
                q.put_nowait(event)
            except Exception:
                pass

async def subscribe() -> AsyncGenerator[str, None]:
    global _loop
    _loop = asyncio.get_event_loop()
    q: asyncio.Queue = asyncio.Queue()
    _queues.append(q)
    connected_event = json.dumps({
        "time": _now(),
        "source": "System",
        "target": "EventLog",
        "type": "connected",
        "detail": "EventLog connected",
    })
    await q.put(connected_event)
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=15.0)
                yield f"data: {event}\n\n"
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
    finally:
        _queues.remove(q)

def emit(source: str, target: str, msg_type: str, detail: str = "") -> None:
    _emit_raw(source, target, msg_type, detail)

def emit_request(source: str, target: str, msg_type: str,
                 detail: str = "", params: dict | None = None) -> str:
    span_id = str(uuid.uuid4())[:8]
    if params:
        detail = (detail + "\n" + json.dumps(params, ensure_ascii=False))[:300]
    _emit_raw(source, target, msg_type, detail, span_id=span_id, direction="request")
    return span_id

def emit_response(span_id: str, source: str, target: str, msg_type: str,
                  detail: str = "", result: dict | list | None = None) -> None:
    if result:
        detail = (detail + "\n" + json.dumps(result, ensure_ascii=False))[:300]
    _emit_raw(source, target, msg_type, detail, span_id=span_id, direction="response")
