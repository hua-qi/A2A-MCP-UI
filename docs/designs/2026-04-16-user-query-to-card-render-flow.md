# 用户提问到卡片渲染完整流程

**Date:** 2026-04-16

---

## 概述

本文档详细描述了从用户在 CF-Frontend 输入问题，到最终渲染出 MCP-UI 卡片的完整流程。包含服务间通信、组件间交互、协议转换等所有关键环节。

---

## 流程总览

```
用户输入
    ↓
CF-Frontend (React) ──SSE──> CF-Agent (Python)
    ↑                              ↓
显示卡片/文本                  A2A 协议
    ↑                              ↓
Module Federation <────────── SG-Agent (Python)
    ↑                              ↓
EmployeeChart 渲染           生成 HTML
    ↑                              ↓
ECharts 图表 <────────────── Shell Builder
```

---

## 详细流程（17个步骤）

### 阶段一：用户输入 → CF-Agent 处理

#### ① 用户触发发送

**位置**: `packages/codeflicker-frontend/src/App.tsx:68`

```typescript
const sendMessage = async (text?: string) => {
  const finalText = (text ?? input).trim();
  if (!finalText || loading) return;
  setInput('');
  setLoading(true);
  // 创建用户消息并显示在聊天列表
  const userMsg: ChatMessageType = {
    id: newId(),
    role: 'user',
    parts: [{ kind: 'text', text: finalText }],
  };
  setMessages((prev) => [...prev, userMsg]);
```

**行为**: 
- 用户在前端输入框输入文字（如"查询快手历年员工人数趋势"）
- 点击发送按钮或按 Enter
- 创建用户消息对象，立即显示在聊天界面

---

#### ② 发起 SSE 流式请求

**位置**: `packages/codeflicker-frontend/src/App.tsx:82`

```typescript
const response = await fetch('/chat-stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ message: finalText, mode }),
  signal: abortControllerRef.current.signal,
});
```

**请求内容**:
```json
{
  "message": "查询快手历年员工人数趋势",
  "mode": "endpoint"  // 或 "mcp"
}
```

**行为**: 前端向 CF-Agent :3002 发起 POST 请求，建立 SSE 流式连接

---

#### ③ CF-Agent 处理请求

**位置**: `packages/codeflicker-agent/src/codeflicker_agent/main.py:75`

```python
@app.post("/chat-stream")
async def chat_stream(request: Request):
    body = await request.json()
    user_message: str = body.get("message", "")
    mode: str = body.get("mode", current_mode)
```

**处理步骤**:
1. **扩展协商验证** (`validate_sg_extensions()`): 检查 SG-Agent 是否支持必需的 A2A 扩展
2. **LLM 意图识别** (`llm.detect_intent()`): 判断是 `query_data` 还是 `general_chat`
3. **A2A 流式调用**: 如果是数据查询，调用 SG-Agent

---

### 阶段二：A2A 协议通信（CF-Agent ↔ SG-Agent）

#### ④ CF-Agent 构造 A2A 请求

**位置**: `packages/codeflicker-agent/src/codeflicker_agent/a2a_stream_client.py:26`

```python
message = make_agent_request_message(text, mode)

request_payload = {
    "jsonrpc": "2.0",
    "id": str(uuid.uuid4()),
    "method": "message/stream",
    "params": {
        "message": message_dict,
        "metadata": {}
    }
}
```

**生成的消息结构**:
```json
{
  "messageId": "uuid",
  "role": "user",
  "parts": [{
    "kind": "data",
    "data": {
      "text": "查询快手历年员工人数趋势",
      "mode": "endpoint"
    }
  }]
}
```

---

#### ⑤ SG-Agent A2A Server 接收请求

**位置**: SG-Agent 的 A2A Server (:3011)

**处理流程**:
1. a2a-sdk 接收 JSON-RPC 请求
2. `AgentExecutor` 路由到 `StargateAgentExecutor`
3. 解析 `message.parts` 中的 `DataPart`

---

#### ⑥ SG-Agent 执行器处理

**位置**: `packages/stargate-agent/src/stargate_agent/a2a_executor.py:25`

```python
async def execute(self, context: RequestContext, event_queue: EventQueue):
    # 1. 发送初始状态
    await event_queue.enqueue_event(
        self._create_status_event(task_id, context_id, TaskState.working, "收到请求，开始处理...")
    )
    
    # 2. 解析请求
    request_data = self._parse_request(message)
    
    # 3. LLM 工具选择
    tool_name, tool_args = await llm.select_tool(user_text)
    
    # 4. 发送工具识别状态
    await event_queue.enqueue_event(
        self._create_status_event(task_id, context_id, TaskState.working, f"执行工具: {tool_name}...")
    )
```

