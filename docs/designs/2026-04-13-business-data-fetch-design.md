# 业务数据获取架构设计

**Date:** 2026-04-13

## Context

在 MCP-UI 双路径改造中，业务数据（如员工趋势数据、鉴权 token）被硬编码在 `stargate-mcp-ui-server` 的 `tools.py` 中（`TREND_DATA`、`TOKEN`、`build_tool_result()`）。这违反了 MCP Server 的职责边界——MCP Server 应只负责提供 shell HTML（UI 资源），不应持有任何业务数据。同时，SG-Agent 的 mcp 路径通过 `_call_mcp_tool_result()` 直接从 MCP Server 拉取业务数据，进一步强化了这一错误依赖。

目标：明确各服务的职责边界，让业务数据从独立业务 API 获取，MCP Server 彻底与业务数据解耦。

## Discussion

**业务数据来源**：应来自独立业务 API（如 HR 系统），而非 resource-center。resource-center 仅作为组件注册中心，提供 `componentName / containerName / remoteEntryUrl`，不涉及业务数据。

**谁来调业务 API**：
- App（iframe）既可通过 agent 链路间接获取数据（agent 能感知当前数据），也可直接调业务 API（适合详情、分页等高频轻量请求）。
- 两种路径共存，按场景选择。

**三种候选方案**：
- 方案 A：业务数据统一由 SG-Agent 代理获取，App 只通过 `tools/call` 间接读取。优点是 agent 完全感知数据；缺点是所有数据请求都走 agent 链路，延迟高。
- 方案 B：SG-Agent 只返回 token，App 直连业务 API 取数据。优点是 App 直连高效；缺点是 agent 不感知数据。
- 方案 C（选定）：两路共存——场景1/2/3 由 SG-Agent 调业务 API 返回数据，场景4 由 App 直连业务 API 用 token 鉴权。场景2 为懒加载变体：UI 壳子先渲染，组件挂载后主动通过 tools/call 拉数据，agent 感知数据但首屏不阻塞。

**MCP Server 路径的补充确认**：endpoint 路径和 mcp Server 路径在业务数据获取上逻辑应完全对称，都由 SG-Agent 调独立业务 API。原 `_call_mcp_tool_result()` 函数（调 MCP Server 的 `/tool-result/` 端点）应删除，mcp 路径改为 SG-Agent 自己调业务 API 拼 toolResult。

## Approach

采用**方案 C：Agent 代理 + App 直连两路共存**。

核心原则：
1. MCP Server 职责收窄为「仅提供 shell HTML」，删除所有业务数据相关代码
2. SG-Agent 新增独立业务 API 路由，作为业务数据的唯一出口（agent 链路侧）
3. App 在需要详情等轻量数据时可持 token 直连业务 API，不绕道 agent

## Architecture

### 服务职责划分

```
resource-center-mock（端口 3003）
  └─ 组件注册中心
  └─ GET /api/components/:name → { componentName, containerName, remoteEntryUrl }
  └─ 不涉及业务数据

独立业务 API（由 stargate-agent 内路由模拟，端口 3001）
  └─ GET /api/employee/trend        → 员工趋势数据列表
  └─ GET /api/employee/detail/{year} → 年份详情（已有）
  └─ POST /api/token/exchange        → 换取 token（已有）

stargate-mcp-ui-server（端口 3005）
  └─ 职责：仅提供 shell HTML（MF 加载器）
  └─ 删除：TREND_DATA、TOKEN、build_tool_result()
  └─ query_employee_trend tool 不再携带 toolResult 中的业务数据

stargate-agent（端口 3001/3011）
  └─ endpoint 路径：调 resource-center 取组件信息 + 调业务 API 取数据 → 拼 toolResult
  └─ mcp 路径：使用 MCP Server 的 resourceUri + 调业务 API 取数据 → 拼 toolResult
  └─ 删除 _call_mcp_tool_result()（不再从 MCP Server 拉业务数据）
  └─ /api/tool-result/{tool_name}：改为调 /api/employee/trend 实时获取（不内联）
```

### 数据流

**场景1 - 即时数据（SG-Agent 代理）**
```
用户消息
 → SG-Agent LLM 选 query_employee_trend
 → SG-Agent 调 GET /api/employee/trend（内部）
 → 拼 toolResult = { data, token }
 → A2A 响应携带 resourceUri + toolResult
 → AppBridge 发 tool-result notification → App 直接渲染图表
```

**场景2 - 懒加载（UI 先渲染，App 主动拉数据）**
```
用户消息
 → SG-Agent LLM 选 query_employee_trend_lazy
 → SG-Agent 调 GET /api/employee/trend（内部）获取 token，但不携带 data
 → A2A 响应携带 resourceUri（ui://stargate/employee-trend-lazy）+ toolResult（仅含 token，无 data）
 → AppBridge 渲染 iframe，加载 EmployeeChartLazy 组件
 → EmployeeChartLazy 挂载后主动发 tools/call { name: query_employee_trend_lazy }
 → AppBridge.onCallTool → CardMessage.handleCallTool
 → POST /tool-call → CF-Agent → SG-Agent A2A
 → SG-Agent 调 GET /api/employee/trend，返回 { data, token }
 → AppBridge 把结果作为 JSON-RPC response 发给 App
 → EmployeeChartLazy 收到数据后渲染图表
```

**场景3 - App 刷新（tools/call 链路）**
```
用户点"刷新数据"
 → App 发 tools/call { name: query_employee_trend }
 → AppBridge.onCallTool → CardMessage.handleCallTool
 → POST /tool-call → CF-Agent → SG-Agent A2A
 → SG-Agent 调 GET /api/employee/trend
 → 返回 { data, token }
 → AppBridge 把结果作为 JSON-RPC response 发给 App
 → App 更新图表
```

**场景4 - App 直连（detail 等轻量请求）**
```
用户点"2022 详情"
 → App 持 token 直接 fetch GET /api/employee/detail/2022
 → 渲染详情（不经过 agent）
```

### 需要改动的文件

| 文件 | 改动 |
|------|------|
| `stargate-mcp-ui-server/tools.py` | 删除 `TREND_DATA`、`TOKEN`、`build_tool_result()` |
| `stargate-mcp-ui-server/main.py` | `query_employee_trend` 不再携带 `toolResult` 业务数据 |
| `stargate-agent/main.py` | 新增 `GET /api/employee/trend`；删除 `_call_mcp_tool_result()`；endpoint/mcp 两路均调业务 API；`/api/tool-result/` 改为实时调用 |
| `stargate-mcp-ui-server/tests/test_tools.py` | 删除 `test_build_tool_result_structure` |
| `stargate-mcp-ui-server/tests/test_main.py` | 更新 `test_query_employee_trend_returns_tool_result`（tool 不再返回业务数据） |
