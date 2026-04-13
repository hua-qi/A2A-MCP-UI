# 时序图箭头顺序优化与链路完整性保障

**Date:** 2026-04-13

## Context

当前时序图存在两个核心缺陷：

1. **顺序问题**：CF-Agent 和 SG-Agent 各自通过 SSE 推送事件，前端合并时按 `HH:MM:SS`（秒级精度）时间戳排序。跨服务事件在同一秒内发出时，排序不稳定，导致时序图箭头顺序错乱（例如 `A2A Response` 出现在 `mcp-resources/read` 之前）。

2. **完整性问题**：各处 `sse_logger.emit()` 调用分散在业务代码各处，缺乏约束机制，容易漏写返回链路（例如 `_read_mcp_resource` 完成后没有任何回程 emit）。此外，`emit` 的 source/target 也存在写错的情况（如误写为 `CF-Agent` 而非 `resource-proxy`）。

## Discussion

### 排序方案探索

| 方案 | 描述 | 结论 |
|---|---|---|
| 提升时间戳精度 | 改为毫秒级 `HH:MM:SS.mmm` | 采用，时间戳字典序自然支持毫秒排序 |
| 全局序列号 | 前端维护单调递增 seq，彻底脱离时钟 | 作为兜底，前端已有 `_seq` 逻辑 |
| **两者结合** | 毫秒时间戳用于展示，`_seq` 兜底同毫秒乱序 | **最终选择** |

### 链路完整性方案探索

| 方案 | 描述 | 结论 |
|---|---|---|
| emit_span context manager | 包裹调用，自动 emit 返回 | 简单但跨服务 span 需手动处理 |
| span_id 关联 | `emit_request` 返回 span_id，`emit_response` 传入关联 | **最终选择**，支持前端配对展示 |
| 配置驱动校验 | YAML 定义期望链路，运行时比对 | 过重，YAGNI |

### detail 信息丰富性

用户明确要求 `detail` 不仅是描述文字，还应包含请求参数（request 时）和响应摘要（response 时），以便 tooltip 展示完整上下文。设计中 `emit_request` 接受 `params` 参数，`emit_response` 接受 `result` 参数，序列化后拼入 detail（截断至 200 字符防止过长）。

### 前端可视化选择

经确认，前端可视化需包含：
- 虚实线区分（request 实线，response 虚线）
- 配对关联高亮（hover 去程自动高亮对应回程，反之亦然）
- Span 详情面板（点击箭头，右侧展开完整 params/result/耗时）

耗时展示（tooltip 中）不在本次范围内，由面板替代。

## Approach

**核心思路：** 在 `sse_logger.py` 层面引入 `span_id`，将原本离散的 `emit` 调用升级为成对的 `emit_request` / `emit_response`，同时将时间戳精度提升至毫秒，从根源上解决排序和完整性两个问题。

前端在渲染层面通过 `span_id` 建立配对 Map，支持虚实线区分、hover 高亮和点击展开详情面板。

## Architecture

### 后端：sse_logger.py 改造（两个服务各一份）

```python
import uuid

def _now() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]  # HH:MM:SS.mmm

def _emit_raw(source, target, msg_type, detail, span_id=None, direction=None):
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

def emit(source, target, msg_type, detail=""):
    _emit_raw(source, target, msg_type, detail)

def emit_request(source, target, msg_type, detail="", params=None) -> str:
    span_id = str(uuid.uuid4())[:8]
    if params:
        detail += "\n" + json.dumps(params, ensure_ascii=False)[:200]
    _emit_raw(source, target, msg_type, detail, span_id=span_id, direction="request")
    return span_id

def emit_response(span_id, source, target, msg_type, detail="", result=None):
    if result:
        detail += "\n" + json.dumps(result, ensure_ascii=False)[:200]
    _emit_raw(source, target, msg_type, detail, span_id=span_id, direction="response")
```

**调用替换规则：**
- 有明确去程/回程对的 `emit` → 替换为 `emit_request` + `emit_response`
- 单向通知类（如 llm-call）→ 保持原 `emit`

**需改造的具体位置：**
- `stargate-agent/main.py` — `mcp_resources_read` 端点
- `stargate-agent/main.py` — `handle_message` 中的 A2A、MCP tool call 等
- `codeflicker-agent/main.py` — A2A 调用、mcp-resources/read 代理等

### 前端：类型扩展

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

### 前端：useEventLog.ts

无需改动。时间戳从 `HH:MM:SS` 升级为 `HH:MM:SS.mmm` 后，字典序比较自然支持毫秒排序；`_seq` 作为同毫秒兜底逻辑已存在。

### 前端：SequenceDiagram.tsx 改造

**箭头渲染：**
- `direction === 'request'` 或无 direction：实线，颜色 `#2563eb`
- `direction === 'response'`：虚线 `lineDash: [4, 3]`，颜色 `#64748b`

**span 配对 Map：**
```typescript
const spanMap = new Map<string, { reqIdx: number; respIdx: number }>();
entries.forEach((e, idx) => {
  if (!e.span_id) return;
  const existing = spanMap.get(e.span_id) ?? {};
  if (e.direction === 'request') existing.reqIdx = idx;
  if (e.direction === 'response') existing.respIdx = idx;
  spanMap.set(e.span_id, existing as any);
});
```

**hover 高亮：** hover 某行时，通过 `span_id` 找到配对行的 index，动态修改其 ECharts graphic 元素颜色为橙色高亮。

**SpanDetailPanel 组件（新增）：**
- 点击任意箭头触发，右侧滑出固定宽度面板
- 展示：span_id、去程时间、回程时间、耗时（ms）、params（格式化 JSON）、result（格式化 JSON）

### 改动文件清单

```
packages/
├── codeflicker-agent/src/codeflicker_agent/
│   ├── sse_logger.py          ← 毫秒精度、emit_request/emit_response
│   └── main.py                ← 替换相关 emit 调用
├── stargate-agent/src/stargate_agent/
│   ├── sse_logger.py          ← 同上
│   └── main.py                ← 替换相关 emit 调用
└── codeflicker-frontend/src/
    ├── types.ts                ← 新增 span_id、direction 字段
    └── components/
        ├── SequenceDiagram.tsx ← 虚实线、hover 高亮、点击触发面板
        └── SpanDetailPanel.tsx ← 新增右侧 span 详情面板组件
```
