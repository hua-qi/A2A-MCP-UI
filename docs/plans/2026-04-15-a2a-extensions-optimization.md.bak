# A2A 扩展全量优化 Implementation Plan

**Goal:** 将三个 A2A 扩展（`structured-data`、`streaming`、`tool-protocol`）作为终态直接落地，废弃所有旧接口和降级路径，实现规范的 DataPart 传输、A2A 层 SSE streaming 和工具调用全链路走 A2A。

**Architecture:** 在 SG-Agent AgentCard `capabilities` 中声明三个扩展标记（因 python_a2a 0.5.10 不支持 `extensions` 字段）；SG-Agent Flask 层覆盖 `/tasks/stream` 路由实现 SSE 流式响应，事件中嵌入 span 数据供时序图使用；CF-Agent 直接透传 A2A stream 至前端；卡片 postMessage 经 CF-Agent 封装为 `ToolRequestPart` 走 A2A，响应拆包后转发回卡片；废弃 `/events`、`/tool-call`、`/tool-result` 端点。

**Tech Stack:** Python 3.11、python_a2a 0.5.10、Flask（A2A Server 层）、FastAPI（REST API 层）、SSE、React + TypeScript、Vite

**⚠️ 关键限制（python_a2a 0.5.10）：**
- `AgentCard` **不支持** `extensions` 字段 → 扩展声明改放在 `capabilities`
- **无** `DataPart` 类 → 使用 `FunctionResponseContent` 或手工构造 JSON-RPC
- `setup_routes` **不自动调用** → 需手动调用，可安全覆盖路由
- 已有 `/tasks/stream` 端点 → 覆盖该端点实现自定义 SSE

---

## 背景知识：项目结构

```
packages/
  codeflicker-agent/    # CF-Agent: FastAPI，A2A 客户端，对前端暴露 /chat
  stargate-agent/       # SG-Agent: FastAPI(REST) + Flask(A2A Server，端口 3011)
  stargate-mcp-ui-server/ # MCP Server: MCP SSE 协议，端口 3005
  codeflicker-frontend/ # React 前端，Vite proxy 到 3002
  employee-chart-card/  # 卡片组件，Module Federation
```

A2A 通信路径：
```
前端 → POST /chat → CF-Agent(:3002) → A2A send_message → SG-Agent Flask(:3011)
```

每个 Python 包用 `uv` 管理，测试用 `pytest`，运行命令：
```bash
cd packages/stargate-mcp-ui-server && uv run pytest tests/ -v
```

---

## Task 1：定义三个扩展规范文档

**背景：** A2A 规范要求扩展 URI 指向可访问的规范文档。先建立三个规范文件作为所有后续改动的语义锚点。

**Files:**
- Create: `ext-a2a-structured-data/spec.md`
- Create: `ext-a2a-streaming/spec.md`
- Create: `ext-a2a-tool-protocol/spec.md`

---

**Step 1: 创建 structured-data 扩展规范**

创建 `ext-a2a-structured-data/spec.md`：

```markdown
# A2A Structured Data Extension

**Extension URI:** `https://stargate.example.com/ext/a2a-structured-data/v1`
**Status:** Draft
**Version:** v1

## 概述

废弃在 `TextContent.text` 中序列化 JSON 的 hack，改用结构化 `DataPart` 传递业务数据。

## DataPart Schema

```json
{
  "kind": "data",
  "mimeType": "application/json",
  "schema": "<schema-uri>",
  "data": {}
}
```

### Agent Request Schema（CF-Agent → SG-Agent）

URI: `https://stargate.example.com/schemas/agent-request-v1`

```json
{
  "type": "object",
  "required": ["text", "mode"],
  "properties": {
    "text": { "type": "string" },
    "mode": { "type": "string", "enum": ["endpoint", "mcp"] }
  }
}
```

### Agent Response Schema（SG-Agent → CF-Agent）

URI: `https://stargate.example.com/schemas/agent-response-v1`

```json
{
  "type": "object",
  "required": ["text"],
  "properties": {
    "text": { "type": "string" },
    "mcp_ui_resource": {
      "type": "object",
      "properties": {
        "kind": { "type": "string", "const": "mcp_ui_resource" },
        "resourceUri": { "type": "string" },
        "toolName": { "type": "string" },
        "toolResult": { "type": "object" },
        "uiMetadata": { "type": "object" }
      }
    }
  }
}
```

## 激活方式

AgentCard 中声明：
```json
{ "uri": "https://stargate.example.com/ext/a2a-structured-data/v1", "required": true }
```
```

---

**Step 2: 创建 streaming 扩展规范**

创建 `ext-a2a-streaming/spec.md`：

```markdown
# A2A Streaming Extension

**Extension URI:** `https://stargate.example.com/ext/a2a-streaming/v1`
**Status:** Draft
**Version:** v1

## 概述

将 A2A 层响应从同步 JSON 改为 SSE 流式推送，允许 SG-Agent 在处理过程中实时推送中间状态。

## SSE 事件格式

### task_status 事件

```
event: task_status
data: {"state": "working", "progress": 0.3, "message": "正在查询 MCP..."}
```

### task_complete 事件

```
event: task_complete
data: {"state": "completed", "result": { <DataPart 格式的响应数据> }}
```

### task_error 事件