**状态更新事件流**:
- "收到请求，开始处理..."
- "正在识别工具..."
- "执行工具: query_employee_trend..."

---

#### ⑦ 工具执行 & UI 资源组装

**位置**: `packages/stargate-agent/src/stargate_agent/a2a_executor.py:189`

```python
async def _handle_employee_trend(self, mode: str) -> dict:
    return {
        "text": "已为您查询快手历年员工趋势数据，共 5 年记录。",
        "mcp_ui_resource": {
            "kind": "mcp_ui_resource",
            "resourceUri": "ui://stargate/employee-trend",
            "toolName": "query_employee_trend",
            "toolResult": {
                "data": [
                    {"year": 2019, "count": 7000},
                    {"year": 2020, "count": 10000},
                    {"year": 2021, "count": 16000},
                    {"year": 2022, "count": 22000},
                    {"year": 2023, "count": 18000},
                ],
                "token": "mock-stargate-token-12345",
            },
            "uiMetadata": {
                "preferred-frame-size": {"width": 560, "height": 420}
            }
        }
    }
```

**返回内容**:
1. **TextPart**: 纯文本回复
2. **DataPart**: 包含 `mcp_ui_resource` 数据，这是 MCP-UI 协议的核心

---

#### ⑧ CF-Agent 接收并转换事件

**位置**: `packages/codeflicker-agent/src/codeflicker_agent/a2a_stream_client.py:93`

```python
def _convert_event(self, event: dict) -> dict:
    # status-update → { type: "status", state, message }
    # message → { type: "complete", result }
```

**事件转换**:
| A2A 事件 | 前端格式 |
|---------|---------|
| `status-update` | `{ type: "status", state, message }` |
| `message` (最终) | `{ type: "complete", result }` |

---

### 阶段三：前端流式接收 & 消息渲染

#### ⑨ CF-Frontend 流式解析响应

**位置**: `packages/codeflicker-frontend/src/App.tsx:92`

```typescript
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  
  buffer += decoder.decode(value, { stream: true });
  const lines = buffer.split('\n');
  
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const data: StreamEvent = JSON.parse(line.slice(6));
      
      switch (data.type) {
        case 'status':
          setStatusText(data.message);  // 显示"正在识别工具..."
          break;
        case 'complete':
          const parts = parseResponseParts(data.result);
          setMessages((prev) => [...prev, agentMsg]);  // 添加 Agent 消息
          break;
      }
    }
  }
}
```

**前端状态变化**:
1. 收到 `status` → 显示蓝色状态文本（如"正在识别工具..."）
2. 收到 `complete` → 解析并渲染最终消息

---

#### ⑩ ChatMessage 渲染消息列表

**位置**: `packages/codeflicker-frontend/src/components/ChatMessage.tsx`

```typescript
// 遍历 message.parts
parts.map((part, idx) => {
  if (part.kind === 'text') {
    return <div key={idx}>{part.text}</div>;  // 渲染文本
  }
  if (part.kind === 'mcp_ui_resource') {
    return <CardMessage key={idx} ... />;  // 渲染卡片
  }
})
```

**行为**: 根据 `part.kind` 决定渲染方式
- `text` → 普通文本气泡
- `mcp_ui_resource` → `<CardMessage />` 组件

---

### 阶段四：MCP-UI 卡片渲染（双层 iframe 架构）

#### ⑪ CardMessage 初始化 AppRenderer

**位置**: `packages/codeflicker-frontend/src/components/CardMessage.tsx:32`

```typescript
export const CardMessage: React.FC<Props> = ({
  resourceUri,      // "ui://stargate/employee-trend"
  toolName,         // "query_employee_trend"
  toolResult,       // { data: [...], token: "..." }
  uiMetadata,       // { preferred-frame-size: {...} }
}) => {
  const { width = 560, height: preferredHeight } = uiMetadata?.['preferred-frame-size'] ?? {};
  const sandboxUrl = new URL('/sandbox_proxy.html', window.location.href);
  
  return (
    <AppRenderer
      toolName={toolName}
      toolResult={toolResult}
      sandbox={{ url: sandboxUrl }}
      toolResourceUri={resourceUri}
      onReadResource={async ({ uri }) => {
        const res = await fetch(`/resource-proxy?uri=${encodeURIComponent(uri)}`);
        return res.json();
      }}
      onSizeChanged={({ height }) => setIframeHeight(height)}
    />
  );
};
```

**关键配置**:
- `sandbox.url`: `/sandbox_proxy.html`（同源代理层）
- `onReadResource`: 调用 `/resource-proxy` 获取卡片 HTML

---

#### ⑫ @mcp-ui/client AppRenderer 创建外层 iframe

