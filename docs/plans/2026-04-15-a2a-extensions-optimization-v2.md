# A2A 扩展全量优化 Implementation Plan (a2a-sdk 版本)

**Goal:** 迁移到 `a2a-sdk` 官方 SDK，完整实现三个 A2A 扩展（`structured-data`、`streaming`、`tool-protocol`），废弃所有旧接口，使用原生 `DataPart`、`AgentExtension` 和 SSE streaming。

**Architecture:** 双侧使用 `a2a-sdk`；SG-Agent 使用 `a2a.server` 的 HTTP 服务器，自定义 `/tasks/sendSubscribe` 处理函数实现 SSE；CF-Agent 使用 `a2a.client.A2AClient` 或原始 HTTP 连接接收 SSE；扩展声明使用原生 `AgentExtension` 模型；数据传输使用原生 `DataPart`。

**Tech Stack:** Python 3.11+、`a2a-sdk>=0.3.26`、Pydantic、FastAPI（REST API 层）、React + TypeScript、Vite

**迁移要点：**
- 依赖从 `python-a2a>=0.5.0` 改为 `a2a-sdk>=0.3.26`
- `AgentCard` 使用 Pydantic 模型，支持 `extensions: list[AgentExtension]`
- `Message.parts` 支持 `DataPart`、`TextPart` 等多种 Part 类型
- 服务器架构从 Flask 改为 `a2a.server` 的 HTTP 服务器

---

## 背景知识：a2a-sdk 核心概念

### AgentCard 与 Extensions

```python
from a2a.types import AgentCard, AgentCapabilities, AgentExtension

card = AgentCard(
    name="stargate-agent",
    description="Stargate A2A Agent with MCP-UI support",
    url="http://localhost:3011",
    version="0.1.0",
    capabilities=AgentCapabilities(
        streaming=True,
        extensions=[
            AgentExtension(
                uri="https://stargate.example.com/ext/a2a-structured-data/v1",
                name="structured-data",
                required=True
            ),
            AgentExtension(
                uri="https://stargate.example.com/ext/a2a-streaming/v1",
                name="streaming",
                required=True
            ),
            AgentExtension(
                uri="https://stargate.example.com/ext/a2a-tool-protocol/v1",
                name="tool-protocol",
                required=True
            ),
        ]
    ),
    defaultInputModes=["text/plain"],
    defaultOutputModes=["text/plain"],
    skills=[]
)
```

### Message 与 DataPart

```python
from a2a.types import Message, DataPart, TextPart

# 请求消息
request_msg = Message(
    role="user",
    parts=[
        DataPart(
            data={"text": "查询员工趋势", "mode": "endpoint"},
            metadata={"schema": "https://stargate.example.com/schemas/agent-request-v1"}
        )
    ]
)

# 响应消息  
response_msg = Message(
    role="agent",
    parts=[
        TextPart(text="已为您查询快手历年员工趋势数据"),
        DataPart(data={"mcp_ui_resource": {...}})
    ]
)
```

---

## Task 0：依赖迁移（双侧）

**Files:**
- Modify: `packages/codeflicker-agent/pyproject.toml`
- Modify: `packages/stargate-agent/pyproject.toml`

**Step 1: 更新 codeflicker-agent 依赖**

```toml
[project]
name = "codeflicker-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "a2a-sdk>=0.3.26",  # 替换 python-a2a
    "openai>=1.30.0",
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.29.0",
    "httpx>=0.27.0",
    "python-dotenv>=1.0.1",
]
```

**Step 2: 更新 stargate-agent 依赖**

```toml
[project]
name = "stargate-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "a2a-sdk[http-server]>=0.3.26",  # 包含 HTTP 服务器
    "mcp[server]>=1.5.0",
    "openai>=1.30.0",
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.29.0",
    "httpx>=0.27.0",
    "python-dotenv>=1.0.1",
    "mcp-ui-server>=1.0.0",
]
```

**Step 3: 重新安装依赖**

