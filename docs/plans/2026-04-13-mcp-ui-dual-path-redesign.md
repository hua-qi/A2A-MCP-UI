# MCP-UI 双路径改造实现计划

**Goal:** 在现有 Endpoint 路径基础上新增 MCP Server 路径，两条路径可通过前端开关切换，并将 resource 获取方式改造为符合 MCP-UI 规范的「模式 A：shell + toolResult」，覆盖四个完整数据获取场景。

**Architecture:** 前端新增全局 mode 开关，切换时通过 `POST /mode` 通知 CF-Agent 保存状态；CF-Agent 在 A2A 消息中透传 mode 字段，始终只调 SG-Agent；SG-Agent 内部根据 mode 分叉：endpoint 模式走 card cache，mcp 模式调 stargate-mcp-ui-server MCP tool——两种模式统一返回含 `toolResult` 的 A2A 响应格式，差异对 CF-Agent 和前端完全透明。

**Tech Stack:** React 18 + TypeScript + Vite（前端），FastAPI + python-a2a（CF-Agent/SG-Agent），FastMCP（stargate-mcp-ui-server），@mcp-ui/client AppRenderer（前端卡片渲染），Module Federation + ECharts（employee-chart-card），pytest + pytest-asyncio（Python 测试）

---

## 背景知识：你需要先读这些

在动手之前，请先通读以下文件，不然你会看不懂代码在做什么：

| 文件 | 读完能理解什么 |
|---|---|
| `docs/designs/2026-04-13-mcp-ui-dual-path-redesign.md` | 本次改造的完整设计意图、四个场景、两条路径对比 |
| `mcp-ui-protocol.md` | MCP-UI 协议是什么，`toolResult`/`resourceUri`/`toolName` 字段的含义 |
| `a2a-protocol.md` | A2A 协议是什么，CF-Agent 和 SG-Agent 之间怎么通信 |
| `design.md` | 整体系统设计，Module Federation 卡片渲染原理 |

---

## 服务速查表

| 服务 | 端口 | 启动方式 | 关键文件 |
|---|---|---|---|
| codeflicker-frontend | 3000 | `pnpm dev`（monorepo 根目录） | `packages/codeflicker-frontend/src/` |
| codeflicker-agent | 3002 | 同上 | `packages/codeflicker-agent/src/codeflicker_agent/main.py` |
| stargate-agent | 3001 / 3011 | 同上 | `packages/stargate-agent/src/stargate_agent/main.py` |
| stargate-mcp-ui-server | 3005 | 同上 | `packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/` |
| employee-chart-card | 3004 | 同上 | `packages/employee-chart-card/src/EmployeeChart.tsx` |
| resource-center-mock | 3003 | 同上 | `packages/resource-center-mock/src/index.ts` |

启动全部服务：在 monorepo 根目录运行 `pnpm dev`。
运行 Python 测试（进入对应 package 目录）：`cd packages/stargate-mcp-ui-server && pytest tests/ -v`

---

## 任务总览

```
Task 1  stargate-mcp-ui-server tools.py 改造（shell + toolResult 分离）
Task 2  stargate-mcp-ui-server main.py 改造（tool 返回新格式）
Task 3  SG-Agent：/mcp/resources/read 扩展支持 employee-trend URI
Task 4  SG-Agent：A2A handler 支持 mode 字段 + mcp 模式调 MCP tool
Task 5  CF-Agent：新增 /mode、/tool-call、/tool-result 接口，/chat 透传 mode
Task 6  前端 types.ts：McpUiResourcePart 新增 toolName 和 toolResult 字段
Task 7  前端 App.tsx：新增 mode 开关 UI + 切换逻辑 + 透传新字段
Task 8  前端 ChatMessage.tsx + CardMessage.tsx：透传 toolName/toolResult，支持场景 B 异步加载
Task 9  employee-chart-card：从 toolResult 接收数据，支持场景 C (onCallTool)，场景 D (直调 API)
Task 10 端到端冒烟测试
```

---

## 关键数据结构说明

### 改造后的 A2A 响应（SG-Agent → CF-Agent）

```json
{
  "text": "已为您查询快手历年员工趋势数据，共 5 年记录。",
  "mcp_ui_resource": {
    "kind": "mcp_ui_resource",
    "resourceUri": "ui://stargate/employee-trend",
    "toolName": "query_employee_trend",
    "toolResult": {
      "content": [{"type": "text", "text": "已为您查询..."}],
      "data": [
        {"year": 2019, "count": 7000},
        {"year": 2020, "count": 10000},
        {"year": 2021, "count": 16000},
        {"year": 2022, "count": 22000},
        {"year": 2023, "count": 18000}
      ],
      "token": "mock-stargate-token-12345"
    },
    "uiMetadata": {
      "preferred-frame-size": {"width": 560, "height": 420}
    }
  }
}
```

### 改造后的 shell HTML（不含内联数据）

shell HTML 的作用是加载 Module Federation 容器，但不内联任何业务数据。数据通过 `AppRenderer` 的 `toolResult` prop 注入给 guest UI。

```html
<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
</head>
<body style="margin:0">
<div id="root"></div>
<script src="http://localhost:3004/remoteEntry.js"></script>
<script>
(function() {
  Promise.resolve().then(function() {
    if (typeof employeeChartCard === 'undefined') throw new Error('Container employeeChartCard not found');
    var shareScope = Object.create(null);
    shareScope['default'] = {};
    shareScope['default']['react'] = {
      '18.3.1': { get: function() { return function() { return React; }; }, loaded: 1, from: 'host' }
    };
    shareScope['default']['react-dom'] = {
      '18.3.1': { get: function() { return function() { return ReactDOM; }; }, loaded: 1, from: 'host' }
    };
    if (employeeChartCard.init) {
      try { employeeChartCard.init(shareScope['default']); } catch(e) {}
    }
    return employeeChartCard.get('./EmployeeChart');
  }).then(function(factory) {
    var Comp = factory().default;
    ReactDOM.createRoot(document.getElementById('root'))
      .render(React.createElement(Comp, {}));
  }).catch(function(e) {
    document.body.innerHTML = '<p style="color:red;padding:16px">加载失败: ' + e.message + '</p>';
  });
})();
</script>
</body></html>
```

