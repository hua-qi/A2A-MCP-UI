# MCP-UI 双路径改造设计

**Date:** 2026-04-13

---

## Context

当前项目（A2A-mcpUI）已实现一条完整的 Endpoint 路径：

```
前端 → CF-Agent /chat → A2A → SG-Agent → card cache → HTML
前端 → CF-Agent /resource-proxy → SG-Agent /mcp/resources/read → HTML
```

同时新增了独立的 MCP Server（`stargate-mcp-ui-server`，端口 3005），通过标准 MCP SSE 协议暴露 `query_employee_trend` tool 和 `ui://stargate/employee-trend` resource。

**改造目标**：

1. 在现有 Endpoint 路径基础上，新增 MCP Server 路径，两条路径可通过前端开关切换。
2. 将两条路径的 resource 获取方式从"HTML 内联数据"改造为符合 MCP-UI 规范的"模式 A：shell + toolResult"。
3. 覆盖四个完整的数据获取场景，便于开发者理解 MCP-UI 规范，同时作为演示用途。
4. 差异封装在 SG-Agent 内部，CF-Agent 和前端对 MCP Server 的存在无感知。

---

## Discussion

### 触发机制与开关位置

- **触发机制**：前端 UI 开关切换（而非用户输入内容决定、也非 Agent 自动路由）。
- **开关位置**：前端全局开关，切换时调用 CF-Agent 的 `POST /mode` 接口，CF-Agent 内存保存当前 mode。
- **影响范围**：影响整个链路（`/chat` 调用方式 + `/resource-proxy` 路由），不只是 resource 获取段。

### A2A 协议职责边界

CF-Agent 不应直接调用 `stargate-mcp-ui-server`，因为后者是 SG-Agent 的 MCP Server，两者属于同一服务域。CF-Agent 始终通过 A2A 协议与 SG-Agent 交互，两条路径的差异**完全封装在 SG-Agent 内部**，对 CF-Agent 透明。

`/resource-proxy` 统一转发到 SG-Agent，由 SG-Agent 根据 URI 格式自动判断路由（`card/{id}` 走 card cache，`employee-trend` 转发给 stargate-mcp-ui-server）。

### 静态 resource 的问题

当前 `stargate-mcp-ui-server` 把趋势数据硬编码并内联到 HTML 中，存在以下问题：

- tool call 的输入参数无法传递到 resource，参数被忽略。
- HTML 与数据耦合，resource 不具备通用性。
- 不符合 MCP-UI 规范的设计意图。

### 模式 A vs 模式 B

| | 模式 A（shell + toolResult） | 模式 B（动态 resource，数据内联 HTML） |
|---|---|---|
| resource 性质 | 静态 shell，URI 固定 | 动态，URI 编码参数 |
| 数据流向 | toolResult → AppRenderer prop → guest UI | resource HTML 内联 |
| 规范符合度 | 更高，职责分离清晰 | 合法但耦合 |
| 可扩展性 | 好，数据变化不影响 resource | 每次数据变化需重新构建 URI |

**决定**：两条路径均改造为模式 A。

### 四个数据获取场景

在讨论 toolResult 来源时，识别出四个独立场景，需全部覆盖：

| 场景 | 说明 | Agent 感知 |
|---|---|---|
| A | A2A 响应直接带 toolResult，组件首渲即有数据，适合小数据量 | 完全感知 |
| B | 组件先渲染 shell，数据异步加载，用户体验更好，适合慢接口 | 完全感知 |
| C | guest UI 通过 `onCallTool` 触发重新获取，适合用户交互刷新 | 完全感知 |
| D | guest UI 直接调业务接口，鉴权由 token 处理，Agent 不感知 | 不感知 |

### `toolName` 硬编码问题

`CardMessage.tsx` 中 `toolName="query_employee_trend"` 硬编码不合理——CF-Agent 前端不应感知 SG-Agent 的 tool 名称。解决方案：CF-Agent 在 A2A 响应的 `mcp_ui_resource` 中带上 `toolName` 字段，前端透传给 `AppRenderer`。

---

## Approach

