import os
import json
import asyncio
import httpx
from dotenv import load_dotenv
from mcp.client.sse import sse_client
from mcp import ClientSession
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from python_a2a import A2AServer, Message, TextContent, MessageRole, AgentCard
from mcp_ui_server import create_ui_resource

from stargate_agent import card_cache, llm, sse_logger
from stargate_agent.shell_builder import MCP_INIT_SCRIPT

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../../../.env"))

RESOURCE_CENTER_URL = os.environ.get("RESOURCE_CENTER_URL", "http://localhost:3003")
PORT = int(os.environ.get("SG_AGENT_PORT", 3001))
A2A_PORT = 3011

app = FastAPI(title="stargate-agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

EMPLOYEE_DETAIL = {
    2019: {"year": 2019, "count": 7000, "note": "快速扩张期"},
    2020: {"year": 2020, "count": 10000, "note": "疫情期逆势增长"},
    2021: {"year": 2021, "count": 16000, "note": "业务多元化"},
    2022: {"year": 2022, "count": 22000, "note": "峰值"},
    2023: {"year": 2023, "count": 18000, "note": "降本增效"},
}

@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/events")
async def events():
    return StreamingResponse(sse_logger.subscribe(), media_type="text/event-stream")

@app.get("/api/card-instance/{card_id}")
async def get_card_instance(card_id: str):
    inst = card_cache.get(card_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="Card instance not found or expired")
    return {
        "componentName": inst.component_name,
        "containerName": inst.container_name,
        "remoteEntryUrl": inst.remote_entry_url,
        "props": inst.props,
    }

@app.post("/api/token/exchange")
async def token_exchange():
    return {"token": "mock-stargate-token-12345"}

@app.get("/api/tool-result/{tool_name}")
async def get_tool_result(tool_name: str):
    if tool_name in ("query_employee_trend", "query_employee_trend_lazy"):
        await asyncio.sleep(1.5)
        sse_logger.emit("SG-Agent", "BusinessAPI", "http", "GET /api/employee/trend")
        trend_resp = await _fetch_employee_trend()
        result = {
            "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
            "data": trend_resp["data"],
            "token": trend_resp["token"],
        }
        return result
    raise HTTPException(status_code=404, detail="Unknown tool")

@app.get("/api/employee/trend")
async def employee_trend():
    return {
        "data": [
            {"year": 2019, "count": 7000},
            {"year": 2020, "count": 10000},
            {"year": 2021, "count": 16000},
            {"year": 2022, "count": 22000},
            {"year": 2023, "count": 18000},
        ],
        "token": "mock-stargate-token-12345",
    }

@app.get("/api/employee/detail/{year}")
async def employee_detail(year: int, authorization: str = Header(default="")):
    span = sse_logger.emit_request(
        "Frontend", "SG-Agent", "http",
        params={"path": f"GET /api/employee/detail/{year}"},
    )
    if not authorization.startswith("Bearer "):
        sse_logger.emit_response(span, "SG-Agent", "Frontend", "http", detail="error: 401 missing token")
        raise HTTPException(status_code=401, detail="Missing token")
    detail = EMPLOYEE_DETAIL.get(year)
    if detail is None:
        sse_logger.emit_response(span, "SG-Agent", "Frontend", "http", detail="error: 404 year not found")
        raise HTTPException(status_code=404, detail="Year not found")
    sse_logger.emit_response(span, "SG-Agent", "Frontend", "http", result={"year": year, "count": detail["count"]})
    return detail

@app.get("/mcp/resources/read")
async def mcp_resources_read(uri: str):
    outer_span = sse_logger.emit_request(
        "CF-Agent", "SG-Agent", "mcp-resources/read",
        params={"uri": uri},
    )

    if uri in ("ui://stargate/employee-trend", "ui://stargate/employee-trend-lazy"):
        inner_span = sse_logger.emit_request(
            "SG-Agent", "MCP-Server", "mcp-resources/read",
            params={"uri": uri},
        )
        contents = await _read_mcp_resource(uri)
        sse_logger.emit_response(
            inner_span, "MCP-Server", "SG-Agent", "mcp-resources/read",
            result={"count": len(contents)},
        )
        sse_logger.emit_response(
            outer_span, "SG-Agent", "CF-Agent", "mcp-resources/read",
            result={"count": len(contents)},
        )
        return JSONResponse({"contents": contents})

    if uri.startswith("ui://stargate/card/"):
        card_id = uri.removeprefix("ui://stargate/card/")
        inst = card_cache.get(card_id)
        if inst is None:
            sse_logger.emit_response(outer_span, "SG-Agent", "CF-Agent", "mcp-resources/read", detail="error: not found")
            raise HTTPException(status_code=404, detail="Card instance not found or expired")

        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
</head>
<body style="margin:0">
<div id="root"></div>
<script src="{inst.remote_entry_url}"></script>
<script>
{MCP_INIT_SCRIPT}
(function() {{
  Promise.resolve().then(function() {{
    if (typeof {inst.container_name} === 'undefined') throw new Error('Container {inst.container_name} not found');
    var shareScope = Object.create(null);
    shareScope['default'] = {{}};
    shareScope['default']['react'] = {{
      '18.3.1': {{ get: function() {{ return function() {{ return React; }}; }}, loaded: 1, from: 'host' }}
    }};
    shareScope['default']['react-dom'] = {{
      '18.3.1': {{ get: function() {{ return function() {{ return ReactDOM; }}; }}, loaded: 1, from: 'host' }}
    }};
    if ({inst.container_name}.init) {{
      try {{ {inst.container_name}.init(shareScope['default']); }} catch(e) {{}}
    }}
    return {inst.container_name}.get('./{inst.component_name}');
  }}).then(function(factory) {{
    var Comp = factory().default;
    ReactDOM.createRoot(document.getElementById('root'))
      .render(React.createElement(Comp, {{}}));
  }}).catch(function(e) {{
    document.body.innerHTML = '<p style="color:red;padding:16px">加载失败: ' + e.message + '</p>';
  }});
}})();
</script>
</body></html>"""

        resource = create_ui_resource({
            "uri": uri,
            "content": {"type": "rawHtml", "htmlString": html},
            "encoding": "text",
        })
        r = resource.model_dump(mode="json")
        sse_logger.emit_response(
            outer_span, "SG-Agent", "CF-Agent", "mcp-resources/read",
            result={"uri": uri},
        )
        return JSONResponse({
            "contents": [{
                "uri": r["resource"]["uri"],
                "mimeType": "text/html;profile=mcp-app",
                "text": r["resource"]["text"],
            }]
        })

    sse_logger.emit_response(outer_span, "SG-Agent", "resource-proxy", "mcp-resources/read", detail="error: unknown uri")
    raise HTTPException(status_code=404, detail="Unknown resource URI")


import concurrent.futures

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            future = _executor.submit(asyncio.run, coro)
            return future.result(timeout=30)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)




async def _fetch_employee_trend() -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"http://localhost:{PORT}/api/employee/trend")
        return resp.json()


async def _fetch_component_info():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{RESOURCE_CENTER_URL}/api/components/EmployeeChart")
        return resp.json()


MCP_SERVER_SSE_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:3005") + "/sse"

async def _call_mcp_tool(tool_name: str) -> dict:
    async with sse_client(MCP_SERVER_SSE_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, {})
            if result.content and hasattr(result.content[0], "text"):
                return json.loads(result.content[0].text)
            return {}

async def _read_mcp_resource(uri: str) -> list:
    async with sse_client(MCP_SERVER_SSE_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.read_resource(uri)
            return [
                {
                    "uri": str(c.uri),
                    "mimeType": "text/html;profile=mcp-app",
                    "text": c.text,
                }
                for c in result.contents
            ]


class StargateA2AServer(A2AServer):
    def handle_message(self, message: Message) -> Message:
        user_text = ""
        mode = "endpoint"
        if hasattr(message.content, "text"):
            raw = message.content.text
            try:
                parsed = json.loads(raw)
                user_text = parsed.get("text", raw)
                mode = parsed.get("mode", "endpoint")
            except (json.JSONDecodeError, AttributeError):
                user_text = raw

        sse_logger.emit("SG-Agent", "SG-LLM", "llm-call", f"tool selection (mode={mode})")
        tool_name, tool_args = _run_async(llm.select_tool(user_text))

        if tool_name == "query_employee_trend":
            if mode == "mcp":
                mcp_span = sse_logger.emit_request(
                    "SG-Agent", "MCP-Server", "mcp-tool-call",
                    params={"tool": "query_employee_trend"},
                )
                mcp_result = _run_async(_call_mcp_tool("query_employee_trend"))
                resource_uri = mcp_result.get("_meta", {}).get("ui", {}).get("resourceUri", "ui://stargate/employee-trend")
                sse_logger.emit_response(
                    mcp_span, "MCP-Server", "SG-Agent", "mcp-tool-result",
                    result={"resourceUri": resource_uri},
                )
                biz_span = sse_logger.emit_request("SG-Agent", "BusinessAPI", "http", params={"path": "GET /api/employee/trend"})
                trend_resp = _run_async(_fetch_employee_trend())
                sse_logger.emit_response(biz_span, "BusinessAPI", "SG-Agent", "http", result={"count": len(trend_resp.get("data", []))})
                tool_result = {
                    "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
                    "data": trend_resp["data"],
                    "token": trend_resp["token"],
                }
            else:
                rc_span = sse_logger.emit_request("SG-Agent", "ResourceCenter", "http", params={"path": "GET /api/components/EmployeeChart"})
                component_info = _run_async(_fetch_component_info())
                sse_logger.emit_response(rc_span, "ResourceCenter", "SG-Agent", "http", result={"componentName": component_info.get("componentName", "")})
                biz_span = sse_logger.emit_request("SG-Agent", "BusinessAPI", "http", params={"path": "GET /api/employee/trend"})
                trend_resp = _run_async(_fetch_employee_trend())
                sse_logger.emit_response(biz_span, "BusinessAPI", "SG-Agent", "http", result={"count": len(trend_resp.get("data", []))})
                card_id = card_cache.put(
                    component_name=component_info["componentName"],
                    container_name=component_info.get("containerName", component_info["componentName"]),
                    remote_entry_url=component_info["remoteEntryUrl"],
                    props={"data": trend_resp["data"]},
                )
                resource_uri = f"ui://stargate/card/{card_id}"
                tool_result = {
                    "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
                    "data": trend_resp["data"],
                    "token": trend_resp["token"],
                }

            response_data = {
                "text": "已为您查询快手历年员工趋势数据，共 5 年记录。",
                "mcp_ui_resource": {
                    "kind": "mcp_ui_resource",
                    "resourceUri": resource_uri,
                    "toolName": "query_employee_trend",
                    "toolResult": tool_result,
                    "uiMetadata": {
                        "preferred-frame-size": {"width": 560, "height": 420}
                    },
                },
            }
            return Message(
                content=TextContent(text=json.dumps(response_data, ensure_ascii=False)),
                role=MessageRole.AGENT,
            )
        elif tool_name == "query_employee_trend_lazy":
            if mode == "mcp":
                mcp_span = sse_logger.emit_request(
                    "SG-Agent", "MCP-Server", "mcp-tool-call",
                    params={"tool": "query_employee_trend_lazy"},
                )
                mcp_result = _run_async(_call_mcp_tool("query_employee_trend_lazy"))
                resource_uri = mcp_result.get("_meta", {}).get("ui", {}).get("resourceUri", "ui://stargate/employee-trend-lazy")
                sse_logger.emit_response(
                    mcp_span, "MCP-Server", "SG-Agent", "mcp-tool-result",
                    result={"resourceUri": resource_uri},
                )
                biz_span = sse_logger.emit_request("SG-Agent", "BusinessAPI", "http", params={"path": "GET /api/employee/trend (token only)"})
                trend_resp = _run_async(_fetch_employee_trend())
                sse_logger.emit_response(biz_span, "BusinessAPI", "SG-Agent", "http", result={"token": "ok"})
                tool_result = {
                    "content": [{"type": "text", "text": "正在为您准备员工趋势数据，请稍候..."}],
                    "token": trend_resp["token"],
                }
            else:
                rc_span = sse_logger.emit_request("SG-Agent", "ResourceCenter", "http", params={"path": "GET /api/components/EmployeeChart"})
                component_info = _run_async(_fetch_component_info())
                sse_logger.emit_response(rc_span, "ResourceCenter", "SG-Agent", "http", result={"componentName": component_info.get("componentName", "")})
                card_id = card_cache.put(
                    component_name="EmployeeChartLazy",
                    container_name=component_info.get("containerName", component_info["componentName"]),
                    remote_entry_url=component_info["remoteEntryUrl"],
                    props={},
                )
                resource_uri = f"ui://stargate/card/{card_id}"
                sse_logger.emit("SG-Agent", "CF-Agent", "card-ready", resource_uri)
                biz_span = sse_logger.emit_request("SG-Agent", "BusinessAPI", "http", params={"path": "GET /api/employee/trend (token only)"})
                trend_resp = _run_async(_fetch_employee_trend())
                sse_logger.emit_response(biz_span, "BusinessAPI", "SG-Agent", "http", result={"token": "ok"})
                tool_result = {
                    "content": [{"type": "text", "text": "正在为您准备员工趋势数据，请稍候..."}],
                    "token": trend_resp["token"],
                }
            response_data = {
                "text": "正在为您准备员工趋势数据，请稍候...",
                "mcp_ui_resource": {
                    "kind": "mcp_ui_resource",
                    "resourceUri": resource_uri,
                    "toolName": "query_employee_trend_lazy",
                    "toolResult": tool_result,
                    "uiMetadata": {
                        "preferred-frame-size": {"width": 560, "height": 420}
                    },
                },
            }
            return Message(
                content=TextContent(text=json.dumps(response_data, ensure_ascii=False)),
                role=MessageRole.AGENT,
            )
        else:
            return Message(
                content=TextContent(text=json.dumps({"text": "抱歉，我目前只支持查询员工趋势数据。"}, ensure_ascii=False)),
                role=MessageRole.AGENT,
            )


def _start_a2a_flask():
    from flask import Flask
    flask_app = Flask(__name__)
    agent_card = AgentCard(
        name="stargate-agent",
        description="Stargate A2A Agent with MCP-UI support",
        url=f"http://localhost:{A2A_PORT}",
        version="0.1.0",
    )
    a2a_server = StargateA2AServer(agent_card=agent_card)
    a2a_server.setup_routes(flask_app)
    flask_app.run(host="0.0.0.0", port=A2A_PORT, debug=False, use_reloader=False)


def main():
    import uvicorn
    import threading

    t = threading.Thread(target=_start_a2a_flask, daemon=True)
    t.start()

    uvicorn.run(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