```bash
cd packages/codeflicker-agent && rm -rf .venv && uv sync
cd packages/stargate-agent && rm -rf .venv && uv sync
```

**Step 4: 验证安装**

```bash
cd packages/codeflicker-agent && uv run python -c "from a2a.types import AgentCard, DataPart; print('OK')"
cd packages/stargate-agent && uv run python -c "from a2a.types import AgentCard; from a2a.server import request_handlers; print('OK')"
```

---

## Task 1：SG-Agent AgentCard 声明

**Files:**
- Create: `packages/stargate-agent/tests/test_agent_card.py`
- Modify: `packages/stargate-agent/src/stargate_agent/main.py`

**Step 1: 写失败测试**

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))
from stargate_agent.main import build_agent_card

REQUIRED_EXTENSIONS = [
    ("https://stargate.example.com/ext/a2a-structured-data/v1", "structured-data"),
    ("https://stargate.example.com/ext/a2a-streaming/v1", "streaming"),
    ("https://stargate.example.com/ext/a2a-tool-protocol/v1", "tool-protocol"),
]

def test_agent_card_has_three_extensions():
    card = build_agent_card()
    extensions = card.capabilities.extensions or []
    assert len(extensions) == 3
    ext_uris = [e.uri for e in extensions]
    for uri, _ in REQUIRED_EXTENSIONS:
        assert uri in ext_uris

def test_agent_card_all_extensions_required():
    card = build_agent_card()
    for ext in card.capabilities.extensions or []:
        assert ext.required is True

def test_agent_card_streaming_enabled():
    card = build_agent_card()
    assert card.capabilities.streaming is True
```

**Step 2: 运行测试，确认失败**

```bash
cd packages/stargate-agent && uv run pytest tests/test_agent_card.py -v
# 预期: FAILED - build_agent_card 不存在
```

**Step 3: 实现 `build_agent_card()`**

```python
from a2a.types import AgentCard, AgentCapabilities, AgentExtension

A2A_PORT = 3011

def build_agent_card() -> AgentCard:
    return AgentCard(
        name="stargate-agent",
        description="Stargate A2A Agent with MCP-UI support",
        url=f"http://localhost:{A2A_PORT}",
        version="0.1.0",
        capabilities=AgentCapabilities(
            streaming=True,
            extensions=[
                AgentExtension(uri="https://stargate.example.com/ext/a2a-structured-data/v1", name="structured-data", required=True),
                AgentExtension(uri="https://stargate.example.com/ext/a2a-streaming/v1", name="streaming", required=True),
                AgentExtension(uri="https://stargate.example.com/ext/a2a-tool-protocol/v1", name="tool-protocol", required=True),
            ]
        ),
        defaultInputModes=["text/plain"],
        defaultOutputModes=["text/plain"],
        skills=[]
    )
```

**Step 4: 运行测试，确认通过**

```bash
cd packages/stargate-agent && uv run pytest tests/test_agent_card.py -v
# 预期: 3 PASSED
```

---

## Task 2：CF-Agent 扩展协商校验

**Files:**
- Create: `packages/codeflicker-agent/src/codeflicker_agent/extension_negotiation.py`
- Create: `packages/codeflicker-agent/tests/test_extension_negotiation.py`
- Modify: `packages/codeflicker-agent/src/codeflicker_agent/main.py`

**Step 1-4:** 与之前方案类似，使用 `a2a.types.AgentCard` 替代 dict

**核心代码：**

```python
from a2a.types import AgentCard, AgentExtension

REQUIRED_EXT_URIS = [...]

class ExtensionNegotiationError(Exception):
    pass

def validate_extensions(agent_card: AgentCard) -> None:
    extensions = agent_card.capabilities.extensions or []
    declared = {e.uri: e.required for e in extensions}
    for uri in REQUIRED_EXT_URIS:
        if uri not in declared or not declared[uri]:
            raise ExtensionNegotiationError(f"Missing or not required: {uri}")
