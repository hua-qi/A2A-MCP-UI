# A2A 扩展优化设计

**Date:** 2026-04-15

## Context

当前项目通过 `python_a2a` 库实现 Agent 间通信，但存在以下核心问题：

- **结构化数据传输缺失**：业务 JSON 数据被序列化后塞进 `TextContent.text` 字段，完全丢失类型信息和协议语义
- **缺乏 A2A 层流式响应**：AgentCard 中 `streaming: false`，A2A 链路为同步全量返回黑盒，前端进度感依赖 CF-Agent 自建的 `/events` SSE
- **工具调用绕开 A2A**：卡片内工具调用通过独立的 `/tool-call`、`/tool-result` HTTP 接口传递，与 A2A 协议体系完全脱节
- **UI 资源元数据不透明**：MCP-UI 资源 URI 藏在文本消息中传递，没有正式的协议声明

目标是通过定义 A2A 扩展，将上述问题全部纳入规范化的协议体系，采用终态直接切换，不保留任何过渡兼容路径。

## Discussion

### 优化目标确认

讨论确认需要同时解决四个方向的问题：结构化数据传输、流式响应体验、工具调用协议统一、UI 资源元数据规范化。设计原则为严格准入——扩展必须完全符合 A2A 规范，不引入与核心协议冲突的自定义行为。

### 方案探索

探索了三种扩展粒度方案：

- **方案 A（大一统）**：单一 `mcp-ui` 扩展覆盖所有能力。优点是声明简单，缺点是粒度太粗，客户端无法按需支持，后期难拆分。
- **方案 B（细粒度）**：三个独立扩展，每个职责单一。优点是职责清晰、符合 A2A 扩展最佳实践，缺点是需要管理三套扩展 URI 和协商逻辑。
- **方案 C（两层分层）**：按传输层和交互层分为两个扩展。介于 A、B 之间，但分层边界需要仔细定义。

**最终选择方案 B**，三个独立扩展，职责单一，严格准入。

### 终态调整

初始设计中 `streaming` 和 `tool-protocol` 为 `required: false` 并保留降级路径。经讨论后调整为：**三个扩展全部 `required: true`，废弃所有旧接口和降级逻辑，直接切换到终态**。

## Approach

定义三个独立的 A2A 扩展，全部标记为 `required: true`，在 CF-Agent 和 SG-Agent 的 AgentCard 中声明。客户端启动时校验所有扩展均支持，任意缺失则拒绝连接，不降级不重试。

废弃项一览：

| 废弃项 | 终态替代 |
|--------|---------|
| `TextContent` 传 JSON 字符串 | `DataPart` 结构化传输 |
| A2A 同步响应模式 | A2A SSE streaming |
| `/tool-call`、`/tool-result` HTTP 接口 | `ToolRequestPart` / `ToolResponsePart` via A2A |
| CF-Agent 自建 `/events` SSE | 直接透传 A2A stream |

## Architecture

### AgentCard 扩展声明

```json
{
  "extensions": [
    { "uri": "https://yourproject/a2a-ext/structured-data", "required": true },
    { "uri": "https://yourproject/a2a-ext/streaming",       "required": true },
    { "uri": "https://yourproject/a2a-ext/tool-protocol",   "required": true }
  ]
}
```

### 扩展 1：`structured-data`

新增 `DataPart` 消息部件类型，替代 `TextContent` 滥用：

```json
{
  "kind": "data",
  "mimeType": "application/json",
  "schema": "https://yourproject/schemas/agent-request-v1",
  "data": { "user_text": "...", "mode": "endpoint" }
}
```

携带 `schema` URI，双方均可对消息体做结构校验，语义明确。

### 扩展 2：`streaming`

AgentCard 中 `streaming: true`，A2A 响应改为 SSE stream，推送中间状态事件：

```
event: task_status
data: { "state": "working", "progress": 0.3, "message": "正在查询 MCP..." }

event: task_status
data: { "state": "working", "progress": 0.8, "message": "渲染 UI 资源..." }

event: task_complete
data: { "state": "completed", "result": { ... } }
```

CF-Agent 收到 A2A stream 后直接透传给前端，不再维护自建 `/events` SSE。

### 扩展 3：`tool-protocol`

定义 `ToolRequestPart` 和 `ToolResponsePart`，将工具调用纳入 A2A 消息体：

```
卡片 postMessage
  → CF-Agent 封装为 Message(ToolRequestPart)
    → SG-Agent via A2A
      → 返回 Message(ToolResponsePart)
        → CF-Agent 转发 postMessage 回卡片
```

`/tool-call` 和 `/tool-result` 接口完全废弃，不保留任何 fallback。

### 客户端协商流程

```
CF-Agent 启动
  → 获取 SG-Agent AgentCard
  → 校验三个扩展均存在且 required=true
  → 任意缺失 → 返回 -32001，连接终止
  → 全部通过 → 建立连接，启用扩展能力
```

### 错误处理

| 场景 | 错误码 | 处理方式 |
|------|--------|---------|
| 客户端缺少任意扩展支持 | `-32001` | 连接终止，不降级 |
| DataPart schema 校验失败 | `-32602` | 请求终止，携带 schema 错误详情 |
| streaming 中途断开 | 标准错误 | 由调用方决定是否重新发起完整请求 |
| tool-protocol 超时 | `-32000` | 返回超时错误，不走任何 HTTP fallback |
