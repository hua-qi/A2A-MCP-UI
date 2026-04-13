# 时序图箭头顺序优化与链路完整性保障 Implementation Plan

**Goal:** 通过引入毫秒级时间戳、span_id 配对机制，解决时序图箭头顺序错乱和返回链路缺失问题，并在前端实现虚实线区分、hover 配对高亮和 Span 详情面板。

**Architecture:** 后端两个 sse_logger.py 统一升级，新增 `emit_request`/`emit_response` 函数，每次调用外部服务时用 span_id 关联去程与回程；前端 SequenceDiagram.tsx 根据 `direction` 字段渲染虚实线，建立 spanMap 支持配对高亮，新增 SpanDetailPanel 组件展示完整参数和耗时。

**Tech Stack:** Python (FastAPI, asyncio), TypeScript, React, ECharts (SVG renderer)

---

### Task 1: 升级 sse_logger.py（两个服务）

**Files:**
- Modify: `packages/codeflicker-agent/src/codeflicker_agent/sse_logger.py`
- Modify: `packages/stargate-agent/src/stargate_agent/sse_logger.py`

两个文件内容完全相同，同步修改。

**Step 1: 替换 codeflicker-agent/sse_logger.py 全文**

```python
import asyncio
import json
import uuid
from datetime import datetime
from typing import AsyncGenerator

_queues: list[asyncio.Queue] = []

def _now() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def _emit_raw(source: str, target: str, msg_type: str, detail: str,
              span_id: str | None = None, direction: str | None = None) -> None:
    event = json.dumps({
        "time": _now(),
        "source": source,
        "target": target,
        "type": msg_type,
        "detail": detail,
        "span_id": span_id,
        "direction": direction,
    })
    for q in list(_queues):
        q.put_nowait(event)

async def subscribe() -> AsyncGenerator[str, None]:
    q: asyncio.Queue = asyncio.Queue()
    _queues.append(q)
    connected_event = json.dumps({
        "time": _now(),
        "source": "System",
        "target": "EventLog",
        "type": "connected",
        "detail": "EventLog connected",
    })
    await q.put(connected_event)
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=15.0)
                yield f"data: {event}\n\n"
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
    finally:
        _queues.remove(q)

def emit(source: str, target: str, msg_type: str, detail: str = "") -> None:
    _emit_raw(source, target, msg_type, detail)

def emit_request(source: str, target: str, msg_type: str,
                 detail: str = "", params: dict | None = None) -> str:
    span_id = str(uuid.uuid4())[:8]
    if params:
        detail = (detail + "\n" + json.dumps(params, ensure_ascii=False))[:300]
    _emit_raw(source, target, msg_type, detail, span_id=span_id, direction="request")
    return span_id

def emit_response(span_id: str, source: str, target: str, msg_type: str,
                  detail: str = "", result: dict | list | None = None) -> None:
    if result:
        detail = (detail + "\n" + json.dumps(result, ensure_ascii=False))[:300]
    _emit_raw(source, target, msg_type, detail, span_id=span_id, direction="response")
```

**Step 2: 同样的内容写入 stargate-agent/sse_logger.py**

内容与上面完全一致，复制粘贴到：
`packages/stargate-agent/src/stargate_agent/sse_logger.py`

**Step 3: 验证 Python 语法无误**

```bash
python -c "import packages.codeflicker-agent.src.codeflicker_agent.sse_logger" 2>&1 || \
cd packages/codeflicker-agent && python -c "from src.codeflicker_agent import sse_logger; print('ok')"
```

或直接启动服务后检查 `/health` 接口是否正常：
```bash
curl http://localhost:3002/health
curl http://localhost:3001/health
```

---

### Task 2: 升级 codeflicker-agent/main.py 中的 emit 调用

**Files:**
- Modify: `packages/codeflicker-agent/src/codeflicker_agent/main.py`

当前文件中需要升级的位置：