```
event: task_error
data: {"code": -32000, "message": "超时"}
```

## 激活方式

AgentCard 中声明：
```json
{ "uri": "https://stargate.example.com/ext/a2a-streaming/v1", "required": true }
```

AgentCard capabilities 中同时设置：`"streaming": true`

## CF-Agent 行为

收到 A2A SSE stream 后，直接将每条事件透传给前端，不缓冲全量结果。
前端通过 EventSource 连接 `/chat-stream` 端点（替代原 `/events`）接收进度。
```

---

**Step 3: 创建 tool-protocol 扩展规范**

创建 `ext-a2a-tool-protocol/spec.md`：

```markdown
# A2A Tool Protocol Extension

**Extension URI:** `https://stargate.example.com/ext/a2a-tool-protocol/v1`
**Status:** Draft
**Version:** v1

## 概述

将卡片内工具调用从独立 HTTP 接口（/tool-call、/tool-result）统一到 A2A 消息体内，使用 ToolRequestPart 和 ToolResponsePart。

## ToolRequestPart Schema

```json
{
  "kind": "tool_request",
  "id": "<唯一请求ID，字符串>",
  "toolName": "query_employee_trend",
  "arguments": {}
}
```

## ToolResponsePart Schema

```json
{
  "kind": "tool_response",
  "requestId": "<对应 ToolRequestPart.id>",
  "result": {}
}
```

## 调用流程

```
卡片 postMessage (jsonrpc tools/call)
  → CF-Agent: 提取 toolName/arguments，生成 requestId
  → CF-Agent: 构造 Message(ToolRequestPart) 发给 SG-Agent via A2A
  → SG-Agent: 处理工具调用，返回 Message(ToolResponsePart)
  → CF-Agent: 提取 result，postMessage 回卡片
```

## 激活方式

AgentCard 中声明：
```json
{ "uri": "https://stargate.example.com/ext/a2a-tool-protocol/v1", "required": true }
```
```

---

**Step 4: 验证三个目录已创建**

```bash
ls ext-a2a-structured-data/ ext-a2a-streaming/ ext-a2a-tool-protocol/
```

预期输出：每个目录下有 `spec.md`

---

## Task 2：更新 SG-Agent AgentCard 声明（适配 python_a2a 0.5.10）

**背景：** `StargateA2AServer` 的 `_start_a2a_flask()` 函数创建 AgentCard。由于 python_a2a 0.5.10 的 `AgentCard` **不支持** `extensions` 字段，扩展声明需放在 `capabilities` 中。

**Files:**
- Modify: `packages/stargate-agent/src/stargate_agent/main.py`

---

**Step 1: 写失败测试**

在 `packages/stargate-agent/src/` 目录下新建测试文件 `tests/__init__.py` 和 `tests/test_agent_card.py`：

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from stargate_agent.main import build_agent_card

EXPECTED_EXTENSIONS = [
    "a2a-structured-data",
    "a2a-streaming",
    "a2a-tool-protocol",
]

def test_agent_card_has_three_extensions_in_capabilities():
    card = build_agent_card()
    card_dict = card.to_dict()
    capabilities = card_dict.get("capabilities", {})
    for ext in EXPECTED_EXTENSIONS:
        assert capabilities.get(ext) is True, f"Missing extension in capabilities: {ext}"

def test_agent_card_streaming_enabled():
    card = build_agent_card()
    card_dict = card.to_dict()
    capabilities = card_dict.get("capabilities", {})
    assert capabilities.get("streaming") is True
```

**Step 2: 运行测试，确认失败**

```bash
cd packages/stargate-agent && uv run pytest tests/test_agent_card.py -v
```

预期：`FAILED` — `build_agent_card` 函数不存在

**Step 3: 在 `main.py` 中提取 `build_agent_card()` 函数**

在 `packages/stargate-agent/src/stargate_agent/main.py` 中，找到 `_start_a2a_flask()` 函数，将 AgentCard 构造逻辑提取为独立函数：

```python
def build_agent_card() -> AgentCard:
    return AgentCard(
        name="stargate-agent",
        description="Stargate A2A Agent with MCP-UI support",
        url=f"http://localhost:{A2A_PORT}",
        version="0.1.0",
        capabilities={
            "streaming": True,
            "a2a-structured-data": True,
            "a2a-streaming": True,
            "a2a-tool-protocol": True,
        },
    )
```

然后在 `_start_a2a_flask()` 中改为：

```python
def _start_a2a_flask():
    from flask import Flask
    flask_app = Flask(__name__)
    agent_card = build_agent_card()
    a2a_server = StargateA2AServer(agent_card=agent_card)
    a2a_server.setup_routes(flask_app)
    flask_app.run(host="0.0.0.0", port=A2A_PORT, debug=False, use_reloader=False)
```

**Step 4: 运行测试，确认通过**

```bash
cd packages/stargate-agent && uv run pytest tests/test_agent_card.py -v
```

预期：2 个 `PASSED`

---

## Task 3：CF-Agent 启动时校验扩展协商（适配 capabilities）

**背景：** CF-Agent 每次调用 SG-Agent 前需获取其 AgentCard 并校验三个扩展标记均在 `capabilities` 中为 `True`。任意缺失则抛出异常，返回 `-32001` 错误。

