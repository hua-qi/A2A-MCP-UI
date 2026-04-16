# MCP-UI × A2A 架构理解指南

本文档面向希望深入理解本项目架构的读者，重点说明 MCP-UI 与 A2A 协议各自的角色、各模块关键代码，以及它们如何有机结合。

---

## 一、整体系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     CF-Frontend（浏览器）                    │
│                                                             │
│   App  ──→  ChatMessage  ──→  CardMessage                   │
│                                   │                         │
│                               AppRenderer (@mcp-ui/client)  │
│                                   │                         │
│                            sandbox_proxy.html               │
│                                   │                         │
│                          [iframe] 卡片 HTML                  │
│                    (Module Federation 动态加载)              │
└────────────────────────┬────────────────────────────────────┘
                         │  HTTP（Vite proxy）
                         ▼
┌────────────────────────────────────────────────────────────┐
│                    CF-Agent（Python FastAPI）               │
│                                                            │
│  POST /chat  ──→  LLM 意图识别  ──→  A2A 调用 SG-Agent    │
│  GET  /events  SSE 事件流                                  │
│  GET  /resource-proxy  代理 MCP 资源读取                   │
└────────────────────────┬───────────────────────────────────┘
                         │  A2A 协议（HTTP JSON-RPC）
                         ▼
┌────────────────────────────────────────────────────────────┐
│               SG-Agent（Python FastAPI + Flask）           │
│                                                            │
│  Flask:3011  A2A Server  ──→  LLM 工具选择                │
│  FastAPI:3001  REST API  ──→  card_cache / 业务 API        │
│                                                            │
│  endpoint 模式：查 ResourceCenter → 生成 cardInstanceId    │
│  mcp 模式：调用 MCP-Server → 获取 resourceUri             │
└──────┬─────────────────────────────────────────────────────┘
       │  MCP 协议（SSE）           │  HTTP
       ▼                            ▼
┌──────────────┐           ┌────────────────────┐
│  MCP-Server  │           │   ResourceCenter   │
│  :3005       │           │   :3003            │
│  (FastMCP)   │           │   (组件索引)        │
└──────────────┘           └────────────────────┘
                                    │
                    ┌───────────────┘
                    ▼
           ┌─────────────────────┐
           │  employee-chart-card │
           │  :3004 remoteEntry   │
           │  (Module Federation) │
           └─────────────────────┘
```

---

## 二、各系统关键代码及作用

### 2.1 CF-Agent（`packages/codeflicker-agent`）

| 文件 | 关键代码 | 作用 |
|---|---|---|
| `main.py` | `POST /chat` | 接收前端消息，调 LLM 识别意图，再 A2A 调用 SG-Agent |
| `main.py` | `_call_sg_agent()` | 封装 A2A 调用，解析响应中的 `mcp_ui_resource` part |
| `main.py` | `GET /events` | SSE 长连接，向前端推送调用链事件日志 |
| `main.py` | `GET /resource-proxy` | 代理前端对 `ui://stargate/...` 资源的读取请求 |
| `main.py` | `POST /tool-call` | 接收卡片内 `tools/call` postMessage，转发给 SG-Agent |
| `llm.py` | `detect_intent()` | 调用 OpenAI 判断用户意图：`query_data` vs `general_chat` |
| `sse_logger.py` | `emit()` / `subscribe()` | 维护 SSE 广播队列，记录每个调用链节点 |

**核心逻辑 `_call_sg_agent`：**

```python
def _call_sg_agent(user_text: str, mode: str) -> list:
    payload = json.dumps({"text": user_text, "mode": mode})
    client = A2AClient(endpoint_url=SG_AGENT_A2A_URL)
    response_msg = client.send_message(Message(content=TextContent(text=payload), role=MessageRole.USER))

    parts = []
    data = json.loads(response_msg.content.text)
    if "text" in data:
        parts.append({"kind": "text", "text": data["text"]})
    if "mcp_ui_resource" in data:
        parts.append(data["mcp_ui_resource"])   # 透传，不做额外处理
    return parts
```

---

### 2.2 SG-Agent（`packages/stargate-agent`）