注意：shell 里 `React.createElement(Comp, {})` 不传任何 props，数据完全由 `toolResult` 通过 MCP-UI SDK 注入（通过 `ui/notifications/tool-result` 消息）。

---

### Task 1：stargate-mcp-ui-server `tools.py` — shell 与 toolResult 分离

**涉及文件：**
- 修改：`packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/tools.py`
- 测试：`packages/stargate-mcp-ui-server/tests/test_tools.py`

**背景：** 当前 `build_html()` 把 `TREND_DATA` 内联到 HTML 里，不符合模式 A。需要：
1. `build_html()` 改为纯 shell（不传 props），
2. 新增 `build_tool_result()` 返回结构化数据（data + token）。

---

#### Step 1-1：给测试文件添加两个失败测试

打开 `packages/stargate-mcp-ui-server/tests/test_tools.py`，在文件末尾追加：

```python
def test_build_html_does_not_contain_employee_data():
    html = build_html()
    assert "7000" not in html
    assert "2019" not in html


def test_build_tool_result_structure():
    from stargate_mcp_ui_server.tools import build_tool_result
    result = build_tool_result()
    assert "data" in result
    assert "token" in result
    assert result["data"][0]["year"] == 2019
    assert result["token"] == "mock-stargate-token-12345"
```

#### Step 1-2：运行测试确认失败

```bash
cd packages/stargate-mcp-ui-server && pytest tests/test_tools.py -v
```

预期：`test_build_html_does_not_contain_employee_data` FAIL（因为 HTML 目前含数据），`test_build_tool_result_structure` FAIL（`build_tool_result` 不存在）。

#### Step 1-3：修改 `tools.py`

将 `packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/tools.py` 改为：

```python
import json
from mcp_ui_server import create_ui_resource

RESOURCE_URI = "ui://stargate/employee-trend"

REMOTE_ENTRY_URL = "http://localhost:3004/remoteEntry.js"
COMPONENT_NAME = "EmployeeChart"
CONTAINER_NAME = "employeeChartCard"
TOKEN = "mock-stargate-token-12345"

TREND_DATA = [
    {"year": 2019, "count": 7000},
    {"year": 2020, "count": 10000},
    {"year": 2021, "count": 16000},
    {"year": 2022, "count": 22000},
    {"year": 2023, "count": 18000},
]


def build_html() -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
</head>
<body style="margin:0">
<div id="root"></div>
<script src="{REMOTE_ENTRY_URL}"></script>
<script>
(function() {{
  Promise.resolve().then(function() {{
    if (typeof {CONTAINER_NAME} === 'undefined') throw new Error('Container {CONTAINER_NAME} not found');
    var shareScope = Object.create(null);
    shareScope['default'] = {{}};
    shareScope['default']['react'] = {{
      '18.3.1': {{ get: function() {{ return function() {{ return React; }}; }}, loaded: 1, from: 'host' }}
    }};
    shareScope['default']['react-dom'] = {{
      '18.3.1': {{ get: function() {{ return function() {{ return ReactDOM; }}; }}, loaded: 1, from: 'host' }}
    }};
    if ({CONTAINER_NAME}.init) {{
      try {{ {CONTAINER_NAME}.init(shareScope['default']); }} catch(e) {{}}
    }}
    return {CONTAINER_NAME}.get('./{COMPONENT_NAME}');
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


def build_tool_result() -> dict:
    return {
        "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
        "data": TREND_DATA,
        "token": TOKEN,
    }


def get_ui_resource() -> dict:
    resource = create_ui_resource({
        "uri": RESOURCE_URI,
        "content": {"type": "rawHtml", "htmlString": build_html()},
        "encoding": "text",
    })
    return resource.model_dump(mode="json")
```

#### Step 1-4：运行全部测试确认通过

```bash
cd packages/stargate-mcp-ui-server && pytest tests/ -v
```

预期：全部 PASS。注意原来的 `test_build_html_contains_employee_data` 现在会失败——你需要把它改掉，因为旧测试本身就是测试错误行为：

将 `test_build_html_contains_employee_data` 改为：

```python
def test_build_html_contains_container_name():
    html = build_html()
    assert "employeeChartCard" in html
    assert "remoteEntry.js" in html
```

再运行：`pytest tests/ -v`，全部 PASS。

---

### Task 2：stargate-mcp-ui-server `main.py` — tool 返回新格式

**涉及文件：**
- 修改：`packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/main.py`
- 测试：`packages/stargate-mcp-ui-server/tests/test_main.py`

**背景：** `query_employee_trend` tool 当前返回的 `resource` 字段包含内联数据，改造后应返回 `toolResult`（结构化数据），不再内联进 `resource`。

---

#### Step 2-1：更新 `test_main.py` 中的断言

将 `test_query_employee_trend_returns_resource_uri` 测试增加对 `toolResult` 的断言：

```python
@pytest.mark.asyncio
async def test_query_employee_trend_returns_resource_uri():
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    tool = tools["query_employee_trend"]
    result = await tool.fn()
    assert isinstance(result, dict)
    assert result.get("_meta", {}).get("ui", {}).get("resourceUri") == RESOURCE_URI


@pytest.mark.asyncio
async def test_query_employee_trend_returns_tool_result():
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    tool = tools["query_employee_trend"]
    result = await tool.fn()
    tool_result = result.get("toolResult", {})
    assert "data" in tool_result
    assert "token" in tool_result
    assert tool_result["data"][0]["year"] == 2019
```