**Files:**
- Create: `packages/codeflicker-agent/src/codeflicker_agent/extension_negotiation.py`
- Create: `packages/codeflicker-agent/tests/test_extension_negotiation.py`
- Modify: `packages/codeflicker-agent/src/codeflicker_agent/main.py`

---

**Step 1: 写失败测试**

创建 `packages/codeflicker-agent/tests/__init__.py`（空文件）和 `tests/test_extension_negotiation.py`：

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))
import pytest
from codeflicker_agent.extension_negotiation import validate_extensions, ExtensionNegotiationError

REQUIRED_EXT_KEYS = [
    "a2a-structured-data",
    "a2a-streaming",
    "a2a-tool-protocol",
]

def _make_card(capabilities):
    return {"capabilities": capabilities}

def test_validate_passes_when_all_extensions_enabled():
    card = _make_card({k: True for k in REQUIRED_EXT_KEYS})
    validate_extensions(card)  # 不抛出异常

def test_validate_fails_when_extension_missing():
    card = _make_card({
        REQUIRED_EXT_KEYS[0]: True,
        REQUIRED_EXT_KEYS[1]: True,
    })
    with pytest.raises(ExtensionNegotiationError) as exc:
        validate_extensions(card)
    assert REQUIRED_EXT_KEYS[2] in str(exc.value)

def test_validate_fails_when_extension_not_true():
    card = _make_card({
        REQUIRED_EXT_KEYS[0]: True,
        REQUIRED_EXT_KEYS[1]: False,  # not True
        REQUIRED_EXT_KEYS[2]: True,
    })
    with pytest.raises(ExtensionNegotiationError) as exc:
        validate_extensions(card)
    assert REQUIRED_EXT_KEYS[1] in str(exc.value)

def test_validate_fails_when_capabilities_absent():
    with pytest.raises(ExtensionNegotiationError):
        validate_extensions({})
```

**Step 2: 运行测试，确认失败**

```bash
cd packages/codeflicker-agent && uv run pytest tests/test_extension_negotiation.py -v
```

预期：`ModuleNotFoundError: codeflicker_agent.extension_negotiation`

**Step 3: 实现 `extension_negotiation.py`**

创建 `packages/codeflicker-agent/src/codeflicker_agent/extension_negotiation.py`：

```python
REQUIRED_EXT_KEYS = [
    "a2a-structured-data",
    "a2a-streaming",
    "a2a-tool-protocol",
]


class ExtensionNegotiationError(Exception):
    pass


def validate_extensions(agent_card: dict) -> None:
    capabilities = agent_card.get("capabilities", {})
    for key in REQUIRED_EXT_KEYS:
        if capabilities.get(key) is not True:
            raise ExtensionNegotiationError(
                f"Required extension not enabled: {key}"
            )
```

**Step 4: 运行测试，确认通过**

```bash
cd packages/codeflicker-agent && uv run pytest tests/test_extension_negotiation.py -v
```

预期：4 个 `PASSED`  (如 AgentCard 不直接支持 `extensions`/`capabilities` 字段，则需要先检查 `python_a2a` 版本，见 Task 3 备注)

**Step 4: 运行测试，确认通过**

```bash
cd packages/codeflicker-agent && uv run pytest tests/test_extension_negotiation.py -v
```

预期：4 个 `PASSED`

**Step 5: 在 CF-Agent `main.py` 中集成校验**

在 `packages/codeflicker-agent/src/codeflicker_agent/main.py` 顶部加入导入：

```python
from codeflicker_agent.extension_negotiation import validate_extensions, ExtensionNegotiationError
```

新增函数 `_get_and_validate_sg_card()`，在 `_call_sg_agent` 调用前执行：

```python
def _get_and_validate_sg_card() -> None:
    import httpx
    resp = httpx.get(f"{SG_AGENT_A2A_URL}/.well-known/agent.json", timeout=5.0)
    resp.raise_for_status()
    validate_extensions(resp.json())
```

在 `/chat` 端点的 `_call_sg_agent` 调用前插入：

```python
try:
    _get_and_validate_sg_card()
except ExtensionNegotiationError as e:
    return JSONResponse({"error": {"code": -32001, "message": str(e)}}, status_code=400)