| 文件 | 关键代码 | 作用 |
|---|---|---|
| `main.py` | `StargateA2AServer.handle_message()` | A2A 消息处理核心：LLM 选工具 → 查业务数据 → 组装响应 |
| `main.py` | `GET /api/card-instance/{id}` | 前端凭 cardInstanceId 换取卡片三元组（componentName + remoteEntryUrl + props） |
| `main.py` | `POST /api/token/exchange` | 换取 Stargate Token（mock） |
| `main.py` | `GET /mcp/resources/read` | 代理 MCP 资源读取，对外暴露 `ui://stargate/...` URI |
| `card_cache.py` | `put()` / `get()` | 内存缓存 CardInstance，TTL 3600s，返回 UUID 作为 cardInstanceId |
| `llm.py` | `select_tool()` | LLM 根据用户文本选择工具名 |
| `shell_builder.py` | `MCP_INIT_SCRIPT` | 注入 iframe 的 MF 初始化脚本，共享 React singleton |

**endpoint 模式下的 handle_message 核心流程：**

```python
# 1. LLM 选工具
tool_name, _ = _run_async(llm.select_tool(user_text))

# 2. 查资源中心获取组件信息
component_info = _run_async(_fetch_component_info())
# → { componentName, containerName, remoteEntryUrl }

# 3. 查业务数据
trend_resp = _run_async(_fetch_employee_trend())

# 4. 存入 card_cache，生成 cardInstanceId
card_id = card_cache.put(
    component_name=component_info["componentName"],
    container_name=component_info["containerName"],
    remote_entry_url=component_info["remoteEntryUrl"],
    props={"data": trend_resp["data"]},
)

# 5. 返回 A2A 响应，携带 mcp_ui_resource
response_data = {
    "text": "已为您查询快手历年员工趋势数据，共 5 年记录。",
    "mcp_ui_resource": {
        "kind": "mcp_ui_resource",
        "resourceUri": f"ui://stargate/card/{card_id}",
        "toolResult": {...},
        "uiMetadata": {"preferred-frame-size": {"width": 560, "height": 420}},
    },
}
```

---

### 2.3 MCP-Server（`packages/stargate-mcp-ui-server`）

| 文件 | 关键代码 | 作用 |
|---|---|---|
| `main.py` | `@mcp.tool() query_employee_trend` | 注册 MCP 工具，返回值携带 `_meta.ui.resourceUri` |
| `main.py` | `@mcp.resource(RESOURCE_URI)` | 注册 `ui://stargate/employee-trend` 资源，返回卡片 HTML |
| `tools.py` | `get_ui_resource()` | 用 `@mcp-ui/server` 的 `createUIResource` 生成 MCP-UI 资源对象 |

MCP 模式下，SG-Agent 通过 `ClientSession.call_tool()` 调用此服务，从响应的 `_meta.ui.resourceUri` 中获取 `ui://` URI。

---

### 2.4 CF-Frontend（`packages/codeflicker-frontend`）

| 文件 | 关键代码 | 作用 |
|---|---|---|
| `App.tsx` | `sendMessage()` | POST `/chat` 发送消息，将响应 parts 映射为 React state |
| `App.tsx` | `useEventLog()` | 订阅 SSE 事件流，驱动时序图渲染 |
| `ChatMessage.tsx` | part 路由 | 根据 `part.kind` 决定渲染文本还是 `CardMessage` |
| `CardMessage.tsx` | `<AppRenderer>` | MCP-UI 核心渲染组件，驱动 sandbox_proxy → iframe 卡片 |
| `sandbox_proxy.html` | postMessage 中转 | 沙箱代理，在 Host 和卡片 iframe 之间中转所有 JSON-RPC 消息 |
| `vite.config.ts` | `proxy` | 将 `/chat`、`/resource-proxy` 等转发到 CF-Agent:3002 |

---

### 2.5 employee-chart-card（`packages/employee-chart-card`）

| 文件 | 关键代码 | 作用 |
|---|---|---|
| `webpack.config.js` | `ModuleFederationPlugin` | 将组件打包为 MF remote，暴露 `./EmployeeChart`、`./EmployeeChartLazy` |
| `EmployeeChart.tsx` | `window.addEventListener('message')` | 监听 `ui/notifications/tool-result`，接收 toolResult 数据更新图表 |
| `EmployeeChart.tsx` | `handleAnalyze()` | postMessage `ui/message`，触发新一轮 Agent 对话 |
| `EmployeeChart.tsx` | `handleRefresh()` | postMessage `tools/call`，让 Host 重新调用工具并将结果推回 |
| `EmployeeChart.tsx` | `handleHoverYear()` | 直接携带 Stargate Token 调用业务 API，无需经过 Agent |

