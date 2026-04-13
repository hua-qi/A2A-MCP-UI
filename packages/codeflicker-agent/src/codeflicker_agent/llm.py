import os
from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None

def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
    return _client

async def detect_intent(user_message: str) -> str:
    """返回 'query_data' 或 'general_chat'"""
    client = _get_client()
    model = os.environ.get("LLM_MODEL", "gpt-4o")
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是 CodeFlicker 助手的意图识别器。"
                    "如果用户想查询数据（如员工、财务、趋势等），回复 'query_data'；"
                    "否则回复 'general_chat'。只返回这两个值之一，不要其他内容。"
                ),
            },
            {"role": "user", "content": user_message},
        ],
    )
    return response.choices[0].message.content.strip()