| 位置 | 原代码 | 升级方向 |
|---|---|---|
| `/chat` 端点，A2A 调用前后 | `emit("CF-Agent", "SG-Agent", "A2A Task", ...)` | emit_request + emit_response |
| `/resource-proxy` 端点 | `emit("Frontend", "CF-Agent", "resource-proxy", uri)` + 无回程 | emit_request + emit_response |
| `/tool-call` 端点，tool-result-fetch 调用 | 两条单向 emit | emit_request + emit_response |

**Step 1: 修改 `/chat` 端点中的 A2A 调用**

找到 `main.py` 第 86-90 行区域（`/chat` 端点内 `_call_sg_agent` 调用前后），修改为：

```python
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
```

**Step 2: 修改 `/resource-proxy` 端点**

```python
@app.get("/resource-proxy")
async def resource_proxy(uri: str):
    span = sse_logger.emit_request(
        "Frontend", "CF-Agent", "resource-proxy",
        params={"uri": uri},
    )
    if uri.startswith("ui://stargate/"):
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{SG_AGENT_BASE_URL}/mcp/resources/read",
                params={"uri": uri},
            )
            data = resp.json()
            sse_logger.emit_response(
                span, "CF-Agent", "Frontend", "resource-proxy",
                result={"status": resp.status_code},
            )
            return JSONResponse(data)
    sse_logger.emit_response(span, "CF-Agent", "Frontend", "resource-proxy", detail="error: unknown host")
    return JSONResponse({"error": "Unknown resource host"}, status_code=404)
```

**Step 3: 修改 `/tool-call` 端点中的 lazy fetch**

找到 `tool_name == "query_employee_trend_lazy"` 分支，修改为：

```python
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
        sse_logger.emit("CF-Agent", "Frontend", "tool-result", tool_name)
        return JSONResponse({"toolResult": result_data})
    # fallback 省略，保持原有
```

**Step 4: 重启服务验证无报错**

```bash
# 在 packages/codeflicker-agent 目录
uvicorn src.codeflicker_agent.main:app --port 3002 --reload
```

观察启动日志无 ImportError / SyntaxError 即可。

---

### Task 3: 升级 stargate-agent/main.py 中的 emit 调用

**Files:**
- Modify: `packages/stargate-agent/src/stargate_agent/main.py`

需要升级的位置：

| 位置 | 描述 |
|---|---|
| `mcp_resources_read` 端点 | resource-proxy → SG-Agent，SG-Agent → MCP-Server，各自加回程 |
| `handle_message` — mcp mode 的 tool call | SG-Agent → MCP-Server 调用 |
| `handle_message` — A2A Response emit | 已是最终回程，改为 emit_response |

**Step 1: 修改 `mcp_resources_read` 端点**

（已在上一步手动修复了 source，现在升级为 span 版本）

```python
@app.get("/mcp/resources/read")
async def mcp_resources_read(uri: str):
    outer_span = sse_logger.emit_request(
        "resource-proxy", "SG-Agent", "mcp-resources/read",
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
            outer_span, "SG-Agent", "resource-proxy", "mcp-resources/read",
            result={"count": len(contents)},
        )
        return JSONResponse({"contents": contents})

    if uri.startswith("ui://stargate/card/"):
        # ... card 逻辑保持不变，最后加 emit_response ...
        card_id = uri.removeprefix("ui://stargate/card/")
        inst = card_cache.get(card_id)
        if inst is None:
            sse_logger.emit_response(outer_span, "SG-Agent", "resource-proxy", "mcp-resources/read", detail="error: not found")
            raise HTTPException(status_code=404, detail="Card instance not found or expired")
        # ... html 生成逻辑不变 ...
        # 在 return 前加：
        sse_logger.emit_response(
            outer_span, "SG-Agent", "resource-proxy", "mcp-resources/read",
            result={"uri": uri},
        )
        # return JSONResponse(...)  保持原有

    sse_logger.emit_response(outer_span, "SG-Agent", "resource-proxy", "mcp-resources/read", detail="error: unknown uri")
    raise HTTPException(status_code=404, detail="Unknown resource URI")
```

**Step 2: 修改 `handle_message` 中的 MCP tool call（mcp mode）**