---

## 三、CF-Agent 与 CF-Frontend 的通信

CF-Frontend 运行在浏览器，CF-Agent 是 Python FastAPI 服务（:3002）。两者通过 **HTTP + SSE** 通信，Vite dev server 做反向代理消除跨域。

### 3.1 请求/响应通道（HTTP）

```
用户输入 → App.tsx sendMessage()
    │
    ▼  POST /chat  { message: "查询快手员工趋势" }
CF-Agent
    │
    ▼  JSON  { parts: [ {kind:"text",...}, {kind:"mcp_ui_resource",...} ] }
App.tsx → setMessages() → 渲染 ChatMessage
```

所有接口均通过 Vite proxy 转发，前端无需关心端口：

```ts
// vite.config.ts
proxy: {
  '/chat':           'http://localhost:3002',
  '/resource-proxy': 'http://localhost:3002',
  '/tool-call':      'http://localhost:3002',
  '/mode':           'http://localhost:3002',
}
```

### 3.2 事件日志通道（SSE）

```
CF-Agent GET /events  ─────────────────────────────┐
SG-Agent GET /events  ──────────────────────────────┤
                                                    ▼
                                         useEventLog.ts (EventSource)
                                                    │
                                                    ▼
                                         SequenceDiagram.tsx 渲染时序图
```

`sse_logger.emit(source, target, type, detail)` 在调用链的每个节点发射事件，前端 `useEventLog` hook 订阅两个 SSE 端点并合并，驱动时序图实时更新。

### 3.3 卡片交互通道（HTTP，由 AppRenderer 发起）

卡片内部的 `tools/call` 和 `ui/message` postMessage 被 `AppRenderer` 捕获后，转换为对 CF-Agent 的 HTTP 调用：

```
卡片 iframe  →  postMessage tools/call
    │
AppRenderer 捕获
    │
    ▼  POST /tool-call  { toolName, arguments }
CF-Agent → SG-Agent（A2A）→ 返回 toolResult
    │
    ▼  JSON  { toolResult: {...} }
AppRenderer → postMessage ui/notifications/tool-result → 卡片 iframe
```

---

## 四、CF-Frontend 内部各层通信

```
App.tsx
  └── ChatMessage.tsx
        └── CardMessage.tsx
              └── AppRenderer（@mcp-ui/client）
                    │  创建 <iframe src="sandbox_proxy.html">
                    ▼
              sandbox_proxy.html（中间层 iframe，同源）
                    │  创建 <iframe srcdoc="卡片 HTML" sandbox="...">
                    ▼
              卡片 iframe（独立沙箱，运行 MF 加载的组件）
```

### 4.1 App 层 → CardMessage

`App.tsx` 的 `sendMessage()` 收到响应后，将 `parts` 存入 state。`ChatMessage` 遍历 parts，当 `part.kind === 'mcp_ui_resource'` 时渲染 `CardMessage`，并将 `onMessage`（触发新对话）和 `onLayout`（滚动到底）回调传下去。

### 4.2 CardMessage → AppRenderer

`CardMessage` 是 MCP-UI 与业务逻辑的连接点：

```tsx
<AppRenderer
  toolName={toolName}
  toolResult={toolResult}          // 初始数据，随 tool-result 注入卡片
  sandbox={{ url: sandboxUrl }}    // 指向 /sandbox_proxy.html
  toolResourceUri={resourceUri}    // ui://stargate/card/{cardInstanceId}
  onReadResource={async ({uri}) => {
    const res = await fetch(`/resource-proxy?uri=${encodeURIComponent(uri)}`);
    return res.json();             // CF-Agent 代理读取 SG-Agent MCP 资源
  }}
  onCallTool={handleCallTool}      // 卡片调用 tools/call → POST /tool-call
  onSizeChanged={({height}) => setIframeHeight(height)}
  onMessage={async (params) => {
    onMessage(params.content[0].text);  // 触发 App 层新一轮对话
  }}
/>
```