```

---

## Task 4：实现结构化数据传输 — 废弃 TextContent JSON-in-text（使用 FunctionResponseContent）

**背景：** 当前 `_call_sg_agent` 把业务 payload 序列化进 `TextContent.text`，SG-Agent 的 `handle_message` 也从 `message.content.text` 反序列化。python_a2a 0.5.10 **不支持** `DataPart`，使用 `FunctionResponseContent` 传递结构化数据（通过 `name` 字段标识 schema，通过 `response` 字段传递数据）。

**Files:**
- Create: `packages/codeflicker-agent/src/codeflicker_agent/a2a_parts.py`
- Create: `packages/codeflicker-agent/tests/test_a2a_parts.py`
- Modify: `packages/codeflicker-agent/src/codeflicker_agent/main.py`
- Modify: `packages/stargate-agent/src/stargate_agent/main.py`

---

**Step 1: 确认使用 FunctionResponseContent**

```bash
cd packages/codeflicker-agent && uv run python -c "from python_a2a import FunctionResponseContent; print('ok')"
```

预期输出：`ok` — `FunctionResponseContent` 存在且可用。

**Step 2: 写失败测试**

创建 `packages/codeflicker-agent/tests/test_a2a_parts.py`：

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))
from codeflicker_agent.a2a_parts import (
    make_agent_request,
    parse_agent_response,
)

def test_make_agent_request_structure():
    content = make_agent_request(text="查询员工", mode="endpoint")
    assert content["type"] == "function_response"
    assert content["name"] == "agent-request-v1"
    assert content["response"]["text"] == "查询员工"
    assert content["response"]["mode"] == "endpoint"

def test_parse_agent_response_text_only():
    content = {
        "type": "function_response",
        "name": "agent-response-v1",
        "response": {"text": "回复内容"},
    }
    result = parse_agent_response(content)
    assert result["text"] == "回复内容"
    assert "mcp_ui_resource" not in result

def test_parse_agent_response_with_resource():
    content = {
        "type": "function_response",
        "name": "agent-response-v1",
        "response": {
            "text": "已查询",
            "mcp_ui_resource": {
                "kind": "mcp_ui_resource",
                "resourceUri": "ui://stargate/employee-trend",
                "toolName": "query_employee_trend",
                "toolResult": {},
                "uiMetadata": {},
            },
        },
    }
    result = parse_agent_response(content)
    assert result["mcp_ui_resource"]["resourceUri"] == "ui://stargate/employee-trend"

def test_parse_raises_on_wrong_name():
    import pytest
    with pytest.raises(ValueError, match="name"):
        parse_agent_response({
            "type": "function_response",
            "name": "wrong-schema",
            "response": {"text": "x"},
        })
```

**Step 3: 运行测试，确认失败**

```bash
cd packages/codeflicker-agent && uv run pytest tests/test_a2a_parts.py -v
```

**Step 4: 实现 `a2a_parts.py`**

创建 `packages/codeflicker-agent/src/codeflicker_agent/a2a_parts.py`：

```python
REQUEST_NAME = "agent-request-v1"
RESPONSE_NAME = "agent-response-v1"


def make_agent_request(text: str, mode: str) -> dict:
    """Return dict that can be used with FunctionResponseContent"""
    return {
        "type": "function_response",
        "name": REQUEST_NAME,
        "response": {"text": text, "mode": mode},
    }


def parse_agent_response(content: dict) -> dict:
    """Parse FunctionResponseContent dict"""
    if content.get("type") != "function_response":
        raise ValueError(f"Expected type=function_response, got: {content.get('type')!r}")
    if content.get("name") != RESPONSE_NAME:
        raise ValueError(f"Unexpected name: {content.get('name')!r}, expected {RESPONSE_NAME!r}")
    return content.get("response", {})
```

**Step 5: 运行测试，确认通过**

```bash
cd packages/codeflicker-agent && uv run pytest tests/test_a2a_parts.py -v
```

预期：4 个 `PASSED`

**Step 6: 更新 CF-Agent `_call_sg_agent` 使用 FunctionResponseContent**

在 `packages/codeflicker-agent/src/codeflicker_agent/main.py` 中：

```python
from python_a2a import FunctionResponseContent
from codeflicker_agent.a2a_parts import make_agent_request, parse_agent_response
```

将 `_call_sg_agent` 中的消息构造改为：

```python
def _call_sg_agent(user_text: str, mode: str) -> list:
    request_dict = make_agent_request(text=user_text, mode=mode)
    client = A2AClient(endpoint_url=SG_AGENT_A2A_URL)
    response_msg = client.send_message(
        Message(
            content=FunctionResponseContent(
                name=request_dict["name"],
                response=request_dict["response"],
            ),
            role=MessageRole.USER,
        )
    )
    parts = []
    if hasattr(response_msg, "content"):
        content = response_msg.content
        content_dict = content if isinstance(content, dict) else vars(content)
        data = parse_agent_response(content_dict)
        if "text" in data:
            parts.append({"kind": "text", "text": data["text"]})
        if "mcp_ui_resource" in data:
            parts.append(data["mcp_ui_resource"])
    return parts
```

**Step 7: 更新 SG-Agent `handle_message` 解析 FunctionResponseContent**

在 `packages/stargate-agent/src/stargate_agent/main.py` 的 `StargateA2AServer.handle_message` 中，将解析逻辑替换为：

```python
def handle_message(self, message: Message) -> Message:
    from python_a2a import FunctionResponseContent
    user_text = ""
    mode = "endpoint"
    content = message.content
    content_dict = content if isinstance(content, dict) else vars(content)
    
    # Check for FunctionResponseContent (structured-data extension)
    if content_dict.get("type") == "function_response":
        if content_dict.get("name") == "agent-request-v1":
            response_data = content_dict.get("response", {})
            user_text = response_data.get("text", "")
            mode = response_data.get("mode", "endpoint")
        else:
            raise ValueError(f"Unsupported function_response name: {content_dict.get('name')}")
    elif hasattr(content, "text"):
        raise ValueError("TextContent is not supported; use FunctionResponseContent (structured-data extension)")
    
    # ... rest of handle_message logic ...
    
    # Return response using FunctionResponseContent
    response_data = {
        "text": "回复内容",
        "mcp_ui_resource": {...},  # if applicable
    }
    return Message(
        content=FunctionResponseContent(
            name="agent-response-v1",
            response=response_data,
        ),
        role=MessageRole.AGENT,
    )
```

