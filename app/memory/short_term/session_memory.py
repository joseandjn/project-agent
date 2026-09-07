import json
from typing import List, TypedDict

from app.core.config import get_settings
from app.db.redis_client import get_redis_client


class Message(TypedDict):
    role: str
    content: str


def _history_key(session_id: str) -> str:
    return f"historial:{session_id}"


async def get_history(session_id: str) -> List[Message]:
    client = get_redis_client()
    raw = await client.get(_history_key(session_id))
    if raw is None:
        return []
    return json.loads(raw)


async def append_exchange(session_id: str, user_message: str, assistant_message: str) -> None:
    settings = get_settings()
    client = get_redis_client()

    history = await get_history(session_id)
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": assistant_message})

    await client.set(_history_key(session_id), json.dumps(history), ex=settings.session_ttl_seconds)