`AppRenderer` 完成以下工作：
1. 调用 `onReadResource` 拉取卡片 HTML（CF-Agent 代理 → SG-Agent → MCP-Server）
2. 向 sandbox_proxy iframe 发送 `ui/notifications/sandbox-resource-ready`，携带 HTML
3. 向卡片 iframe 推送 `ui/notifications/tool-result`，注入 toolResult 初始数据
4. 监听来自 sandbox_proxy 的上行消息（`tools/call`、`ui/message`、`size-changed`）

### 4.3 AppRenderer → sandbox_proxy.html

**为什么需要 sandbox_proxy？**

`AppRenderer` 所在页面（`:3000`）与卡片 iframe（`blob:` URL）不同源，直接通信受浏览器安全限制。`sandbox_proxy.html` 作为**同源中间层**，放宽了通信限制，充当透明转发代理。

```
AppRenderer
  │
  │  postMessage → (sandbox_proxy iframe, 同源)
  ▼
sandbox_proxy.html
  │
  │  监听 ui/notifications/sandbox-resource-ready
  │  → 创建内层 <iframe srcdoc="卡片HTML" sandbox="allow-scripts allow-same-origin allow-forms allow-popups">
  │
  │  上行（卡片 → Host）：e.source === appIframe.contentWindow → window.parent.postMessage
  │  下行（Host → 卡片）：e.source === window.parent → appIframe.contentWindow.postMessage
  ▼
卡片 iframe（隔离沙箱）
```

sandbox_proxy 的核心转发逻辑：

```js
window.addEventListener('message', function(e) {
  // 收到来自 Host(AppRenderer) 的消息 → 转发给卡片
  if (e.source === window.parent && appIframe) {
    appIframe.contentWindow.postMessage(msg, '*');
    return;
  }
  // 收到来自卡片的消息 → 转发给 Host
  if (appIframe && e.source === appIframe.contentWindow) {
    window.parent.postMessage(msg, '*');
    return;
  }
});
```

### 4.4 sandbox_proxy.html → 卡片 iframe（MF 组件）

卡片 HTML 由 SG-Agent 动态生成，内嵌 Module Federation 初始化脚本：

1. **加载 remoteEntry.js**（来自 `employee-chart-card` webpack-dev-server）
2. **共享 React singleton**：手动构造 shareScope，将 Host 的 React/ReactDOM 注入 MF 容器，避免多 React 实例
3. **渲染组件**：`container.get('./EmployeeChart')` → `factory().default` → `ReactDOM.createRoot(...).render(...)`

```js
// shell_builder.py 生成的 HTML 中的关键脚本（简化）
shareScope['default']['react'] = {
  '18.3.1': { get: () => () => React, loaded: 1, from: 'host' }
};
employeeChartCard.init(shareScope['default']);
const factory = await employeeChartCard.get('./EmployeeChart');
const Comp = factory().default;
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(Comp, {}));
```

### 4.5 卡片 → Host 的上行通信

卡片内使用标准 postMessage 协议（JSON-RPC 2.0）与 Host 通信：

| postMessage 方法 | 触发时机 | Host 处理 |
|---|---|---|
| `ui/notifications/size-changed` | 组件渲染完成/高度变化 | AppRenderer → `onSizeChanged` → CardMessage 动态调整 iframe 高度 |
| `tools/call` | 用户点击"刷新数据" | AppRenderer → `onCallTool` → POST `/tool-call` → 返回新 toolResult，再 postMessage 回卡片 |
| `ui/message` | 用户点击"分析趋势" | AppRenderer → `onMessage` → App 层 `sendMessage()` 触发新一轮 Agent 对话 |

---

## 五、A2A 协议结构举例

### 5.1 A2A 核心对象速览

A2A 基于 HTTP JSON-RPC 2.0，所有请求均 `POST <agentUrl>`。核心数据结构：

```
AgentCard   Agent 的"身份证"，托管在 /.well-known/agent-card.json，描述能力、认证方案、技能列表
Message     单轮通信单元，role=user|agent，包含 parts[]
Part        内容最小单元：text / raw(Base64) / url / data(JSON 对象)，可附 mediaType、metadata
Task        有状态工作单元，state: submitted→working→completed|failed|input-required
Artifact    任务产出物，包含 parts[]
```