找到 `if mode == "mcp":` 分支，将 mcp tool call 的两条 emit 改为 span：

```python
# query_employee_trend, mcp mode
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
```

同样处理 `query_employee_trend_lazy` 的 mcp 分支。

**Step 3: 修改 `handle_message` 的最终 A2A Response**

`A2A Response` 是由 CF-Agent 的 `emit_request("CF-Agent", "SG-Agent", "A2A Task", ...)` 发起的，
SG-Agent 的 `handle_message` 是接收方，所以这里需要用 CF-Agent 传过来的 span_id 来回复。

但由于 A2A 协议（python_a2a）不透传 span_id，当前架构无法跨服务传递 span_id。  
**临时方案**：保持 `emit` 不变（单向通知），在 CF-Agent 侧 `emit_response` 已覆盖 A2A Task 回程，SG-Agent 的 `"A2A Response"` emit 改为更清晰的命名即可：

```python
# 将原来的
sse_logger.emit("SG-Agent", "CF-Agent", "A2A Response", f"mcp_ui_resource {resource_uri}")
# 保持不变，这条 emit 作为 SG-Agent 视角的单向通知，CF-Agent 侧 emit_response 是配对回程
```

**Step 4: 重启 stargate-agent 验证无报错**

```bash
cd packages/stargate-agent
uvicorn src.stargate_agent.main:app --port 3001 --reload
```

---

### Task 4: 扩展前端类型定义

**Files:**
- Modify: `packages/codeflicker-frontend/src/types.ts`

**Step 1: 在 EventLogEntry 接口中新增字段**

找到：
```typescript
export interface EventLogEntry {
  time: string;
  source: string;
  target: string;
  type: string;
  detail: string;
}
```

替换为：
```typescript
export interface EventLogEntry {
  time: string;
  source: string;
  target: string;
  type: string;
  detail: string;
  span_id?: string;
  direction?: 'request' | 'response';
}
```

**Step 2: 确认前端 TypeScript 编译无报错**

```bash
cd packages/codeflicker-frontend
npx tsc --noEmit
```

Expected: 无任何输出（无错误）

---

### Task 5: 新增 SpanDetailPanel 组件

**Files:**
- Create: `packages/codeflicker-frontend/src/components/SpanDetailPanel.tsx`

**Step 1: 创建组件文件**