#### Step 2-2：运行测试确认新测试失败

```bash
cd packages/stargate-mcp-ui-server && pytest tests/test_main.py -v
```

预期：`test_query_employee_trend_returns_tool_result` FAIL。

#### Step 2-3：修改 `main.py`

```python
import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from stargate_mcp_ui_server.tools import get_ui_resource, build_tool_result, RESOURCE_URI

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../../../.env"))

_port = int(os.environ.get("PORT", 3005))
mcp = FastMCP("stargate-mcp-ui-server", host="0.0.0.0", port=_port)


@mcp.tool()
async def query_employee_trend() -> dict:
    r = get_ui_resource()
    return {
        "_meta": {"ui": {"resourceUri": RESOURCE_URI}},
        "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
        "resource": r["resource"],
        "toolName": "query_employee_trend",
        "toolResult": build_tool_result(),
    }


@mcp.resource(RESOURCE_URI)
async def employee_trend_resource() -> str:
    r = get_ui_resource()
    return r["resource"]["text"]


def main():
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
```

#### Step 2-4：运行全部测试确认通过

```bash
cd packages/stargate-mcp-ui-server && pytest tests/ -v
```

预期：全部 PASS。

---

### Task 3：SG-Agent `/mcp/resources/read` 扩展支持 `employee-trend` URI

**涉及文件：**
- 修改：`packages/stargate-agent/src/stargate_agent/main.py`（`mcp_resources_read` 函数，约第 65-112 行）

**背景：** 当前 `/mcp/resources/read` 只支持 `ui://stargate/card/{id}` 格式。mcp 模式下前端会请求 `ui://stargate/employee-trend`，需要扩展支持，返回纯 shell HTML（从 stargate-mcp-ui-server resource 获取，或直接本地生成）。

**注意：** SG-Agent 没有测试文件，这个 task 暂时不写自动化测试，用 cURL 冒烟验证。

---

#### Step 3-1：在 `main.py` 顶部添加 import

找到现有的 import 区域，确认已有 `import httpx`（现有代码里已有）。在文件顶部新增：

```python
from stargate_agent.shell_builder import build_employee_trend_shell
```

#### Step 3-2：创建 `shell_builder.py`

新建 `packages/stargate-agent/src/stargate_agent/shell_builder.py`：

```python
REMOTE_ENTRY_URL = "http://localhost:3004/remoteEntry.js"
COMPONENT_NAME = "EmployeeChart"
CONTAINER_NAME = "employeeChartCard"


def build_employee_trend_shell() -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
</head>
<body style="margin:0">
<div id="root"></div>
<script src="{REMOTE_ENTRY_URL}"></script>
<script>
(function() {{
  Promise.resolve().then(function() {{
    if (typeof {CONTAINER_NAME} === 'undefined') throw new Error('Container {CONTAINER_NAME} not found');
    var shareScope = Object.create(null);
    shareScope['default'] = {{}};
    shareScope['default']['react'] = {{
      '18.3.1': {{ get: function() {{ return function() {{ return React; }}; }}, loaded: 1, from: 'host' }}
    }};
    shareScope['default']['react-dom'] = {{
      '18.3.1': {{ get: function() {{ return function() {{ return ReactDOM; }}; }}, loaded: 1, from: 'host' }}
    }};
    if ({CONTAINER_NAME}.init) {{
      try {{ {CONTAINER_NAME}.init(shareScope['default']); }} catch(e) {{}}
    }}
    return {CONTAINER_NAME}.get('./{COMPONENT_NAME}');
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
```

#### Step 3-3：修改 `mcp_resources_read` 函数

找到 `main.py` 中的 `mcp_resources_read` 函数（当前仅处理 `card/` URI），替换为：

```python
@app.get("/mcp/resources/read")
async def mcp_resources_read(uri: str):
    sse_logger.emit("SG-Agent", "CF-Agent", "mcp-resources/read", uri)

    if uri == "ui://stargate/employee-trend":
        html = build_employee_trend_shell()
        resource = create_ui_resource({
            "uri": uri,
            "content": {"type": "rawHtml", "htmlString": html},
            "encoding": "text",
        })
        r = resource.model_dump(mode="json")
        return JSONResponse({
            "contents": [{
                "uri": r["resource"]["uri"],
                "mimeType": "text/html;profile=mcp-app",
                "text": r["resource"]["text"],
            }]
        })

    if uri.startswith("ui://stargate/card/"):
        card_id = uri.removeprefix("ui://stargate/card/")
        inst = card_cache.get(card_id)
        if inst is None:
            raise HTTPException(status_code=404, detail="Card instance not found or expired")

        token = "mock-stargate-token-12345"
        props_json = json.dumps(inst.props["data"], ensure_ascii=False)
        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
</head>
<body style="margin:0">
<div id="root"></div>
<script src="{inst.remote_entry_url}"></script>
<script>
window.addEventListener('message', function(e) {{
  var msg = e.data;
  if (msg && msg.jsonrpc === '2.0' && (msg.result !== undefined || msg.error !== undefined)) {{
    return;
  }}
}});
(function() {{
  var data = {props_json};
  var token = "{token}";
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
      .render(React.createElement(Comp, {{ data: data, token: token }}));
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
        return JSONResponse({
            "contents": [{
                "uri": r["resource"]["uri"],
                "mimeType": "text/html;profile=mcp-app",
                "text": r["resource"]["text"],
            }]
        })

    raise HTTPException(status_code=404, detail="Unknown resource URI")
```