**SG-Agent 的 AgentCard（`/.well-known/agent-card.json`）：**

```json
{
  "name": "stargate-agent",
  "description": "Stargate A2A Agent with MCP-UI support",
  "url": "http://localhost:3011",
  "version": "0.1.0",
  "capabilities": {
    "streaming": false,
    "pushNotifications": false
  },
  "skills": [
    {
      "id": "query-employee-trend",
      "name": "查询员工趋势",
      "description": "查询快手历年员工人数趋势，返回可渲染的图表卡片",
      "tags": ["hr", "data", "chart"],
      "inputModes": ["text"],
      "outputModes": ["text", "data"]
    }
  ]
}
```

---

### 5.2 CF-Agent → SG-Agent 请求

CF-Agent 使用 `python_a2a` 库向 SG-Agent（`:3011`）发送标准 A2A 消息：

```json
POST http://localhost:3011/message
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": "req-001",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "messageId": "msg-001",
      "contextId": "ctx-session-abc",
      "parts": [
        {
          "text": "{\"text\": \"查询快手历年员工人数趋势\", \"mode\": \"endpoint\"}"
        }
      ]
    }
  }
}
```

> `text` part 内嵌 JSON 字符串，是本项目对 A2A 的**最小化扩展**：`mode` 字段控制 SG-Agent 走 endpoint 模式（查 ResourceCenter + card_cache）还是 mcp 模式（调用 MCP-Server）。

---

### 5.3 SG-Agent → CF-Agent 响应（endpoint 模式）

SG-Agent 处理完成后，通过标准 A2A 双 part 结构返回。这是 MCP-UI 协议进入 A2A 链路的**注入点**：

```json
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "result": {
    "message": {
      "role": "agent",
      "messageId": "msg-002",
      "contextId": "ctx-session-abc",
      "parts": [
        {
          "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"
        },
        {
          "data": {
            "kind": "mcp_ui_resource",
            "resourceUri": "ui://stargate/card/550e8400-e29b-41d4-a716-446655440000",
            "toolName": "query_employee_trend",
            "toolResult": {
              "content": [{ "type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。" }],
              "data": [
                { "year": 2019, "count": 7000 },
                { "year": 2020, "count": 10000 },
                { "year": 2021, "count": 16000 },
                { "year": 2022, "count": 22000 },
                { "year": 2023, "count": 18000 }
              ],
              "token": "mock-stargate-token-12345"
            },
            "uiMetadata": { "preferred-frame-size": { "width": 560, "height": 420 } }
          },
          "mediaType": "application/json",
          "metadata": { "extension": "https://stargate.example.com/ext/mcp-ui-resource/v1" }
        }
      ]
    }
  }
}
```

CF-Agent 遍历 `parts[]`，按字段类型路由后返回给前端：

```json
{
  "parts": [
    {
      "kind": "text",
      "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"
    },
    {
      "kind": "mcp_ui_resource",
      "resourceUri": "ui://stargate/card/550e8400-e29b-41d4-a716-446655440000",
      "toolName": "query_employee_trend",
      "toolResult": {
        "content": [{ "type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。" }],
        "data": [
          { "year": 2019, "count": 7000 },
          { "year": 2020, "count": 10000 },
          { "year": 2021, "count": 16000 },
          { "year": 2022, "count": 22000 },
          { "year": 2023, "count": 18000 }
        ],
        "token": "mock-stargate-token-12345"
      },
      "uiMetadata": {
        "preferred-frame-size": { "width": 560, "height": 420 }
      }
    }
  ]
}
```

---

### 5.4 SG-Agent → CF-Agent 响应（mcp 模式）

mcp 模式下，SG-Agent 先通过 MCP SSE 协议调用 MCP-Server：

```
SG-Agent  →  MCP ClientSession.call_tool("query_employee_trend")
             ↓
         MCP-Server 返回：
         {
           "_meta": { "ui": { "resourceUri": "ui://stargate/employee-trend" } },
           "content": [{ "type": "text", "text": "..." }],
           "resource": { "uri": "...", "mimeType": "text/html;profile=mcp-app", "text": "<html>...</html>" }
         }
```

A2A 响应结构与 endpoint 模式相同，仅 `resourceUri` 不同——指向 MCP-Server 注册的固定资源而非 cardInstanceId：

