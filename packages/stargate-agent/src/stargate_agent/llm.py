import os
import json
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

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_employee_trend",
            "description": "查询快手历年员工人数趋势数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "公司名称"},
                },
                "required": ["company"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_employee_trend_lazy",
            "description": "懒加载方式查询快手历年员工人数趋势，卡片先渲染后由卡片自身异步拉取数据",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_github",
            "description": "打开 GitHub 主页，在卡片中以 iframe 方式展示 GitHub 网站",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

async def select_tool(user_message: str) -> tuple[str, dict]:
    client = _get_client()
    model = os.environ.get("LLM_MODEL", "gpt-4o")
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": user_message}],
        tools=TOOLS,
        tool_choice="auto",
    )
    msg = response.choices[0].message
    if msg.tool_calls:
        tc = msg.tool_calls[0]
        return tc.function.name, json.loads(tc.function.arguments)
    return "none", {}