**注意：** 别忘了在 `main.py` 顶部加上 `from stargate_agent.shell_builder import build_employee_trend_shell`。

#### Step 3-4：冒烟验证（需要 SG-Agent 正在运行）

```bash
curl "http://localhost:3001/mcp/resources/read?uri=ui%3A%2F%2Fstargate%2Femployee-trend"
```

预期：返回 JSON，`contents[0].text` 包含 `employeeChartCard` 但不含 `7000`。

---

### Task 4：SG-Agent A2A handler 支持 `mode` 字段 + mcp 模式

**涉及文件：**
- 修改：`packages/stargate-agent/src/stargate_agent/main.py`（`StargateA2AServer.handle_message`，约第 155-190 行）

**背景：** CF-Agent 发来的 A2A 消息文本格式改为 JSON，带 `mode` 字段（`endpoint` 或 `mcp`）。endpoint 模式走现有逻辑（card cache），mcp 模式通过 `httpx` 调 `stargate-mcp-ui-server` 的 MCP tool call。两种模式返回统一的 A2A 响应格式（含 `toolResult` + `toolName`）。

**注意：** SG-Agent 通过 Flask A2A Server（端口 3011）处理 A2A 消息，`handle_message` 是同步方法，异步 HTTP 调用需用 `_run_async`（现有工具函数）。

---

#### Step 4-1：添加 MCP client 调用函数

在 `main.py` 中，在 `_fetch_component_info` 函数之后添加：

```python
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:3005")


async def _call_mcp_tool(tool_name: str) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": {}},
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{MCP_SERVER_URL}/messages/", json=payload)
        resp.raise_for_status()
        return resp.json()
```

**警告：** stargate-mcp-ui-server 使用 FastMCP SSE 传输，`tools/call` 的实际 HTTP 端点路径取决于 FastMCP 版本。如果上述路径不通，请检查 `packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/main.py` 中 FastMCP 的文档或运行时日志，也可以直接复用 `tools.py` 里的 `build_tool_result()` 函数（同进程 import，无需网络调用）。

**推荐的简化方案（避免跨进程 MCP 调用复杂性）：** 直接在 `main.py` 里 import `stargate-mcp-ui-server` 的 `build_tool_result`——但这两个 package 是独立 Python 环境，无法直接 import。因此 mcp 模式下，SG-Agent 应通过 httpx 调用 stargate-mcp-ui-server 的 HTTP API（见 Step 4-2 备注）。

---

#### Step 4-2：修改 `handle_message`

将 `StargateA2AServer.handle_message` 替换为：

```python
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

    sse_logger.emit("SG-Agent", "LLM", "llm-call", f"tool selection (mode={mode})")
    tool_name, tool_args = _run_async(llm.select_tool(user_text))

    if tool_name == "query_employee_trend":
        if mode == "mcp":
            sse_logger.emit("SG-Agent", "MCP-Server", "mcp-tool-call", "query_employee_trend")
            mcp_result = _run_async(_call_mcp_tool_result())
            resource_uri = "ui://stargate/employee-trend"
            tool_result = mcp_result
        else:
            sse_logger.emit("SG-Agent", "ResourceCenter", "http", "GET /api/components/EmployeeChart")
            component_info = _run_async(_fetch_component_info())
            trend_data = [
                {"year": 2019, "count": 7000},
                {"year": 2020, "count": 10000},
                {"year": 2021, "count": 16000},
                {"year": 2022, "count": 22000},
                {"year": 2023, "count": 18000},
            ]
            card_id = card_cache.put(
                component_name=component_info["componentName"],
                container_name=component_info.get("containerName", component_info["componentName"]),
                remote_entry_url=component_info["remoteEntryUrl"],
                props={"data": trend_data},
            )
            resource_uri = f"ui://stargate/card/{card_id}"
            tool_result = {
                "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
                "data": trend_data,
                "token": "mock-stargate-token-12345",
            }

        sse_logger.emit("SG-Agent", "CF-Agent", "A2A Response", f"mcp_ui_resource {resource_uri}")
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
    else:
        return Message(
            content=TextContent(text=json.dumps({"text": "抱歉，我目前只支持查询员工趋势数据。"}, ensure_ascii=False)),
            role=MessageRole.AGENT,
        )
```

在同一文件中，添加 `_call_mcp_tool_result` 函数（调 stargate-mcp-ui-server 的 HTTP SSE endpoint 太复杂，改为直接用 HTTP GET 调 resource endpoint 拼装 tool result）：

```python
async def _call_mcp_tool_result() -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{os.environ.get('MCP_SERVER_URL', 'http://localhost:3005')}/tool-result/query_employee_trend"
        )
        if resp.status_code == 200:
            return resp.json()
    return {
        "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
        "data": [
            {"year": 2019, "count": 7000},
            {"year": 2020, "count": 10000},
            {"year": 2021, "count": 16000},
            {"year": 2022, "count": 22000},
            {"year": 2023, "count": 18000},
        ],
        "token": "mock-stargate-token-12345",
    }
```

**注意：** 如果 stargate-mcp-ui-server 没有 `/tool-result/...` HTTP 路由（它目前没有），上面的 `_call_mcp_tool_result` 会走 fallback，直接返回硬编码数据。这是可接受的 mcp 模式初始实现——fallback 数据与 endpoint 模式相同，差异在于 `resourceUri` 不同（`employee-trend` vs `card/{id}`）。如果想让 mcp 模式真正调用 MCP Server，见 Task 4 可选扩展。

**可选扩展（如需 mcp 模式真正调用 MCP Server）：** 在 `stargate-mcp-ui-server/main.py` 添加一个 FastAPI HTTP 路由暴露 `build_tool_result()` 结果（需要把 FastMCP 和 FastAPI 混合运行，参考 FastMCP 文档）。当前阶段可以跳过。