```json
"resourceUri": "ui://stargate/employee-trend"
```

---

### 5.5 MCP-UI 协议的完整链路举例

以下展示 **endpoint 模式**下，从用户发消息到卡片渲染完成的完整协议交互链路：

```
① 用户输入 → App.tsx
   POST /chat  { "message": "查询快手历年员工人数趋势" }

② CF-Agent：LLM 意图识别 → "query_data"
   A2A  POST http://localhost:3011/message
   Header: A2A-Extensions: https://stargate.example.com/ext/mcp-ui-resource/v1
   {
     "method": "message/send",
     "params": {
       "message": {
         "role": "user",
         "parts": [{ "text": "{\"text\": \"查询快手历年员工人数趋势\", \"mode\": \"endpoint\"}" }]
       }
     }
   }

③ SG-Agent：LLM 选工具 → "query_employee_trend"
   HTTP GET http://localhost:3003/api/components/EmployeeChart
   → { "componentName": "EmployeeChart", "containerName": "employeeChartCard",
       "remoteEntryUrl": "http://localhost:3004/remoteEntry.js" }

   HTTP GET http://localhost:3001/api/employee/trend
   → { "data": [...], "token": "mock-stargate-token-12345" }

   card_cache.put(...)  → cardInstanceId = "550e8400-..."

   A2A 响应（双 part，回显 Header）：
   Header: A2A-Extensions: https://stargate.example.com/ext/mcp-ui-resource/v1
   {
     "parts": [
       { "text": "已为您查询快手历年员工趋势数据，共 5 年记录。" },
       {
         "data": { "kind": "mcp_ui_resource", "resourceUri": "ui://stargate/card/550e8400-..." },
         "mediaType": "application/json",
         "metadata": { "extension": "https://stargate.example.com/ext/mcp-ui-resource/v1" }
       }
     ]
   }

④ CF-Agent 透传 → /chat HTTP 响应
   { "parts": [ {kind:"text",...}, {kind:"mcp_ui_resource", resourceUri:"ui://stargate/card/550e8400-..."} ] }

⑤ CF-Frontend：ChatMessage → CardMessage → AppRenderer
   AppRenderer.onReadResource({ uri: "ui://stargate/card/550e8400-..." })
   → GET /resource-proxy?uri=ui%3A%2F%2Fstargate%2Fcard%2F550e8400-...
   → CF-Agent 代理 GET http://localhost:3001/mcp/resources/read?uri=ui://stargate/card/550e8400-...
   → SG-Agent 从 card_cache 取出实例，动态生成卡片 HTML（含 MF 初始化脚本）
   → 返回 MCP-UI UIResource：
     {
       "contents": [{
         "uri": "ui://stargate/card/550e8400-...",
         "mimeType": "text/html;profile=mcp-app",
         "text": "<!DOCTYPE html>...<script src='http://localhost:3004/remoteEntry.js'>...</script>"
       }]
     }

⑥ AppRenderer → sandbox_proxy.html
   postMessage:
   {
     "jsonrpc": "2.0",
     "method": "ui/notifications/sandbox-resource-ready",
     "params": { "html": "<!DOCTYPE html>..." }
   }

⑦ sandbox_proxy 创建卡片 iframe（srcdoc + sandbox 属性）
   卡片 HTML 执行：加载 remoteEntry.js → MF 初始化共享 React → 渲染 EmployeeChart 组件

⑧ AppRenderer → 卡片 iframe（经 sandbox_proxy 中转）
   postMessage:
   {
     "jsonrpc": "2.0",
     "method": "ui/notifications/tool-result",
     "params": {
       "result": {
         "data": [{"year":2019,"count":7000}, ...],
         "token": "mock-stargate-token-12345"
       }
     }
   }
   EmployeeChart 接收后 setState，echarts 渲染折线图

⑨ 卡片渲染完成 → 卡片 iframe → sandbox_proxy → AppRenderer
   postMessage:
   {
     "jsonrpc": "2.0",
     "method": "ui/notifications/size-changed",
     "params": { "height": 380 }
   }
   CardMessage.setIframeHeight(380) → iframe 展开显示
```

**用户点击"刷新数据"时的交互链路：**