响应构造同样改为 DataPart：

```python
response_part = {
    "kind": "data",
    "mimeType": "application/json",
    "schema": "https://stargate.example.com/schemas/agent-response-v1",
    "data": response_data,
}
return Message(
    content=DataPart(**response_part),  # 或手工构造
    role=MessageRole.AGENT,
)
```

---

## Task 5：实现 A2A Streaming — 覆盖 `/tasks/stream` 并嵌入 span 数据

**背景：** SG-Agent 的 Flask A2A handler 当前返回同步 JSON。改为覆盖 python_a2a 的 `/tasks/stream` 端点，返回 SSE 流式响应，在各异步调用完成时推送 `task_status` 事件（嵌入 span 数据供时序图使用），最终推送 `task_complete`。CF-Agent 侧改为接收 stream 并透传给前端的 `/chat-stream` 端点，废弃 `/events` 自建 SSE。

**Files:**
- Create: `packages/stargate-agent/src/stargate_agent/a2a_streaming.py`
- Create: `packages/stargate-agent/tests/test_a2a_streaming.py`
- Modify: `packages/stargate-agent/src/stargate_agent/main.py`
- Modify: `packages/codeflicker-agent/src/codeflicker_agent/main.py`
- Modify: `packages/codeflicker-frontend/vite.config.ts`（移除 `/events` proxy）

---

**Step 1: 写失败测试**

创建 `packages/stargate-agent/tests/test_a2a_streaming.py`：

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))
from stargate_agent.a2a_streaming import (
    make_status_event,
    make_complete_event,
    make_error_event,
    parse_sse_events,
)

def test_make_status_event_format():
    event = make_status_event(progress=0.3, message="正在查询", span={"id": "s1"})
    assert event.startswith("event: task_status\n")
    assert '"state": "working"' in event
    assert '"progress": 0.3' in event
    assert '"id": "s1"' in event
    assert event.endswith("\n\n")

def test_make_complete_event_format():
    result = {"text": "done", "mcp_ui_resource": None}
    event = make_complete_event(result=result)
    assert event.startswith("event: task_complete\n")
    assert '"state": "completed"' in event
    assert event.endswith("\n\n")

def test_make_error_event_format():
    event = make_error_event(code=-32000, message="timeout")
    assert event.startswith("event: task_error\n")
    assert '"-32000"' in event or "-32000" in event
    assert event.endswith("\n\n")

def test_parse_sse_events_extracts_complete():
    import json
    result_data = {"text": "ok"}
    raw = make_complete_event(result=result_data)
    events = parse_sse_events(raw)
    assert len(events) == 1
    assert events[0]["type"] == "task_complete"
    assert events[0]["data"]["result"]["text"] == "ok"
```

**Step 2: 运行测试，确认失败**

```bash
cd packages/stargate-agent && uv run pytest tests/test_a2a_streaming.py -v
```

**Step 3: 实现 `a2a_streaming.py`**

创建 `packages/stargate-agent/src/stargate_agent/a2a_streaming.py`：

```python
import json


def make_status_event(progress: float, message: str, span: dict = None) -> str:
    data = {"state": "working", "progress": progress, "message": message}
    if span:
        data["span"] = span
    return f"event: task_status\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def make_complete_event(result: dict, span: dict = None) -> str:
    data = {"state": "completed", "result": result}
    if span:
        data["span"] = span
    return f"event: task_complete\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def make_error_event(code: int, message: str) -> str:
    data = {"code": code, "message": message}
    return f"event: task_error\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def parse_sse_events(raw: str) -> list:
    events = []
    for block in raw.strip().split("\n\n"):
        lines = block.strip().split("\n")
        event_type = None
        data_str = None
        for line in lines:
            if line.startswith("event: "):
                event_type = line[len("event: "):]
            elif line.startswith("data: "):
                data_str = line[len("data: "):]
        if event_type and data_str:
            events.append({"type": event_type, "data": json.loads(data_str)})
    return events
```

**Step 4: 运行测试，确认通过**

```bash
cd packages/stargate-agent && uv run pytest tests/test_a2a_streaming.py -v
```

预期：4 个 `PASSED`

**Step 5: 覆盖 `/tasks/stream` 路由实现 SSE**

在 `packages/stargate-agent/src/stargate_agent/main.py` 中：

```python
from stargate_agent.a2a_streaming import make_status_event, make_complete_event, make_error_event
from flask import Response, stream_with_context
```

在 `_start_a2a_flask()` 中，在 `a2a_server.setup_routes(flask_app)` 之后，覆盖 `/tasks/stream` 路由（python_a2a 默认已注册，覆盖即可）：

```python
@flask_app.route("/tasks/stream", methods=["POST"])
def a2a_stream_handler():
    from flask import request as flask_request
    import json as _json
    body = flask_request.get_json(force=True)
    params = body.get("params", {})
    message_data = params.get("message", {})

    def generate():
        try:
            span = {"id": f"sg-{uuid.uuid4().hex[:8]}", "from": "CF-Agent", "to": "SG-Agent"}
            yield make_status_event(progress=0.1, message="收到请求，解析中...", span=span)
            content = message_data.get("content", {})
            
            # Check for FunctionResponseContent (structured-data extension)
            if content.get("type") != "function_response":
                yield make_error_event(-32602, "Expected FunctionResponseContent with structured-data extension")
                return
            if content.get("name") != "agent-request-v1":
                yield make_error_event(-32602, f"Unsupported request type: {content.get('name')}")
                return
                
            req_data = content.get("response", {})
            user_text = req_data.get("text", "")
            mode = req_data.get("mode", "endpoint")

            yield make_status_event(progress=0.3, message="工具识别中...", span=span)
            tool_name, tool_args = _run_async(llm.select_tool(user_text))

            yield make_status_event(progress=0.5, message=f"调用工具 {tool_name}...", span=span)
            response_data = _run_async(_execute_tool(tool_name, mode, span))

            yield make_complete_event(result=response_data)
        except Exception as e:
            yield make_error_event(-32000, str(e))

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