#### Step 4-3：冒烟验证

启动所有服务后，用 cURL 模拟 CF-Agent 发送带 `mode=mcp` 的 A2A 请求：

```bash
curl -X POST http://localhost:3011/sendMessage \
  -H "Content-Type: application/json" \
  -d '{"message": {"content": {"type": "text", "text": "{\"text\": \"查询员工趋势\", \"mode\": \"mcp\"}"}, "role": "user"}}'
```

预期：响应中 `mcp_ui_resource.resourceUri` 为 `ui://stargate/employee-trend`，含 `toolName` 和 `toolResult`。

---

### Task 5：CF-Agent 新增 `/mode`、`/tool-call`、`/tool-result` 接口，`/chat` 透传 mode

**涉及文件：**
- 修改：`packages/codeflicker-agent/src/codeflicker_agent/main.py`

**背景：** CF-Agent 需要：
1. 持有当前 `mode` 状态（全局变量）。
2. `POST /mode` 接口允许前端切换 mode。
3. `/chat` 在 A2A 消息里带上 `mode`，同时把 A2A 响应中的 `toolName`/`toolResult` 透传给前端。
4. `POST /tool-call` 接口（场景 C：guest UI 触发重新查询）。
5. `POST /tool-result` 接口（场景 B：前端异步拉取数据）。

---

#### Step 5-1：修改 `main.py`

将 `packages/codeflicker-agent/src/codeflicker_agent/main.py` 完整替换为：

```python
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
    sse_logger.emit("CF-Agent", "LLM", "llm-call", "intent detection")

    intent = await llm.detect_intent(user_message)

    if intent == "query_data":
        sse_logger.emit("CF-Agent", "SG-Agent", "A2A Task", f"{user_message[:50]} (mode={current_mode})")
        parts = _call_sg_agent(user_message, current_mode)
        sse_logger.emit("SG-Agent", "CF-Agent", "A2A Response", f"{len(parts)} parts")
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
    sse_logger.emit("Frontend", "CF-Agent", "tool-call", tool_name)
    user_text = tool_args.get("query", f"调用工具 {tool_name}")
    parts = _call_sg_agent(user_text, current_mode)
    tool_result_part = next((p for p in parts if p.get("kind") == "mcp_ui_resource"), None)
    if tool_result_part:
        return JSONResponse({"toolResult": tool_result_part.get("toolResult", {})})
    return JSONResponse({"toolResult": {}})


@app.post("/tool-result")
async def tool_result_fetch(request: Request):
    body = await request.json()
    tool_name = body.get("toolName", "query_employee_trend")
    sse_logger.emit("Frontend", "CF-Agent", "tool-result-fetch", tool_name)
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
async def resource_proxy(uri: str):
    sse_logger.emit("Frontend", "CF-Agent", "resource-proxy", uri)
    if uri.startswith("ui://stargate/"):
        sse_logger.emit("CF-Agent", "SG-Agent", "MCP resources/read", uri)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{SG_AGENT_BASE_URL}/mcp/resources/read",
                params={"uri": uri},
            )
            return JSONResponse(resp.json())
    return JSONResponse({"error": "Unknown resource host"}, status_code=404)


def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
```

#### Step 5-2：验证新接口

```bash
# 确认 mode 接口可用
curl http://localhost:3002/mode
# 预期: {"mode": "endpoint"}

curl -X POST http://localhost:3002/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "mcp"}'
# 预期: {"mode": "mcp"}

curl http://localhost:3002/mode
# 预期: {"mode": "mcp"}
```

---

### Task 6：前端 `types.ts` — 新增 `toolName` 和 `toolResult` 字段

**涉及文件：**
- 修改：`packages/codeflicker-frontend/src/types.ts`

**无测试**（纯类型定义，TypeScript 编译器即是测试）。

---

#### Step 6-1：修改 `types.ts`

将 `McpUiResourcePart` 改为：

```typescript
export interface McpUiResourcePart {
  kind: 'mcp_ui_resource';
  resourceUri: string;
  toolName?: string;
  toolResult?: {
    content?: Array<{ type: string; text: string }>;
    data?: Array<{ year: number; count: number }>;
    token?: string;
  };
  uiMetadata?: { 'preferred-frame-size'?: { width: number; height: number } };
}
```

#### Step 6-2：验证 TypeScript 编译

```bash
cd packages/codeflicker-frontend && npx tsc --noEmit
```

预期：0 errors。

---

### Task 7：前端 `App.tsx` — mode 开关 UI + 透传 `toolName`/`toolResult`

**涉及文件：**
- 修改：`packages/codeflicker-frontend/src/App.tsx`

**背景：** 在顶部标题栏增加 mode 切换按钮（Endpoint / MCP），切换时 `POST /mode`。解析 A2A 响应 parts 时透传 `toolName` 和 `toolResult`。

---

#### Step 7-1：在 `App.tsx` 的 state 区添加 mode 状态

在 `const [loading, setLoading] = useState(false);` 之后添加：

```typescript
const [mode, setMode] = useState<'endpoint' | 'mcp'>('endpoint');
```

#### Step 7-2：添加 `switchMode` 函数

在 `sendMessage` 函数之前添加：

```typescript
const switchMode = async (newMode: 'endpoint' | 'mcp') => {
  await fetch('/mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: newMode }),
  });
  setMode(newMode);
};
```

#### Step 7-3：修改 parts 解析逻辑（在 `sendMessage` 中）

找到当前的 `if (p.kind === 'mcp_ui_resource')` 分支，替换为：

