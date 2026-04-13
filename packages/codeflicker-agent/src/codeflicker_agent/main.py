import os
import json
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from python_a2a import A2AClient, Message, TextContent, MessageRole

from codeflicker_agent import llm, sse_logger

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../../../.env"))

SG_AGENT_A2A_URL = os.environ.get("SG_AGENT_A2A_URL", "http://localhost:3011")
SG_AGENT_BASE_URL = os.environ.get("SG_AGENT_BASE_URL", "http://localhost:3001")
PORT = int(os.environ.get("CF_AGENT_PORT", 3002))

app = FastAPI(title="codeflicker-agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

current_mode: str = "endpoint"


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/events")
async def events():
    return StreamingResponse(sse_logger.subscribe(), media_type="text/event-stream")


@app.post("/mode")
async def set_mode(request: Request):
    global current_mode
    body = await request.json()
    mode = body.get("mode", "endpoint")
    if mode not in ("endpoint", "mcp"):
        return JSONResponse({"error": "mode must be 'endpoint' or 'mcp'"}, status_code=400)
    current_mode = mode
    sse_logger.emit("Frontend", "CF-Agent", "mode-switch", mode)
    return {"mode": current_mode}


@app.get("/mode")
async def get_mode():
    return {"mode": current_mode}


def _call_sg_agent(user_text: str, mode: str) -> list:
    payload = json.dumps({"text": user_text, "mode": mode}, ensure_ascii=False)
    client = A2AClient(endpoint_url=SG_AGENT_A2A_URL)
    response_msg = client.send_message(
        Message(
            content=TextContent(text=payload),
            role=MessageRole.USER,
        )
    )

    parts = []
    if hasattr(response_msg, "content") and hasattr(response_msg.content, "text"):
        raw = response_msg.content.text
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                if "text" in data:
                    parts.append({"kind": "text", "text": data["text"]})
                if "mcp_ui_resource" in data:
                    parts.append(data["mcp_ui_resource"])
            else:
                parts.append({"kind": "text", "text": raw})
        except json.JSONDecodeError:
            parts.append({"kind": "text", "text": raw})
    return parts


@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    user_message: str = body.get("message", "")

    sse_logger.emit("Frontend", "CF-Agent", "chat", user_message[:50])
    sse_logger.emit("CF-Agent", "CF-LLM", "llm-call", "intent detection")

    intent = await llm.detect_intent(user_message)

    if intent == "query_data":
        span = sse_logger.emit_request(
            "CF-Agent", "SG-Agent", "A2A Task",
            params={"text": user_message[:80], "mode": current_mode},
        )
        parts = _call_sg_agent(user_message, current_mode)
        sse_logger.emit_response(
            span, "SG-Agent", "CF-Agent", "A2A Response",
            result={"parts_count": len(parts)},
        )
        return JSONResponse({"parts": parts})
    else:
        return JSONResponse({
            "parts": [{"kind": "text", "text": "您好！我是 CodeFlicker 助手，可以帮您查询快手员工趋势等数据。"}]
        })


@app.post("/tool-call")
async def tool_call(request: Request):
    body = await request.json()
    tool_name = body.get("toolName", "")
    tool_args = body.get("arguments", {})
    outer_span = sse_logger.emit_request(
        "Frontend", "CF-Agent", "tool-call",
        params={"toolName": tool_name},
    )

    if tool_name == "query_employee_trend_lazy":
        span = sse_logger.emit_request(
            "CF-Agent", "SG-Agent", "tool-result-fetch",
            params={"toolName": tool_name},
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{SG_AGENT_BASE_URL}/api/tool-result/{tool_name}")
        if resp.status_code == 200:
            result_data = resp.json()
            sse_logger.emit_response(
                span, "SG-Agent", "CF-Agent", "tool-result",
                result={"status": "ok"},
            )
            sse_logger.emit_response(
                outer_span, "CF-Agent", "Frontend", "tool-call",
                result={"status": "ok"},
            )
            return JSONResponse({"toolResult": result_data})
        sse_logger.emit_response(outer_span, "CF-Agent", "Frontend", "tool-call", detail="fallback")
        return JSONResponse({"toolResult": {
            "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
            "data": [
                {"year": 2019, "count": 7000},
                {"year": 2020, "count": 10000},
                {"year": 2021, "count": 16000},
                {"year": 2022, "count": 22000},
                {"year": 2023, "count": 18000},
            ],
            "token": "mock-stargate-token-12345",
        }})

    tool_text_map = {
        "query_employee_trend": "查询快手历年员工人数趋势",
    }
    user_text = tool_args.get("query") or tool_text_map.get(tool_name, f"调用工具 {tool_name}")
    a2a_span = sse_logger.emit_request(
        "CF-Agent", "SG-Agent", "A2A Task",
        params={"text": user_text[:80], "mode": current_mode},
    )
    parts = _call_sg_agent(user_text, current_mode)
    sse_logger.emit_response(
        a2a_span, "SG-Agent", "CF-Agent", "A2A Response",
        result={"parts_count": len(parts)},
    )
    tool_result_part = next((p for p in parts if p.get("kind") == "mcp_ui_resource"), None)
    if tool_result_part:
        sse_logger.emit_response(
            outer_span, "CF-Agent", "Frontend", "tool-call",
            result={"status": "ok"},
        )
        return JSONResponse({"toolResult": tool_result_part.get("toolResult", {})})
    sse_logger.emit_response(outer_span, "CF-Agent", "Frontend", "tool-call", detail="no result")
    return JSONResponse({"toolResult": {}})


@app.post("/tool-result")
async def tool_result_fetch(request: Request):
    body = await request.json()
    tool_name = body.get("toolName", "query_employee_trend")
    sse_logger.emit("Frontend", "CF-Agent", "tool-result-pull", tool_name)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{SG_AGENT_BASE_URL}/api/tool-result/{tool_name}"
        )
        if resp.status_code == 200:
            return JSONResponse(resp.json())
    return JSONResponse({
        "data": [
            {"year": 2019, "count": 7000},
            {"year": 2020, "count": 10000},
            {"year": 2021, "count": 16000},
            {"year": 2022, "count": 22000},
            {"year": 2023, "count": 18000},
        ],
        "token": "mock-stargate-token-12345",
    })


@app.get("/resource-proxy")
async def resource_proxy(uri: str, source: str = "host"):
    outer_span = sse_logger.emit_request(
        "Frontend", "CF-Agent", "resource-proxy",
        params={"uri": uri, "source": source},
    )
    if uri.startswith("ui://stargate/"):
        inner_span = sse_logger.emit_request(
            "CF-Agent", "SG-Agent", "mcp-resources/read",
            params={"uri": uri, "source": source},
        )
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{SG_AGENT_BASE_URL}/mcp/resources/read",
                params={"uri": uri},
            )
            data = resp.json()
            sse_logger.emit_response(
                inner_span, "SG-Agent", "CF-Agent", "mcp-resources/read",
                result={"status": resp.status_code},
            )
            sse_logger.emit_response(
                outer_span, "CF-Agent", "Frontend", "resource-proxy",
                result={"status": resp.status_code},
            )
            return JSONResponse(data)
    sse_logger.emit_response(outer_span, "CF-Agent", "Frontend", "resource-proxy", detail="error: unknown host")
    return JSONResponse({"error": "Unknown resource host"}, status_code=404)


def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