```

---

## Task 3：DataPart 结构化数据传输

**Files:**
- Create: `packages/codeflicker-agent/src/codeflicker_agent/a2a_parts.py`
- Create: `packages/codeflicker-agent/tests/test_a2a_parts.py`
- Modify: CF-Agent 和 SG-Agent main.py

**核心代码：**

```python
from a2a.types import Message, DataPart, TextPart

REQUEST_SCHEMA = "https://stargate.example.com/schemas/agent-request-v1"
RESPONSE_SCHEMA = "https://stargate.example.com/schemas/agent-response-v1"

def make_agent_request_message(text: str, mode: str) -> Message:
    return Message(
        role="user",
        parts=[DataPart(data={"text": text, "mode": mode}, metadata={"schema": REQUEST_SCHEMA})]
    )

def parse_agent_response_message(message: Message) -> dict:
    for part in message.parts:
        if isinstance(part, DataPart):
            return part.data
    raise ValueError("No DataPart found in response")
```

---

## Task 4：SG-Agent SSE Streaming 服务器

**背景：** a2a-sdk 使用 `a2a.server` 架构，需要自定义 `JSONRPCHandler` 来处理 `/tasks/sendSubscribe`。

**Files:**
- Create: `packages/stargate-agent/src/stargate_agent/a2a_handler.py`
- Modify: `packages/stargate-agent/src/stargate_agent/main.py`

**核心设计：**

```python
from a2a.server.request_handlers import JSONRPCHandler
from a2a.types import Task, TaskStatusUpdateEvent, TaskArtifactUpdateEvent

class StreamingA2AHandler(JSONRPCHandler):
    async def handle_send_subscribe(self, task: Task):
        # 生成 SSE 事件流
        yield TaskStatusUpdateEvent(task_id=task.id, state="working", message="开始处理...")
        # ... 处理逻辑 ...
        yield TaskStatusUpdateEvent(task_id=task.id, state="completed", message="完成")
```

---

## Task 5：CF-Agent 接收 SSE Stream

**Files:**
- Modify: `packages/codeflicker-agent/src/codeflicker_agent/main.py`
- Modify: 前端 `App.tsx`

**核心代码：**

```python
from a2a.client import A2AClient

async def call_sg_agent_streaming(text: str, mode: str):
    client = A2AClient(SG_AGENT_A2A_URL)
    message = make_agent_request_message(text, mode)
    
    async for event in client.send_message_stream(message):
        if isinstance(event, TaskStatusUpdateEvent):
            yield {"type": "status", "state": event.state, "message": event.message}
        elif isinstance(event, TaskCompleteEvent):
            yield {"type": "complete", "result": event.result}
```

---

## Task 6：Tool-Protocol 统一工具调用

**背景：** 使用 `DataPart` 封装工具调用请求和响应。

**请求格式：**
```python
DataPart(data={
    "kind": "tool_request",
    "id": "req-001",
    "toolName": "query_employee_trend",
    "arguments": {}
})
```

**响应格式：**
```python
DataPart(data={
    "kind": "tool_response",
    "requestId": "req-001",
    "result": {...}
})
```

---

## Task 7：全量回归测试

**测试清单：**
1. 双侧 AgentCard 扩展声明正确
2. CF-Agent 能正确校验扩展
3. DataPart 传输正常，废弃 TextContent
4. SSE streaming 工作，带 span 数据
5. Tool-protocol 端到端工作
6. 废弃端点返回 404

---

## 附录：新旧 API 对照表

| 功能 | python-a2a (旧) | a2a-sdk (新) |
|------|----------------|--------------|
| AgentCard | 简单 dataclass | Pydantic 模型，支持 extensions |
| Content | TextContent, FunctionCallContent | TextPart, DataPart, FilePart |
| Message | content 字段 | parts: list[Part] |
| 服务器 | Flask + A2AServer | a2a.server + JSONRPCHandler |
| 客户端 | A2AClient | A2AClient (类似) |
| Streaming | stream_response | send_message_stream |

---

## Task 8：补充遗漏项

### 8.1 SG-Agent 双服务启动（FastAPI + A2A Server）

SG-Agent 需要同时运行 FastAPI (:3001) 和 A2A Server (:3011)，使用 threading：

```python
# packages/stargate-agent/src/stargate_agent/main.py
import threading
import uvicorn
from a2a.server.apps import A2AHTTPApp  # 需确认实际导入路径