将原 `handle_message` 的工具调用逻辑重构到 `_execute_tool(tool_name, mode)` 异步函数中，返回 `response_data` dict。

**Step 6: 改造 CF-Agent 接收 SSE stream**

在 `packages/codeflicker-agent/src/codeflicker_agent/main.py` 中，将 `_call_sg_agent` 改为用 `httpx` 流式读取：

```python
import httpx
from codeflicker_agent.a2a_stream_client import call_sg_agent_streaming
```

创建 `packages/codeflicker-agent/src/codeflicker_agent/a2a_stream_client.py`：

```python
import json
import httpx
from typing import AsyncGenerator


TASK_COMPLETE = "task_complete"
TASK_ERROR = "task_error"


async def call_sg_agent_streaming(
    endpoint_url: str,
    request_part: dict,
) -> AsyncGenerator[dict, None]:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "content": request_part,
            }
        },
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", endpoint_url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("event: "):
                    event_type = line[len("event: "):]
                elif line.startswith("data: "):
                    data = json.loads(line[len("data: "):])
                    yield {"type": event_type, "data": data}
                    if event_type in (TASK_COMPLETE, TASK_ERROR):
                        return
```

**Step 7: 改造 `/chat` 端点为 SSE 透传**

在 `packages/codeflicker-agent/src/codeflicker_agent/main.py` 中，将 `/chat` 端点改为 SSE 流式响应，废弃 `/events` 端点：

```python
from fastapi.responses import StreamingResponse
from codeflicker_agent.a2a_stream_client import call_sg_agent_streaming
from codeflicker_agent.a2a_parts import make_agent_request_part

@app.post("/chat-stream")
async def chat_stream(request: Request):
    body = await request.json()
    user_message: str = body.get("message", "")

    intent = await llm.detect_intent(user_message)

    async def generate():
        if intent != "query_data":
            result = {"parts": [{"kind": "text", "text": "您好！我是 CodeFlicker 助手。"}]}
            yield f"event: task_complete\ndata: {json.dumps(result)}\n\n"
            return
        request_part = make_agent_request_part(text=user_message, mode=current_mode)
        async for event in call_sg_agent_streaming(SG_AGENT_A2A_URL, request_part):
            if event["type"] == "task_status":
                yield f"event: task_status\ndata: {json.dumps(event['data'])}\n\n"
            elif event["type"] == "task_complete":
                sg_result = event["data"].get("result", {})
                parts = []
                if "text" in sg_result:
                    parts.append({"kind": "text", "text": sg_result["text"]})
                if "mcp_ui_resource" in sg_result:
                    parts.append(sg_result["mcp_ui_resource"])
                final = {"parts": parts}
                yield f"event: task_complete\ndata: {json.dumps(final)}\n\n"
            elif event["type"] == "task_error":
                yield f"event: task_error\ndata: {json.dumps(event['data'])}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```

废弃旧的 `/events` 端点（直接删除该路由）。

**Step 8: 更新前端 `App.tsx` 使用 EventSource**

在 `packages/codeflicker-frontend/src/App.tsx` 中，将 `sendMessage` 的 `fetch('/chat')` 改为 `EventSource('/chat-stream')`：

```typescript
const sendMessage = async (text?: string) => {
  const finalText = (text ?? input).trim();
  if (!finalText || loading) return;
  setInput('');
  setLoading(true);

  const userMsg: ChatMessageType = {
    id: newId(), role: 'user',
    parts: [{ kind: 'text', text: finalText }],
  };
  setMessages((prev) => [...prev, userMsg]);

  const url = `/chat-stream?` + new URLSearchParams({ message: finalText });
  // EventSource 不支持 POST，改用 fetch SSE
  const res = await fetch('/chat-stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: finalText }),
  });
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() ?? '';
    for (const block of blocks) {
      const eventLine = block.split('\n').find(l => l.startsWith('event: '));
      const dataLine = block.split('\n').find(l => l.startsWith('data: '));
      if (!eventLine || !dataLine) continue;
      const eventType = eventLine.slice('event: '.length);
      const data = JSON.parse(dataLine.slice('data: '.length));
      if (eventType === 'task_status') {
        // 可在此更新 loading 文案
      } else if (eventType === 'task_complete') {
        const parts: MessagePart[] = (data.parts ?? []).map((p: any) => {
          if (p.kind === 'text') return { kind: 'text' as const, text: p.text };
          if (p.kind === 'mcp_ui_resource') return { kind: 'mcp_ui_resource' as const, ...p };
          return { kind: 'text' as const, text: JSON.stringify(p) };
        });
        setMessages((prev) => [...prev, { id: newId(), role: 'agent', parts }]);
        setLoading(false);
      } else if (eventType === 'task_error') {
        setMessages((prev) => [...prev, {
          id: newId(), role: 'agent',
          parts: [{ kind: 'text', text: `错误: ${data.message}` }],
        }]);
        setLoading(false);
      }
    }
  }
};
```