**行为**:
1. 创建外层 iframe，src 指向 `sandbox_proxy.html`
2. 等待 `sandbox-proxy-ready` 消息
3. 调用 `onReadResource()` 发起资源读取

---

#### ⑬ CF-Agent 代理资源请求

**位置**: `packages/codeflicker-agent/src/codeflicker_agent/main.py:155`

```python
@app.get("/resource-proxy")
async def resource_proxy(uri: str, source: str = "host"):
    if uri.startswith("ui://stargate/"):
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{SG_AGENT_BASE_URL}/mcp/resources/read",
                params={"uri": uri},
            )
            return JSONResponse(resp.json())
```

**转发逻辑**:
- 解析 `uri = "ui://stargate/employee-trend"`
- 转发到 SG-Agent: `GET /mcp/resources/read?uri=...`

---

#### ⑭ SG-Agent 生成动态 HTML

**位置**: `packages/stargate-agent/src/stargate_agent/shell_builder.py:14`

```python
def build_employee_trend_shell(component_name: str = COMPONENT_NAME) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
</head>
<body style="margin:0">
  <div id="root"></div>
  <script src="http://localhost:3004/remoteEntry.js"></script>
  <script>
    // Module Federation 初始化脚本
    // 1. 创建共享作用域
    // 2. 注入 react/react-dom 共享实例
    // 3. 调用 container.init()
    // 4. 动态加载 EmployeeChart 组件
    // 5. ReactDOM.createRoot().render(<EmployeeChart />)
  </script>
</body>
</html>"""
```

**HTML 内容**:
1. **React CDN**: 加载 React 和 ReactDOM
2. **remoteEntry.js**: Module Federation 入口
3. **MF 初始化脚本**: 配置共享依赖、加载组件、渲染到 DOM

---

#### ⑮ Sandbox Proxy 创建内层 iframe

**位置**: `packages/codeflicker-frontend/public/sandbox_proxy.html:18`

```javascript
if (msg.method === 'ui/notifications/sandbox-resource-ready') {
    var html = msg.params && msg.params.html;
    
    // 移除旧 iframe
    if (appIframe) {
        document.body.removeChild(appIframe);
    }
    
    // 创建新 iframe
    appIframe = document.createElement('iframe');
    appIframe.style.width = '100%';
    appIframe.style.height = '100%';
    appIframe.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms allow-popups');
    
    // 使用 blob URL 加载 HTML
    var blob = new Blob([html], { type: 'text/html' });
    appIframe.src = URL.createObjectURL(blob);
    document.body.appendChild(appIframe);
    
    // 加载完成后向内层发送消息
    appIframe.addEventListener('load', function () {
        appIframe.contentWindow.postMessage(msg, '*');
    });
}
```

**双层架构说明**:
- **外层 iframe** (`sandbox_proxy.html`): 同源，放宽跨域限制，中转消息
- **内层 iframe** (blob URL): 完全隔离，加载动态生成的 HTML

---

#### ⑯ EmployeeChart 组件初始化

**位置**: `packages/employee-chart-card/src/EmployeeChart.tsx:18`

```typescript
const EmployeeChart: React.FC<EmployeeChartProps> = ({
  data: initialData,
  token: initialToken,
}) => {
  const [data, setData] = useState(initialData ?? []);
  const chartRef = useRef<HTMLDivElement>(null);
  
  // 监听父窗口消息
  useEffect(() => {
    const handleMessage = (e: MessageEvent) => {
      const msg = e.data;
      if (msg.method === 'ui/notifications/tool-result') {
        const result = msg.params?.result ?? {};
        if (result.data) setData(result.data);
      }
    };
    window.addEventListener('message', handleMessage);
  }, []);
  
  // 初始化 ECharts
  useEffect(() => {
    if (!chartRef.current || data.length === 0) return;
    const chart = echarts.init(chartRef.current);
    chart.setOption({
      title: { text: '快手员工趋势' },
      xAxis: { type: 'category', data: data.map((d) => String(d.year)) },
      yAxis: { type: 'value' },
      series: [{ type: 'line', data: data.map((d) => d.count), smooth: true }],
    });
    chart.on('finished', notifySize);  // 图表渲染完成通知高度
  }, [data]);
  
  // ResizeObserver 监听容器尺寸变化
  useEffect(() => {
    const ro = new ResizeObserver(notifySize);
    ro.observe(containerRef.current);
  }, []);
```

**组件行为**:
1. **接收初始数据**: 从 `toolResult` 获取 `data` 和 `token`
2. **监听消息**: 等待 `tool-result` 消息更新数据
3. **渲染图表**: ECharts 初始化并设置折线图配置
4. **通知高度**: 图表渲染完成后，通过 postMessage 通知父窗口实际高度