def run_fastapi():
    uvicorn.run(fastapi_app, host="0.0.0.0", port=3001)

def run_a2a_server():
    card = build_agent_card()
    handler = StreamingA2AHandler()
    app = A2AHTTPApp(handler=handler, card=card)
    app.run(host="0.0.0.0", port=3011)

def main():
    t1 = threading.Thread(target=run_fastapi, daemon=True)
    t2 = threading.Thread(target=run_a2a_server, daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
```

### 8.2 前端 SSE 接收实现

```typescript
// packages/codeflicker-frontend/src/App.tsx
const sendMessageStream = async (text: string) => {
  const response = await fetch('/chat-stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text }),
  });
  
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    
    const chunk = decoder.decode(value);
    const lines = chunk.split('\n');
    
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = JSON.parse(line.slice(6));
        
        if (data.type === 'status') {
          updateLoading(data.message);
          // 时序图数据
          if (data.span) addSpanToDiagram(data.span);
        } else if (data.type === 'complete') {
          renderResult(data.result);
        } else if (data.type === 'error') {
          showError(data.code, data.message);
        }
      }
    }
  }
};
```

### 8.3 时序图 Span 嵌入格式

```python
# 在 StreamingA2AHandler 中
def make_status_event_with_span(task_id: str, state: str, message: str, 
                                from_svc: str, to_svc: str, operation: str) -> dict:
    span_id = f"span-{uuid.uuid4().hex[:8]}"
    return {
        "taskId": task_id,
        "state": state,
        "message": message,
        "span": {
            "id": span_id,
            "from": from_svc,
            "to": to_svc,
            "operation": operation,
            "timestamp": datetime.utcnow().isoformat(),
        }
    }

# 使用示例
yield TaskStatusUpdateEvent(
    task_id=task.id,
    state="working",
    message="正在查询 MCP...",
    metadata={
        "span": make_status_event_with_span(
            task.id, "working", "正在查询 MCP...",
            "SG-Agent", "MCP-Server", "mcp-tool-call"
        )
    }
)
```

### 8.4 废弃接口清单

| 接口 | 方法 | 替代方案 | 废弃后行为 |
|------|------|----------|-----------|
| `/chat` | POST | `/chat-stream` | 返回 410 Gone |
| `/events` | GET | A2A SSE stream | 返回 404 |
| `/tool-call` | POST | `/a2a-tool-call` | 返回 404 |
| `/tool-result` | POST/GET | 内嵌在 A2A 响应中 | 返回 404 |

### 8.5 错误码定义

```python
# packages/codeflicker-agent/src/codeflicker_agent/errors.py
from enum import IntEnum

class A2AErrorCode(IntEnum):
    """A2A Protocol Error Codes"""
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    
    # 自定义扩展错误码
    EXTENSION_NOT_SUPPORTED = -32001
    SCHEMA_VALIDATION_FAILED = -32002
    STREAMING_NOT_SUPPORTED = -32003
    TOOL_CALL_TIMEOUT = -32004
```

### 8.6 环境变量变更

```bash
# .env.example 更新
# A2A 协议配置
A2A_PROTOCOL_VERSION=0.3.0
A2A_USE_STREAMING=true

# 服务端口
CF_AGENT_PORT=3002
SG_AGENT_PORT=3001
SG_AGENT_A2A_PORT=3011
MCP_SERVER_PORT=3005

# 扩展 URI（用于协商校验）
EXT_STRUCTURED_DATA_URI=https://stargate.example.com/ext/a2a-structured-data/v1
EXT_STREAMING_URI=https://stargate.example.com/ext/a2a-streaming/v1
EXT_TOOL_PROTOCOL_URI=https://stargate.example.com/ext/a2a-tool-protocol/v1
```

### 8.7 Agent Skills 定义

```python
from a2a.types import AgentSkill