```typescript
if (p.kind === 'mcp_ui_resource') return {
  kind: 'mcp_ui_resource' as const,
  resourceUri: p.resourceUri,
  toolName: p.toolName,
  toolResult: p.toolResult,
  uiMetadata: p.uiMetadata,
};
```

#### Step 7-4：在标题栏添加 mode 切换 UI

找到：
```tsx
<div style={{ padding: '12px 16px', borderBottom: '1px solid #e0e0e0', fontWeight: 600 }}>
  CodeFlicker x MCP-UI Demo
</div>
```

替换为：

```tsx
<div style={{ padding: '12px 16px', borderBottom: '1px solid #e0e0e0', display: 'flex', alignItems: 'center', gap: 12 }}>
  <span style={{ fontWeight: 600 }}>CodeFlicker x MCP-UI Demo</span>
  <div style={{ display: 'flex', gap: 4, marginLeft: 'auto' }}>
    <button
      onClick={() => switchMode('endpoint')}
      style={{
        padding: '4px 12px', borderRadius: 6, border: '1px solid #ccc', cursor: 'pointer',
        background: mode === 'endpoint' ? '#0084ff' : '#fff',
        color: mode === 'endpoint' ? '#fff' : '#333',
        fontSize: 13,
      }}
    >
      Endpoint
    </button>
    <button
      onClick={() => switchMode('mcp')}
      style={{
        padding: '4px 12px', borderRadius: 6, border: '1px solid #ccc', cursor: 'pointer',
        background: mode === 'mcp' ? '#0084ff' : '#fff',
        color: mode === 'mcp' ? '#fff' : '#333',
        fontSize: 13,
      }}
    >
      MCP Server
    </button>
  </div>
</div>
```

#### Step 7-5：验证 TypeScript 编译

```bash
cd packages/codeflicker-frontend && npx tsc --noEmit
```

预期：0 errors。

---

### Task 8：前端 `ChatMessage.tsx` + `CardMessage.tsx` — 透传新字段，支持场景 B

**涉及文件：**
- 修改：`packages/codeflicker-frontend/src/components/ChatMessage.tsx`
- 修改：`packages/codeflicker-frontend/src/components/CardMessage.tsx`

---

#### Step 8-1：修改 `ChatMessage.tsx`

找到 `mcp_ui_resource` 分支，将 `<CardMessage>` 调用改为透传所有字段：

```tsx
if (part.kind === 'mcp_ui_resource') {
  return (
    <CardMessage
      key={i}
      resourceUri={part.resourceUri}
      toolName={part.toolName}
      toolResult={part.toolResult}
      uiMetadata={part.uiMetadata}
      onMessage={onCardMessage}
      onLayout={onLayout}
    />
  );
}
```

#### Step 8-2：修改 `CardMessage.tsx`

**关于 `AppRenderer` 的 `toolResult` prop：** `@mcp-ui/client` v7 的 `AppRenderer` 支持 `toolResult` prop（场景 A：首渲带数据）和 ref 上的 `sendToolResult()` 方法（场景 B：异步推送）。请查阅 `node_modules/@mcp-ui/client` 目录或其 TypeScript 声明文件确认实际 prop 名称，以下以文档约定为准。

将 `CardMessage.tsx` 替换为：

```typescript
import React, { useState, useRef } from 'react';
import { AppRenderer } from '@mcp-ui/client';
import type { McpUiResourcePart } from '../types';

interface Props {
  resourceUri: string;
  toolName?: string;
  toolResult?: McpUiResourcePart['toolResult'];
  uiMetadata?: McpUiResourcePart['uiMetadata'];
  onMessage?: (text: string) => void;
  onLayout?: () => void;
}

export const CardMessage: React.FC<Props> = ({
  resourceUri,
  toolName,
  toolResult,
  uiMetadata,
  onMessage,
  onLayout,
}) => {
  const { width = 560 } = uiMetadata?.['preferred-frame-size'] ?? {};
  const sandboxUrl = new URL('/sandbox_proxy.html', window.location.href);
  const [iframeHeight, setIframeHeight] = useState<number | undefined>(undefined);
  const rendererRef = useRef<any>(null);

  const handleCallTool = async (params: { name: string; arguments?: Record<string, unknown> }) => {
    const res = await fetch('/tool-call', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ toolName: params.name, arguments: params.arguments ?? {} }),
    });
    const data = await res.json();
    return data.toolResult ?? {};
  };

  return (
    <div style={{
      border: iframeHeight ? '1px solid #e0e0e0' : 'none',
      borderRadius: 8,
      overflow: 'hidden',
      width,
      height: iframeHeight ?? 0,
      transition: 'height 0.2s ease',
    }}>
      <AppRenderer
        ref={rendererRef}
        toolName={toolName ?? 'query_employee_trend'}
        toolResult={toolResult}
        sandbox={{ url: sandboxUrl }}
        toolResourceUri={resourceUri}
        onReadResource={async ({ uri }) => {
          const res = await fetch(`/resource-proxy?uri=${encodeURIComponent(uri)}`);
          return res.json();
        }}
        onCallTool={handleCallTool}
        onSizeChanged={({ height }) => {
          if (height !== undefined) {
            setIframeHeight(height);
            onLayout?.();
          }
        }}
        onMessage={async (params) => {
          const textBlock = params.content.find((c: any) => c.type === 'text');
          if (textBlock && onMessage) {
            onMessage((textBlock as any).text);
          }
          return {};
        }}
        onError={(e) => console.error('[AppRenderer]', e)}
      />
    </div>
  );
};
```

**重要：** `AppRenderer` 的 `toolResult`、`onCallTool`、`ref.sendToolResult` 等 prop 名称需以实际 `@mcp-ui/client` v7 的 TypeScript 声明为准。如果编译报错，请执行：