同时删除 `useEventLog` 对 `/events` 端点的订阅（该 hook 已无用），移除 `eventEntries` 和 `SequenceDiagram` 从 `/events` 读数据的部分（时序图改用 A2A stream 内的 span 数据，或直接废弃）。

**Step 9: 更新 vite.config.ts**

在 `packages/codeflicker-frontend/vite.config.ts` 中，移除 proxy 中的 `/events`，并新增 `/chat-stream`：

```typescript
proxy: {
  '/chat-stream': 'http://localhost:3002',
  '/resource-proxy': 'http://localhost:3002',
  '/mode': 'http://localhost:3002',
},
```

删除 `/tool-call`、`/tool-result`、`/chat` 的 proxy 条目。

---

## Task 6：实现 tool-protocol — 工具调用统一走 A2A

**背景：** 当前卡片 `tools/call` postMessage 经 `/tool-call` HTTP 接口转发给 SG-Agent。改为 CF-Agent 封装 `ToolRequestPart`，走已有的 A2A streaming 连接，收到 `ToolResponsePart` 后转发回卡片。废弃 `/tool-call` 和 `/tool-result` 端点。

**Files:**
- Create: `packages/codeflicker-agent/src/codeflicker_agent/tool_protocol.py`
- Create: `packages/codeflicker-agent/tests/test_tool_protocol.py`
- Modify: `packages/codeflicker-agent/src/codeflicker_agent/main.py`
- Modify: `packages/stargate-agent/src/stargate_agent/main.py`（SG-Agent 识别 ToolRequestPart）
- Modify: `packages/codeflicker-frontend/src/components/CardMessage.tsx`（或调用卡片的父组件）

---

**Step 1: 写失败测试**

创建 `packages/codeflicker-agent/tests/test_tool_protocol.py`：

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))
from codeflicker_agent.tool_protocol import (
    make_tool_request_part,
    parse_tool_response_part,
)
import pytest

def test_make_tool_request_part_structure():
    part = make_tool_request_part(
        request_id="req-001",
        tool_name="query_employee_trend",
        arguments={"year": 2023},
    )
    assert part["kind"] == "tool_request"
    assert part["id"] == "req-001"
    assert part["toolName"] == "query_employee_trend"
    assert part["arguments"] == {"year": 2023}

def test_parse_tool_response_part_ok():
    part = {
        "kind": "tool_response",
        "requestId": "req-001",
        "result": {"data": [1, 2, 3]},
    }
    result = parse_tool_response_part(part, expected_request_id="req-001")
    assert result == {"data": [1, 2, 3]}

def test_parse_tool_response_part_wrong_id_raises():
    part = {
        "kind": "tool_response",
        "requestId": "req-999",
        "result": {},
    }
    with pytest.raises(ValueError, match="requestId"):
        parse_tool_response_part(part, expected_request_id="req-001")

def test_parse_tool_response_part_wrong_kind_raises():
    with pytest.raises(ValueError, match="kind"):
        parse_tool_response_part(
            {"kind": "data", "requestId": "req-001", "result": {}},
            expected_request_id="req-001",
        )
```

**Step 2: 运行测试，确认失败**

```bash
cd packages/codeflicker-agent && uv run pytest tests/test_tool_protocol.py -v
```

**Step 3: 实现 `tool_protocol.py`**

创建 `packages/codeflicker-agent/src/codeflicker_agent/tool_protocol.py`：

```python
import uuid


def make_tool_request_part(
    request_id: str,
    tool_name: str,
    arguments: dict,
) -> dict:
    return {
        "kind": "tool_request",
        "id": request_id,
        "toolName": tool_name,
        "arguments": arguments,
    }


def parse_tool_response_part(part: dict, expected_request_id: str) -> dict:
    if part.get("kind") != "tool_response":
        raise ValueError(f"Expected kind=tool_response, got: {part.get('kind')!r}")
    if part.get("requestId") != expected_request_id:
        raise ValueError(
            f"requestId mismatch: expected {expected_request_id!r}, got {part.get('requestId')!r}"
        )
    return part.get("result", {})


def new_request_id() -> str:
    return str(uuid.uuid4())
```

**Step 4: 运行测试，确认通过**

```bash
cd packages/codeflicker-agent && uv run pytest tests/test_tool_protocol.py -v
```

预期：4 个 `PASSED`

**Step 5: 更新 CF-Agent — 废弃 `/tool-call` 端点，新增 A2A 工具调用路由**

在 `packages/codeflicker-agent/src/codeflicker_agent/main.py` 中：

删除整个 `/tool-call` 和 `/tool-result` 路由函数。

新增处理卡片 tool-call 消息的 WebSocket 或 POST 端点 `/a2a-tool-call`（由前端 CardMessage 组件调用，替代原 postMessage → `/tool-call` 路径）：

```python
from codeflicker_agent.tool_protocol import make_tool_request_part, parse_tool_response_part, new_request_id