---

#### ⑰ 高度同步完成卡片展开

**消息流向**:
```
EmployeeChart
  → window.parent.postMessage({ method: 'ui/notifications/size-changed', params: { height } })
  → 内层 iframe
  → sandbox_proxy (外层 iframe)
  → AppRenderer (host 页面)
  → CardMessage.onSizeChanged()
  → setIframeHeight(height)
  → iframe height 动画过渡
  → onLayout() 滚动到底部
```

**最终效果**: 卡片平滑展开到合适高度，用户看到完整的 ECharts 趋势图

---

## 通信协议分层

| 层级 | 协议/机制 | 作用 | 涉及文件 |
|------|----------|------|---------|
| **服务间** | A2A (HTTP JSON-RPC + SSE) | CF-Agent ↔ SG-Agent 标准化通信 | `a2a_stream_client.py`, `a2a_executor.py` |
| **资源代理** | HTTP GET | CF-Agent 代理 MCP-UI 资源读取 | `main.py:155` |
| **组件渲染** | MCP-UI (ui:// URI) | 工具 → UI 资源绑定 | `a2a_executor.py:189` |
| **沙箱内** | postMessage (JSON-RPC 2.0) | Host ↔ iframe 双向通信 | `sandbox_proxy.html`, `EmployeeChart.tsx` |
| **微前端** | Module Federation | 运行时动态加载远程组件 | `shell_builder.py`, `webpack.config.js` |
| **数据共享** | React Context / Props | 父子组件数据传递 | `CardMessage.tsx` |

---

## 关键交互事件序列

```
[时间]  系统              动作                           说明
────────────────────────────────────────────────────────────────────────
T+0     User             输入"查询快手员工人数趋势"
T+1     CF-Frontend      POST /chat-stream              发起 SSE 连接
T+2     CF-Agent         detect_intent()                LLM 意图识别
T+3     CF-Agent         POST SG-Agent :3011            A2A JSON-RPC
T+4     SG-Agent         select_tool()                  LLM 工具选择
T+5     SG-Agent         SSE: status "正在识别工具..."    状态更新
T+6     SG-Agent         生成 mcp_ui_resource           组装 UI 资源
T+7     SG-Agent         SSE: message (complete)        返回最终结果
T+8     CF-Frontend      解析 parts                     分离 text + mcp_ui_resource
T+9     CF-Frontend      渲染 ChatMessage               显示文本气泡
T+10    CF-Frontend      渲染 CardMessage               初始化 AppRenderer
T+11    AppRenderer      GET /resource-proxy            读取卡片资源
T+12    CF-Agent         转发到 SG-Agent                代理请求
T+13    SG-Agent         返回 HTML                      shell_builder 生成
T+14    Sandbox Proxy    创建内层 iframe(blob URL)      沙箱隔离
T+15    EmployeeChart    echarts.init()                 渲染折线图
T+16    EmployeeChart    postMessage size-changed       通知实际高度
T+17    CardMessage      setIframeHeight()              展开卡片容器
```

---

## 扩展：卡片内交互

### 刷新数据

```
用户点击"刷新数据"
  → EmployeeChart handleRefresh()
  → postMessage({ method: 'tools/call', params: { name: 'query_employee_trend' } })
  → AppRenderer
  → POST /a2a-tool-call
  → CF-Agent → A2A → SG-Agent
  → 返回新 toolResult
  → AppRenderer postMessage({ method: 'ui/notifications/tool-result' })
  → EmployeeChart setData()
  → ECharts 更新
```

### 分析趋势

```
用户点击"分析趋势"
  → EmployeeChart handleAnalyze()
  → postMessage({ method: 'ui/message', params: { content: [...] } })
  → AppRenderer
  → onMessage() 回调
  → App.sendMessage()
  → 触发新一轮完整对话
```

---

## 参考文件

| 文件路径 | 职责 |
|---------|------|
| `packages/codeflicker-frontend/src/App.tsx` | 前端主应用，SSE 流式处理 |
| `packages/codeflicker-frontend/src/components/CardMessage.tsx` | 卡片消息容器 |
| `packages/codeflicker-frontend/public/sandbox_proxy.html` | 沙箱代理层 |
| `packages/codeflicker-agent/src/codeflicker_agent/main.py` | CF-Agent 主服务 |
| `packages/codeflicker-agent/src/codeflicker_agent/a2a_stream_client.py` | A2A 流式客户端 |
| `packages/stargate-agent/src/stargate_agent/a2a_executor.py` | SG-Agent 执行器 |
| `packages/stargate-agent/src/stargate_agent/shell_builder.py` | HTML 生成器 |
| `packages/employee-chart-card/src/EmployeeChart.tsx` | 模块联邦组件 |