1. **前端加全局 mode 开关**，切换时 `POST /mode` 到 CF-Agent，保存 `endpoint | mcp` 状态。
2. **CF-Agent `/chat`** 根据 mode 在 A2A 消息中带上 mode 字段，始终调用 SG-Agent，不直接调用 MCP Server。
3. **SG-Agent 内部分叉**：
   - `endpoint` mode：走现有 card cache 逻辑。
   - `mcp` mode：调用 `stargate-mcp-ui-server` 的 MCP tool call 获取数据，组装 toolResult。
   - 两种 mode 返回统一的 A2A 响应格式（含 `resourceUri`、`toolName`、`toolResult`）。
4. **SG-Agent `/mcp/resources/read` 扩展**：支持 `ui://stargate/employee-trend`，返回纯 shell HTML（不内联数据）。
5. **resource HTML 改造**：两条路径的 resource 均返回纯 shell（Module Federation 引导 + 空 root div），数据通过 `toolResult` 流入。
6. **`employee-chart-card` 改造**：从 `toolResult` 接收数据，支持场景 C 的 `onCallTool`，支持场景 D 的业务接口直调（Bearer token）。
7. **前端 `CardMessage.tsx`**：`toolName` 改从 props 传入，支持传入 `toolResult` prop，场景 B 支持异步加载。

---

## Architecture

### 服务端口一览

| 服务 | 端口 | 说明 |
|---|---|---|
| codeflicker-frontend | 3000 | React 前端（Vite） |
| stargate-agent | 3001 | SG-Agent 主服务（FastAPI） |
| codeflicker-agent | 3002 | CF-Agent（FastAPI） |
| resource-center-mock | 3003 | 资源中心模拟（Express） |
| employee-chart-card | 3004 | MF 远程组件（Webpack） |
| stargate-mcp-ui-server | 3005 | MCP Server（FastMCP SSE） |
| stargate-agent A2A | 3011 | SG-Agent A2A 服务（Flask） |

---

### A2A 响应统一格式（改造后）

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

---

### 四个场景的完整数据流

#### 场景 A：A2A 响应直接带 toolResult

```
用户发消息
  → CF-Agent POST /chat（带 mode）
  → A2A → SG-Agent（根据 mode 走 card cache 或 stargate-mcp-ui-server）
  → SG-Agent 组装 toolResult（含 data + token）
  → A2A 响应带完整 toolResult
  → CF-Agent 透传给前端
  → 前端 AppRenderer toolResult prop 传入
  → guest UI 收到 ui/notifications/tool-result，直接渲染图表
```

#### 场景 B：shell 先渲染，数据异步加载

```
用户发消息
  → SG-Agent 响应只含 resourceUri + toolName，不含 toolResult
  → 前端先渲染 shell（显示 loading 状态）
  → 前端异步 POST /tool-result 到 CF-Agent
  → CF-Agent 调 SG-Agent 获取数据
  → 前端收到数据，通过 AppRenderer ref.sendToolResult() 推入 guest UI
  → guest UI 数据就绪，渲染图表
```

#### 场景 C：guest UI 通过 onCallTool 触发重新获取

```
用户在 guest UI 内交互（如切换年份范围）
  → guest UI 发起 tools/call 请求
  → AppRenderer onCallTool 回调触发
  → 前端 POST /tool-call 到 CF-Agent
  → CF-Agent → A2A → SG-Agent → 返回新 toolResult
  → guest UI 收到新数据，重新渲染
```

#### 场景 D：guest UI 直接调业务接口（Agent 不感知）

```
用户点击图表某年柱形查看详情
  → guest UI 直接 GET http://localhost:3001/api/employee/detail/{year}
    （Authorization: Bearer mock-stargate-token-12345）
  → SG-Agent 验证 token，返回详情数据
  → guest UI 自行渲染详情，CF-Agent 完全不感知
```

---

### 两条路径对比（改造后）