```tsx
import React from 'react';
import type { EventLogEntry } from '../types';

interface SpanPair {
  request: EventLogEntry;
  response?: EventLogEntry;
}

interface Props {
  pair: SpanPair | null;
  onClose: () => void;
}

function calcDuration(req: EventLogEntry, resp?: EventLogEntry): string {
  if (!resp) return '-';
  const parse = (t: string) => {
    const [hms, ms = '0'] = t.split('.');
    const [h, m, s] = hms.split(':').map(Number);
    return (h * 3600 + m * 60 + s) * 1000 + Number(ms);
  };
  const diff = parse(resp.time) - parse(req.time);
  return diff >= 0 ? `${diff}ms` : '-';
}

function tryFormatJson(raw: string): string {
  const idx = raw.indexOf('\n');
  if (idx === -1) return raw;
  const jsonPart = raw.slice(idx + 1);
  try {
    return raw.slice(0, idx) + '\n' + JSON.stringify(JSON.parse(jsonPart), null, 2);
  } catch {
    return raw;
  }
}

export const SpanDetailPanel: React.FC<Props> = ({ pair, onClose }) => {
  if (!pair) return null;
  const { request, response } = pair;
  const duration = calcDuration(request, response);

  return (
    <div style={{
      width: 320,
      flexShrink: 0,
      borderLeft: '1px solid #e2e8f0',
      background: '#f8fafc',
      display: 'flex',
      flexDirection: 'column',
      fontSize: 11,
      fontFamily: 'monospace',
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '8px 12px',
        borderBottom: '1px solid #e2e8f0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: '#fff',
      }}>
        <span style={{ fontWeight: 600, color: '#1e293b' }}>Span 详情</span>
        <button
          onClick={onClose}
          style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: 14, color: '#94a3b8' }}
        >✕</button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px' }}>
        <Row label="span_id" value={request.span_id ?? '-'} />
        <Row label="耗时" value={duration} highlight />

        <Section title="去程 (Request)">
          <Row label="时间" value={request.time} />
          <Row label="路径" value={`${request.source} → ${request.target}`} />
          <Row label="类型" value={request.type} />
          {request.detail && <Pre label="params" value={tryFormatJson(request.detail)} />}
        </Section>

        {response && (
          <Section title="回程 (Response)">
            <Row label="时间" value={response.time} />
            <Row label="路径" value={`${response.source} → ${response.target}`} />
            {response.detail && <Pre label="result" value={tryFormatJson(response.detail)} />}
          </Section>
        )}
        {!response && (
          <div style={{ color: '#f59e0b', marginTop: 8 }}>等待回程...</div>
        )}
      </div>
    </div>
  );
};

const Row: React.FC<{ label: string; value: string; highlight?: boolean }> = ({ label, value, highlight }) => (
  <div style={{ display: 'flex', gap: 6, marginBottom: 4 }}>
    <span style={{ color: '#64748b', minWidth: 52 }}>{label}:</span>
    <span style={{ color: highlight ? '#2563eb' : '#1e293b', wordBreak: 'break-all' }}>{value}</span>
  </div>
);

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div style={{ marginTop: 12 }}>
    <div style={{ color: '#92400e', fontWeight: 600, marginBottom: 4 }}>{title}</div>
    {children}
  </div>
);

const Pre: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div style={{ marginTop: 4 }}>
    <div style={{ color: '#64748b' }}>{label}:</div>
    <pre style={{
      margin: '2px 0 0',
      padding: '4px 6px',
      background: '#f1f5f9',
      border: '1px solid #e2e8f0',
      borderRadius: 3,
      fontSize: 10,
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-all',
      maxHeight: 160,
      overflowY: 'auto',
    }}>{value}</pre>
  </div>
);
```

**Step 2: 确认 TypeScript 无报错**

```bash
cd packages/codeflicker-frontend
npx tsc --noEmit
```

---

### Task 6: 改造 SequenceDiagram.tsx

**Files:**
- Modify: `packages/codeflicker-frontend/src/components/SequenceDiagram.tsx`

这是改动最大的一个 Task，分步进行。

**Step 1: 在文件顶部新增 import**

在现有 import 行之后，新增：
```tsx
import { SpanDetailPanel } from './SpanDetailPanel';
import type { EventLogEntry } from '../types';
```

（`EventLogEntry` 已有 import，确认不重复即可）

**Step 2: 新增 state 和 spanMap 逻辑**

在组件内 `const [hotZones, setHotZones]` 之后，新增：

```tsx
const [hoveredSpanId, setHoveredSpanId] = useState<string | null>(null);
const [selectedPair, setSelectedPair] = useState<{ request: EventLogEntry; response?: EventLogEntry } | null>(null);
```

**Step 3: 在 renderChart 中构建 spanMap 并实现虚实线**

在 `entries.forEach((entry, rowIdx) => {` 循环之前，插入 spanMap 构建逻辑：

```tsx
const spanMap = new Map<string, { reqIdx?: number; respIdx?: number }>();
entries.forEach((e, idx) => {
  if (!e.span_id) return;
  const existing = spanMap.get(e.span_id) ?? {};
  if (e.direction === 'request') existing.reqIdx = idx;
  if (e.direction === 'response') existing.respIdx = idx;
  spanMap.set(e.span_id, existing);
});
```

**Step 4: 修改箭头渲染逻辑（区分虚实线和颜色）**

在 `entries.forEach` 循环内，找到 `graphicElements.push` 画线的部分，替换为：