```
卡片 iframe → sandbox_proxy → AppRenderer
postMessage:
{
  "jsonrpc": "2.0",
  "id": 1712345678901,
  "method": "tools/call",
  "params": { "name": "query_employee_trend", "arguments": {} }
}

AppRenderer.onCallTool({ name: "query_employee_trend", arguments: {} })
→ POST /tool-call  { "toolName": "query_employee_trend", "arguments": {} }
→ CF-Agent → A2A → SG-Agent → 返回新 toolResult

AppRenderer → sandbox_proxy → 卡片 iframe
postMessage:
{
  "jsonrpc": "2.0",
  "id": 1712345678901,
  "result": { "data": [...], "token": "..." }
}
EmployeeChart 更新图表数据
```

**用户点击"分析趋势"时的交互链路：**

```
卡片 iframe → sandbox_proxy → AppRenderer
postMessage:
{
  "jsonrpc": "2.0",
  "method": "ui/message",
  "params": {
    "role": "user",
    "content": [{ "type": "text", "text": "分析以下员工趋势数据：[...]" }]
  }
}

AppRenderer.onMessage → CardMessage.onMessage → App.sendMessage()
→ 触发新一轮完整链路（从步骤①重新开始）
```

---

### 5.6 协议扩展说明

本项目将 `mcp_ui_resource` 实现为标准 A2A `data` part，与 MCP-UI 字段的对应关系如下：

| A2A data part 字段 | 本项目用法 |
|---|---|
| `data.kind` | 固定值 `"mcp_ui_resource"`，用于客户端路由识别 |
| `data.resourceUri` | 对齐 MCP-UI 的 `ui://` URI 规范 |
| `data.toolResult` | 对应 MCP-UI `AppRenderer` 的 `toolResult` prop |
| `data.uiMetadata` | 对应 MCP-UI `createUIResource` 的 `uiMetadata` 参数 |
| `mediaType` | 固定值 `"application/json"` |
| `metadata.extension` | 声明所属扩展 URI，便于多扩展共存时路由 |

---

### 5.7 扩展规范文档与 A2A 治理规范映射

本项目将 `mcp_ui_resource` 定义为正式 A2A 扩展，规范文档位于：
`ext-mcp-ui-resource/spec.md`

| A2A 治理要求 | 本项目做法 |
|---|---|
| URI 唯一标识 | `https://stargate.example.com/ext/mcp-ui-resource/v1` |
| 规范托管在 URI | `ext-mcp-ui-resource/spec.md`（生产环境应部署到对应域名） |
| AgentCard 声明 | `capabilities.extensions[]` 中声明 uri、description、required |
| 激活协商 | 请求带 `A2A-Extensions` Header，响应回显已激活 URI |
| Breaking change 换 URI | 字段变更升级到 `/v2`，不允许原地修改 |
| `required: false` | 不支持扩展的客户端降级为纯文本，不影响基础调用 |

---

## 六、MCP-UI 与 A2A 的有机结合

| 层次 | 协议 | 解决的问题 |
|---|---|---|
| Agent 间通信 | **A2A** | CF-Agent 与 SG-Agent 跨进程、标准化协作，SG-Agent 不暴露内部实现 |
| 工具→UI 绑定 | **MCP-UI** | SG-Agent 返回的不只是数据，而是携带 `ui://` URI 的可渲染 UI 资源 |
| 资源读取 | **MCP protocol** | CF-Frontend 通过 CF-Agent 代理，用标准 MCP resources/read 协议拉取卡片 HTML |
| 卡片渲染 | **Module Federation** | 卡片组件独立部署，运行时动态加载，与主应用共享 React 实例 |
| 卡片↔Host 通信 | **postMessage（JSON-RPC 2.0）** | MCP Apps 规范定义的 iframe 通信协议，支持 tools/call、ui/message 等语义 |

**关键结合点**：`resourceUri`（`ui://stargate/card/{cardInstanceId}`）是连接 A2A 和 MCP-UI 的**语义锚点**。SG-Agent 通过 A2A 响应传递这个 URI，CF-Frontend 通过 `AppRenderer.onReadResource` 回调解析它，最终触发 MF 组件的加载和渲染。整个链路中，A2A 负责"谁来干"，MCP-UI 负责"怎么展示"，两者通过 `ui://` URI 解耦。