| | Endpoint 路径 | MCP Server 路径 |
|---|---|---|
| 前端开关 | `mode=endpoint` | `mode=mcp` |
| CF-Agent `/chat` | A2A 消息带 `mode=endpoint` | A2A 消息带 `mode=mcp` |
| SG-Agent 内部逻辑 | card cache + resource-center-mock | 调 stargate-mcp-ui-server MCP tool |
| resourceUri | `ui://stargate/card/{id}` | `ui://stargate/employee-trend` |
| resource HTML | 纯 shell（不含数据） | 纯 shell（不含数据） |
| toolResult 数据来源 | card cache 里的 props | stargate-mcp-ui-server tool call 结果 |
| `/resource-proxy` | → SG-Agent `/mcp/resources/read` | → SG-Agent `/mcp/resources/read` |
| SG-Agent `/mcp/resources/read` | `card/{id}` → card cache | `employee-trend` → stargate-mcp-ui-server |

---

### 变更清单

#### `stargate-mcp-ui-server`
- `tools.py`：`build_html()` 改为返回纯 shell HTML（去掉内联数据），新增 `build_tool_result()` 返回结构化数据。
- `main.py`：`query_employee_trend` tool 返回格式包含 `_meta.ui.resourceUri` + `toolResult`（data + token）。

#### `stargate-agent`
- `main.py` A2A handler：新增 `mode` 参数解析；`mcp` mode 下通过 MCP client 调用 stargate-mcp-ui-server tool call，将结果组装为统一 A2A 响应格式。
- `main.py` `/mcp/resources/read`：扩展支持 `ui://stargate/employee-trend` URI，返回纯 shell HTML（从 stargate-mcp-ui-server resource 获取）。

#### `codeflicker-agent`
- `main.py`：新增全局变量 `current_mode = "endpoint"`；新增 `POST /mode` 接口；`/chat` A2A 消息中带 `mode`；新增 `POST /tool-call` 接口（场景 C）；新增 `POST /tool-result` 接口（场景 B）。

#### `employee-chart-card`
- 改为从 `toolResult` 接收数据（而非 HTML props 内联）。
- 支持点击年份柱形，直接调 `GET /api/employee/detail/{year}` 展示详情（场景 D）。
- 支持通过 MCP `tools/call` 触发重新查询（场景 C）。

#### `codeflicker-frontend`
- `types.ts`：`McpUiResourcePart` 新增 `toolName: string`、`toolResult?: object` 字段。
- `App.tsx`：新增 mode 切换开关 UI，切换时 `POST /mode`；解析 parts 时透传 `toolName` 和 `toolResult`。
- `CardMessage.tsx`：`toolName` 改为从 props 传入；支持 `toolResult` prop 传给 `AppRenderer`；场景 B 支持异步加载逻辑（通过 `AppRenderer` ref 的 `sendToolResult()`）。

---

### AppRenderer 关键 Props 对应关系

| 场景 | 关键 Props |
|---|---|
| 场景 A | `toolResourceUri` + `toolResult`（首渲即有数据） |
| 场景 B | `toolResourceUri`（先渲染），之后通过 `ref.sendToolResult()` 推数据 |
| 场景 C | `onCallTool` 回调处理 guest UI 的 tools/call 请求 |
| 场景 D | `onReadResource`（shell 获取）+ guest UI 自行调业务接口 |

---

### 鉴权设计（场景 D）

- token 由 SG-Agent 通过 `POST /api/token/exchange` 生成（当前为 mock：`mock-stargate-token-12345`）。
- token 随 `toolResult` 下发到前端，再由 `AppRenderer` 通过 `toolResult` 注入 guest UI。
- guest UI 持有 token 后，直接在 HTTP 请求头带 `Authorization: Bearer {token}` 调业务接口。
- SG-Agent 业务接口（`/api/employee/detail/{year}` 等）验证 token，无需经过 CF-Agent。

---

### SSE EventLog 可观测性

- CF-Agent `/events` 和 SG-Agent `/events` 均通过 SSE 向前端推送链路事件。
- 前端右侧 EventLog 面板实时展示事件流，便于演示时可视化两条路径的差异。
- 场景 D 的业务接口直调不经过 CF-Agent，在 EventLog 中体现为 SG-Agent 单独的日志条目（无 CF-Agent 转发记录），清晰展示"Agent 不感知"特性。