```tsx
const isResponse = entry.direction === 'response';
const isPairHovered = hoveredSpanId !== null && entry.span_id === hoveredSpanId;
const lineColor = isPairHovered ? '#f59e0b' : isResponse ? '#64748b' : ARROW_COLOR;
const lineDash = isResponse ? [4, 3] : undefined;

graphicElements.push({
  type: 'line',
  shape: { x1, y1: y, x2, y2: y },
  style: {
    stroke: lineColor,
    lineWidth: 1.5,
    ...(lineDash ? { lineDash } : {}),
  },
  z: 5,
});

graphicElements.push({
  type: 'polygon',
  shape: {
    points: [
      [x2, y],
      [x2 - arrowDir * ARROW_SIZE, y - ARROW_SIZE / 2],
      [x2 - arrowDir * ARROW_SIZE, y + ARROW_SIZE / 2],
    ],
  },
  style: { fill: lineColor },
  z: 6,
});
```

注意：`hoveredSpanId` 在 renderChart 内部引用时，需将其作为依赖加入 `useCallback` 的依赖数组：
```tsx
const renderChart = useCallback(() => { ... }, [entries, hoveredSpanId]);
```

**Step 5: 在 HotZone 上绑定 hover 和 click 事件**

找到 hotZones 渲染部分的 `<div>` 元素，在 `onMouseEnter` 之外新增：

```tsx
onMouseEnter={(e) => {
  // 原有 tooltip 逻辑...
  if (entry.span_id) setHoveredSpanId(entry.span_id);  // 新增
}}
onMouseLeave={() => {
  setTooltip((prev) => ({ ...prev, visible: false }));
  setHoveredSpanId(null);  // 新增
}}
onClick={() => {
  if (!entry.span_id) return;
  const info = spanMap.get(entry.span_id);
  const reqEntry = info?.reqIdx !== undefined ? entries[info.reqIdx] : entry;
  const respEntry = info?.respIdx !== undefined ? entries[info.respIdx] : undefined;
  setSelectedPair({ request: reqEntry, response: respEntry });
}}
```

由于 hotZones 渲染在 map 中不能直接访问 entries 和 spanMap（它们在 renderChart 函数作用域内），需要将 spanMap 提升为 state：

```tsx
const [spanMapState, setSpanMapState] = useState<Map<string, { reqIdx?: number; respIdx?: number }>>(new Map());
```

在 renderChart 最后调用 `setSpanMapState(spanMap)`。

**Step 6: 在组件 JSX 最外层 div 中引入 SpanDetailPanel**

找到组件 return 的最外层 `<div>`，将其改为横向布局：

```tsx
return (
  <div style={{
    width: '100%', height: '100%', background: BG_COLOR,
    position: 'relative', display: 'flex', flexDirection: 'row',   // ← 改为 row
    overflow: 'hidden',
  }}>
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
      {/* 原有的 header + scrollRef + tooltip 全部放在这个 div 内 */}
    </div>
    <SpanDetailPanel
      pair={selectedPair}
      onClose={() => setSelectedPair(null)}
    />
  </div>
);
```

**Step 7: 启动前端开发服务器验证渲染**

```bash
cd packages/codeflicker-frontend
npm run dev
```

打开浏览器，触发一次对话，观察时序图：
- response 类型箭头应为虚线灰色
- hover 某箭头时，配对的另一条变为橙色
- 点击箭头后，右侧面板滑出展示 span 详情

**Step 8: 最终 TypeScript 检查**

```bash
cd packages/codeflicker-frontend
npx tsc --noEmit
```

Expected: 无输出（无错误）

---

### 验收检查清单

| 检查项 | 验证方式 |
|---|---|
| 时间戳精度为毫秒 | 观察 SSE 事件流，time 字段格式为 `HH:MM:SS.mmm` |
| 同一请求的去程/回程有相同 span_id | Chrome DevTools → Network → SSE → 查看 data |
| mcp-resources/read 有 4 条箭头（去+回各2条）| 触发 mcp 模式对话，观察时序图 |
| response 箭头为虚线 | 视觉验证 |
| hover 某箭头，配对箭头变橙色 | 鼠标悬停验证 |
| 点击箭头，右侧面板展示 params/result/耗时 | 点击验证 |
| 两个服务均可正常启动 | curl /health 验证 |
