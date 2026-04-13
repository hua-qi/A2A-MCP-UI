import time
import uuid
from dataclasses import dataclass, field
from typing import Any

TTL = 3600

@dataclass
class CardInstance:
    component_name: str
    container_name: str
    remote_entry_url: str
    props: dict[str, Any]
    created_at: float = field(default_factory=time.time)

_store: dict[str, CardInstance] = {}

def put(component_name: str, container_name: str, remote_entry_url: str, props: dict[str, Any]) -> str:
    cid = str(uuid.uuid4())
    _store[cid] = CardInstance(component_name, container_name, remote_entry_url, props)
    return cid

def get(cid: str) -> CardInstance | None:
    inst = _store.get(cid)
    if inst is None:
        return None
    if time.time() - inst.created_at > TTL:
        del _store[cid]
        return None
    return inst