@app.post("/a2a-tool-call")
async def a2a_tool_call(request: Request):
    body = await request.json()
    tool_name = body.get("toolName", "")
    arguments = body.get("arguments", {})
    request_id = new_request_id()

    tool_part = make_tool_request_part(
        request_id=request_id,
        tool_name=tool_name,
        arguments=arguments,
    )

    result = {}
    async for event in call_sg_agent_streaming(SG_AGENT_A2A_URL, tool_part):
        if event["type"] == "task_complete":
            result_data = event["data"].get("result", {})
            if result_data.get("kind") == "tool_response":
                result = parse_tool_response_part(result_data, expected_request_id=request_id)
            break
        elif event["type"] == "task_error":
            return JSONResponse(
                {"error": {"code": -32000, "message": event["data"].get("message", "tool error")}},
                status_code=500,
            )

    return JSONResponse({"toolResult": result})
```

**Step 6: 更新 SG-Agent `_execute_tool` 识别 ToolRequestPart**

在 `packages/stargate-agent/src/stargate_agent/main.py` 的 `_execute_tool`（Task 5 Step 5 中提取的函数）中，在工具调用前检查 content kind：

```python
async def _execute_tool(content: dict, mode: str) -> dict:
    kind = content.get("kind")
    if kind == "tool_request":
        tool_name = content.get("toolName", "")
        arguments = content.get("arguments", {})
        request_id = content.get("id", "")
        tool_result = await _run_tool(tool_name, arguments, mode)
        return {
            "kind": "tool_response",
            "requestId": request_id,
            "result": tool_result,
        }
    elif kind == "data":
        data = content.get("data", {})
        user_text = data.get("text", "")
        mode = data.get("mode", mode)
        return await _run_agent_query(user_text, mode)
    else:
        raise ValueError(f"Unsupported content kind: {kind!r}")
```

**Step 7: 更新前端 CardMessage 组件**

在 `packages/codeflicker-frontend/src/components/CardMessage.tsx` 中，找到处理 `tools/call` postMessage 的逻辑，将原来的 `fetch('/tool-call', ...)` 替换为 `fetch('/a2a-tool-call', ...)`：

```typescript
if (msg.method === 'tools/call') {
  const { name, arguments: args } = msg.params ?? {};
  const res = await fetch('/a2a-tool-call', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ toolName: name, arguments: args ?? {} }),
  });
  const data = await res.json();
  iframe.contentWindow?.postMessage({
    jsonrpc: '2.0',
    id: msg.id,
    result: data.toolResult,
  }, '*');
}
```

**Step 8: 更新 vite.config.ts 加入新端点**

```typescript
proxy: {
  '/chat-stream': 'http://localhost:3002',
  '/a2a-tool-call': 'http://localhost:3002',
  '/resource-proxy': 'http://localhost:3002',
  '/mode': 'http://localhost:3002',
},
```

---

## Task 7：全量回归测试

**Step 1: 运行所有 Python 测试**

```bash
cd packages/stargate-mcp-ui-server && uv run pytest tests/ -v
cd packages/stargate-agent && uv run pytest tests/ -v
cd packages/codeflicker-agent && uv run pytest tests/ -v
```

每个包预期全部 `PASSED`，无 `FAILED` 或 `ERROR`。

**Step 2: 启动所有服务，手动验证端到端**

```bash
# 终端 1：MCP Server
cd packages/stargate-mcp-ui-server && uv run python -m stargate_mcp_ui_server.main

# 终端 2：SG-Agent
cd packages/stargate-agent && uv run python -m stargate_agent.main

# 终端 3：CF-Agent
cd packages/codeflicker-agent && uv run python -m codeflicker_agent.main

# 终端 4：前端
cd packages/codeflicker-frontend && pnpm dev
```

**Step 3: 验证扩展协商**

访问 `http://localhost:3011/.well-known/agent.json`，确认响应中包含：

```json
"extensions": [
  { "uri": "https://stargate.example.com/ext/a2a-structured-data/v1", "required": true },
  { "uri": "https://stargate.example.com/ext/a2a-streaming/v1", "required": true },
  { "uri": "https://stargate.example.com/ext/a2a-tool-protocol/v1", "required": true }
]
```

**Step 4: 验证 DataPart 传输**

在浏览器 DevTools 中，发送消息"查询快手历年员工人数趋势"，在 Network 面板检查 `/chat-stream` 请求的 SSE 流，确认：
- 收到多条 `task_status` 事件
- 最终收到 `task_complete` 事件，payload 中无 TextContent，有 DataPart 格式的 mcp_ui_resource

**Step 5: 验证 tool-protocol**

在图表渲染后点击"刷新数据"按钮，检查 Network 面板确认走 `/a2a-tool-call` 而非 `/tool-call`，响应返回正确的 `toolResult`。

**Step 6: 确认废弃端点不可访问**

```bash
curl -X POST http://localhost:3002/tool-call  # 预期 404
curl http://localhost:3002/events             # 预期 404
curl -X POST http://localhost:3002/tool-result # 预期 404
```