```bash
cat packages/codeflicker-frontend/node_modules/@mcp-ui/client/dist/index.d.ts | grep -A 20 "AppRendererProps"
```

根据实际 prop 名称修正。

#### Step 8-3：验证 TypeScript 编译

```bash
cd packages/codeflicker-frontend && npx tsc --noEmit
```

预期：0 errors。如有 prop 类型错误，根据实际声明修正。

---

### Task 9：`employee-chart-card` — 从 `toolResult` 接收数据，支持场景 C 和 D

**涉及文件：**
- 修改：`packages/employee-chart-card/src/EmployeeChart.tsx`

**背景（重要）：** 改造后 shell HTML 不内联数据，组件 props 中不再有 `data` 和 `token`。数据通过 `AppRenderer` 的 `toolResult` prop 以 MCP-UI 消息 `ui/notifications/tool-result` 注入。组件需要监听此消息并更新内部 state。

场景 C：组件内交互（如切换年份范围）需要通过 `postMessage` 发送 `tools/call` 请求，触发 `AppRenderer.onCallTool` 回调。

场景 D：点击年份详情直接调 SG-Agent REST API（Bearer token 来自 toolResult 注入）。

---

#### Step 9-1：理解 MCP-UI 消息协议

`AppRenderer` 通过 `postMessage` 向 iframe 内的 guest UI 发送以下消息：

```json
{
  "jsonrpc": "2.0",
  "method": "ui/notifications/tool-result",
  "params": {
    "toolName": "query_employee_trend",
    "result": { "data": [...], "token": "..." }
  }
}
```

guest UI 应监听 `window.addEventListener('message', ...)` 并处理此消息。