def build_agent_card() -> AgentCard:
    return AgentCard(
        name="stargate-agent",
        description="Stargate A2A Agent with MCP-UI support",
        url=f"http://localhost:{A2A_PORT}",
        version="0.1.0",
        capabilities=AgentCapabilities(...),
        skills=[
            AgentSkill(
                id="query_employee_trend",
                name="Query Employee Trend",
                description="Query Kuaishou employee trend data over years",
                tags=["employee", "trend", "data"],
                examples=["查询快手历年员工人数趋势", "快手员工变化"],
            ),
            AgentSkill(
                id="query_employee_trend_lazy",
                name="Query Employee Trend (Lazy)",
                description="Lazy loading version of employee trend query",
                tags=["employee", "trend", "lazy"],
                examples=["懒加载查询员工趋势"],
            ),
        ],
        defaultInputModes=["text/plain"],
        defaultOutputModes=["text/plain", "application/json"],
    )
```

### 8.8 数据迁移与兼容性

**⚠️ 重要：此升级不兼容旧协议**

- **CF-Agent 和 SG-Agent 必须同时升级**，否则 A2A 通信会失败
- **升级前备份：**
  ```bash
  cp -r packages/codeflicker-agent packages/codeflicker-agent.backup
  cp -r packages/stargate-agent packages/stargate-agent.backup
  ```
- **升级顺序：**
  1. 停止所有服务
  2. 双侧代码更新
  3. 双侧依赖重装
  4. 同时启动双侧服务
  5. 端到端测试

### 8.9 扩展规范文档引用

```python
# 在扩展规范文档中定义 schema
# ext-a2a-structured-data/spec.md

SCHEMA_AGENT_REQUEST = """
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["text", "mode"],
  "properties": {
    "text": { "type": "string", "description": "User query text" },
    "mode": { 
      "type": "string", 
      "enum": ["endpoint", "mcp"],
      "description": "Rendering mode"
    }
  }
}
"""
```

### 8.10 测试命令

```bash
# 1. 单侧单元测试
cd packages/stargate-agent && uv run pytest tests/ -v -k "test_agent_card"
cd packages/codeflicker-agent && uv run pytest tests/ -v -k "test_extension"

# 2. 集成测试（需双侧服务启动）
# 启动 SG-Agent
cd packages/stargate-agent && uv run python -m stargate_agent.main &
# 启动 CF-Agent
cd packages/codeflicker-agent && uv run python -m codeflicker_agent.main &
# 运行集成测试
cd packages/codeflicker-agent && uv run pytest tests/integration/ -v

# 3. 端到端测试（手动）
# 打开 http://localhost:3000，发送消息验证完整链路
```

### 8.11 回滚方案

```bash
#!/bin/bash
# rollback.sh

echo "Rolling back to python-a2a..."

# 停止服务
pkill -f stargate_agent
pkill -f codeflicker_agent

# 恢复备份
rm -rf packages/codeflicker-agent
rm -rf packages/stargate-agent
mv packages/codeflicker-agent.backup packages/codeflicker-agent
mv packages/stargate-agent.backup packages/stargate-agent

# 重装依赖
cd packages/codeflicker-agent && uv sync
cd packages/stargate-agent && uv sync

echo "Rollback complete. Restart services manually."
```

### 8.12 日志与调试

```python
# 配置 a2a-sdk 日志
import logging
from a2a import logger as a2a_logger

a2a_logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
a2a_logger.addHandler(handler)

# CF-Agent 侧日志
def log_a2a_request(message: Message):
    logger.info(f"A2A Request: {message.model_dump_json()}")

def log_a2a_response(response: Message):
    logger.info(f"A2A Response: {response.model_dump_json()}")
```

---

**注意：** 由于 a2a-sdk 服务器文档较少，Task 4 的具体实现可能需要参考 SDK 源码和示例进行调整。建议先实现最小可行版本（MVP），验证基础链路后再完善高级功能。