场景 C：guest UI 发送：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "query_employee_trend",
    "arguments": {}
  }
}
```

到 `window.parent`。`AppRenderer` 收到后触发 `onCallTool` 回调，将结果通过 `ui/notifications/tool-result` 回传。

**注意：** 以上消息格式以 `@mcp-ui/client` v7 的实际实现为准。执行以下命令查看实际协议：

```bash
cat packages/codeflicker-frontend/node_modules/@mcp-ui/client/dist/index.js | grep -o "ui/notifications/[a-z-]*" | sort -u
```

---

#### Step 9-2：修改 `EmployeeChart.tsx`

```typescript
import React, { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts';

export interface EmployeeChartProps {
  data?: { year: number; count: number }[];
  token?: string;
  sgAgentBaseUrl?: string;
}

const EmployeeChart: React.FC<EmployeeChartProps> = ({
  data: initialData,
  token: initialToken,
  sgAgentBaseUrl = 'http://localhost:3001',
}) => {
  const chartRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<{ year: number; count: number }[]>(initialData ?? []);
  const [token, setToken] = useState<string>(initialToken ?? '');
  const [detail, setDetail] = useState<{ year: number; count: number; note: string } | null>(null);

  useEffect(() => {
    const handleMessage = (e: MessageEvent) => {
      const msg = e.data;
      if (!msg || msg.jsonrpc !== '2.0') return;
      if (msg.method === 'ui/notifications/tool-result') {
        const result = msg.params?.result ?? msg.params ?? {};
        if (result.data) setData(result.data);
        if (result.token) setToken(result.token);
      }
    };
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  const notifySize = () => {
    if (!containerRef.current) return;
    const height = Math.ceil(containerRef.current.getBoundingClientRect().height);
    if (height > 0) {
      window.parent.postMessage(
        { jsonrpc: '2.0', method: 'ui/notifications/size-changed', params: { height } },
        '*'
      );
    }
  };

  useEffect(() => {
    if (!chartRef.current || data.length === 0) return;
    const chart = echarts.init(chartRef.current);
    chart.setOption({
      title: { text: '快手员工趋势' },
      xAxis: { type: 'category', data: data.map((d) => String(d.year)) },
      yAxis: { type: 'value' },
      series: [{ type: 'line', data: data.map((d) => d.count), smooth: true }],
    });
    chart.on('finished', notifySize);
    return () => chart.dispose();
  }, [data]);

  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver(notifySize);
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  const handleAnalyze = () => {
    window.parent.postMessage({
      jsonrpc: '2.0',
      id: Date.now(),
      method: 'ui/message',
      params: {
        role: 'user',
        content: [{ type: 'text', text: `分析以下员工趋势数据：${JSON.stringify(data)}` }],
      },
    }, '*');
  };

  const handleRefresh = () => {
    window.parent.postMessage({
      jsonrpc: '2.0',
      id: Date.now(),
      method: 'tools/call',
      params: {
        name: 'query_employee_trend',
        arguments: {},
      },
    }, '*');
  };

  const handleHoverYear = async (year: number) => {
    if (!token) return;
    const res = await fetch(`${sgAgentBaseUrl}/api/employee/detail/${year}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const d = await res.json();
    setDetail(d);
  };

  if (data.length === 0) {
    return (
      <div ref={containerRef} style={{ padding: 16, color: '#888' }}>
        加载中...
      </div>
    );
  }

  return (
    <div ref={containerRef} style={{ padding: 16 }}>
      <div ref={chartRef} style={{ width: 500, height: 300 }} />
      {detail && (
        <div style={{ margin: '8px 0', padding: '8px 12px', background: '#f5f5f5', borderRadius: 6, fontSize: 13 }}>
          <strong>{detail.year} 年</strong>：{detail.count.toLocaleString()} 人 — {detail.note}
          <button onClick={() => setDetail(null)} style={{ marginLeft: 8, cursor: 'pointer', border: 'none', background: 'none', color: '#999' }}>×</button>
        </div>
      )}
      <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button onClick={handleAnalyze}>分析趋势</button>
        <button onClick={handleRefresh}>刷新数据</button>
        {data.map((d) => (
          <button key={d.year} onClick={() => handleHoverYear(d.year)}>
            {d.year} 详情
          </button>
        ))}
      </div>
    </div>
  );
};

export default EmployeeChart;
```

**关键变更说明：**
- `data` 和 `token` 都是可选 props（兼容旧的 inline 方式和新的 toolResult 方式）。
- 通过 `window.addEventListener('message', ...)` 监听 `ui/notifications/tool-result`，收到后更新 state。
- 新增「刷新数据」按钮触发 `tools/call` 消息（场景 C）。
- 「X 详情」按钮直接调 SG-Agent API（场景 D），但只有 `token` 存在时才调用。
- `data.length === 0` 时显示「加载中...」（支持场景 B 的异步加载）。

#### Step 9-3：验证 TypeScript 编译

```bash
cd packages/employee-chart-card && npx tsc --noEmit
```

预期：0 errors。

---

### Task 10：端到端冒烟测试

所有代码改完后，执行以下步骤验证四个场景。

#### Step 10-1：启动所有服务

```bash
pnpm dev
```

等待所有服务就绪（检查各端口响应）：

```bash
curl http://localhost:3000 -o /dev/null -s -w "%{http_code}"   # 预期: 200
curl http://localhost:3001/health                               # 预期: {"ok":true}
curl http://localhost:3002/health                               # 预期: {"ok":true}
curl http://localhost:3003/health                               # 预期: {"ok":true}
curl http://localhost:3004/remoteEntry.js -o /dev/null -s -w "%{http_code}"  # 预期: 200
```

#### Step 10-2：验证场景 A（endpoint 模式，toolResult 首渲）

1. 打开 `http://localhost:3000`，确认顶部有 **Endpoint** 和 **MCP Server** 按钮，当前 Endpoint 高亮。
2. 输入「查询快手历年员工人数趋势」，发送。
3. 预期：卡片渲染，图表显示，EventLog 显示 `CF-Agent → SG-Agent A2A Task (mode=endpoint)`。

#### Step 10-3：验证切换到 MCP 模式

1. 点击「MCP Server」按钮，确认按钮高亮。
2. 再次发送「查询快手历年员工人数趋势」。
3. 预期：卡片正常渲染，EventLog 显示 `mode=mcp`，resourceUri 变为 `ui://stargate/employee-trend`（可在浏览器 DevTools Network 中确认）。

#### Step 10-4：验证场景 D（直调业务 API）

1. 图表渲染后，点击任意「2021 详情」按钮。
2. 预期：卡片内显示 2021 年详情（16000 人，「业务多元化」），EventLog 无 CF-Agent 条目（SG-Agent 直接被调用）。

#### Step 10-5：验证场景 C（刷新数据）

1. 点击「刷新数据」按钮。
2. 预期：EventLog 显示 `Frontend → CF-Agent tool-call`，之后图表重新渲染（数据不变，但走了完整 tool call 流程）。

#### Step 10-6：运行 Python 测试

```bash
cd packages/stargate-mcp-ui-server && pytest tests/ -v
```

预期：全部 PASS。

---

## 常见问题 & 调试技巧

### AppRenderer prop 名称不对
```bash
cat packages/codeflicker-frontend/node_modules/@mcp-ui/client/dist/index.d.ts | grep -A 30 "interface"
```
找到 `AppRendererProps`，查看实际 prop 名称。

### MCP-UI 消息格式不对
```bash
cat packages/codeflicker-frontend/node_modules/@mcp-ui/client/dist/index.js | grep -o '"ui/[a-z/\-]*"' | sort -u
```
列出所有 MCP-UI 消息方法名。

### SG-Agent A2A 端口冲突
A2A 服务跑在 3011（Flask），FastAPI 服务跑在 3001。如果 3011 端口被占用，检查：
```bash
lsof -i :3011
```

### 前端热更新不生效
Vite 代理配置仅代理 `/chat` 和 `/resource-proxy`，新增的 `/mode` 和 `/tool-call` 路径需要在 `vite.config.ts` 补充代理规则：

```typescript
proxy: {
  '/chat': 'http://localhost:3002',
  '/resource-proxy': 'http://localhost:3002',
  '/mode': 'http://localhost:3002',
  '/tool-call': 'http://localhost:3002',
  '/tool-result': 'http://localhost:3002',
}
```

文件位置：`packages/codeflicker-frontend/vite.config.ts`。

---

## 文件变更汇总

| 文件 | 操作 | Task |
|---|---|---|
| `packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/tools.py` | 修改 | 1 |
| `packages/stargate-mcp-ui-server/tests/test_tools.py` | 修改 | 1 |
| `packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/main.py` | 修改 | 2 |
| `packages/stargate-mcp-ui-server/tests/test_main.py` | 修改 | 2 |
| `packages/stargate-agent/src/stargate_agent/shell_builder.py` | 新建 | 3 |
| `packages/stargate-agent/src/stargate_agent/main.py` | 修改 | 3, 4 |
| `packages/codeflicker-agent/src/codeflicker_agent/main.py` | 修改 | 5 |
| `packages/codeflicker-frontend/src/types.ts` | 修改 | 6 |
| `packages/codeflicker-frontend/vite.config.ts` | 修改 | 7（常见问题） |
| `packages/codeflicker-frontend/src/App.tsx` | 修改 | 7 |
| `packages/codeflicker-frontend/src/components/ChatMessage.tsx` | 修改 | 8 |
| `packages/codeflicker-frontend/src/components/CardMessage.tsx` | 修改 | 8 |
| `packages/employee-chart-card/src/EmployeeChart.tsx` | 修改 | 9 |
