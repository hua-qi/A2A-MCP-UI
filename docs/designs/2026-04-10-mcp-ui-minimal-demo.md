# MCP-UI 最小验证 Demo

**Date:** 2026-04-10

## Context

在已有 A2A + MCP-UI 整体架构设计的基础上，需要落地一个可运行的技术验证 Demo，目标是跑通从用户输入 → A2A 协议 → MCP-UI → 模块联邦卡片渲染的完整链路。核心价值是技术验证：确认各协议层、各服务之间的集成能够端到端工作。

## Discussion

### 关键决策

| 问题 | 选项 | 最终决策 |
|---|---|---|
| Demo 目标 | 跑通链路 / 对外演示 / 性能基准 | **跑通链路（技术验证）** |
| 实现范围 | 全量实现 / 最小化 / HTML片段替代MF | **全量实现** |
| Agent 技术栈 | Python / TypeScript 全栈 / Mock | **Python Agent** |
| LLM 接入 | 全部真实 / 仅 CF-Agent / 全 Mock | **两个 Agent 均接入真实 LLM** |
| A2A 协议实现 | 官方 a2a-sdk / 自行实现 / HTTP REST 替代 | **官方 `python-a2a` SDK** |
| resources/read 路由 | 前端直连 SG-Agent / 经 CF-Agent 代理 | **前端 → CF-Agent `/resource-proxy` → SG-Agent** |
| 数据流转记录器 | 保留 / 去掉 | **MVP 中保留** |

### 探索的替代方案

- **HTML 片段方案**：SG-Agent 直接返回内嵌 ECharts 的 rawHtml，用 iframe srcdoc 渲染。链路最简，但无法验证模块联邦这条核心链路，排除。
- **Mock LLM 方案**：两个 Agent 工具选择均 mock。考虑到验证目标包含意图识别和工具调用能力，保留真实 LLM。
- **TypeScript 全栈**：前后端统一语言，但与设计文档既定方向不符，排除。

## Approach

采用 5 子包 monorepo，Python Agent + React 前端全量实现设计文档中的完整链路。两个 Agent 均接入真实 LLM（通过 `.env` 环境变量配置），A2A 层使用官方 `python-a2a` SDK，资源代理统一经由 CF-Agent 中转，前端保留数据流转记录器以直观展示调用链路。

## Architecture

### 工程结构

```
A2A-mcpUI/
├── packages/
│   ├── codeflicker-frontend/      # React Web UI，端口 3000
│   ├── codeflicker-agent/         # Python，端口 3002
│   ├── stargate-agent/            # Python，端口 3001
│   ├── employee-chart-card/       # Webpack5 MF 卡片，端口 3004
│   └── resource-center-mock/      # 纯 mock HTTP 服务，端口 3003
├── package.json                   # monorepo root（pnpm workspaces）
└── .env                           # LLM key 统一管理
```

### 服务依赖启动顺序

```
resource-center-mock (3003)   employee-chart-card (3004)
         ↑                              ↑
    stargate-agent (3001) ←─────────────
         ↑
  codeflicker-agent (3002)
         ↑
  codeflicker-frontend (3000)
```

启动命令：`pnpm dev`（并发启动，内部健康检查保证顺序就绪）

### 完整调用链路

```
用户输入
  │
  ▼
[CF-Frontend] POST /chat
  │
  ▼
[CF-Agent] LLM 意图识别
  │ python-a2a A2A Task
  ▼
[SG-Agent] LLM 工具选择 → query_employee_trend
  │ GET /api/components/EmployeeChart
  ▼
[resource-center-mock] 返回 { componentName, remoteEntryUrl }
  │ 生成 cardInstanceId 写缓存
  ▼
[SG-Agent] A2A Response: [text part + mcp_ui_resource part]
  │ CF-Agent 透传，不做额外处理
  ▼
[CF-Frontend] 渲染文本气泡 + 触发 AppRenderer
  │ onReadResource → GET /resource-proxy?uri=ui://stargate/card/:id
  ▼
[CF-Agent] MCP resources/read → [SG-Agent]
  │ 返回 { componentName, remoteEntryUrl, props }
  ▼
[CF-Frontend] POST /api/token/exchange → stargateToken
  │ 动态加载 remoteEntry.js（MF，端口 3004）
  ▼
渲染 <EmployeeChart data={props} token={stargateToken} />
```

### Stargate Agent（端口 3001）

同时承担 **A2A Agent** 和 **MCP-UI Server（SSE 模式）** 两个角色。

**关键接口：**

| 接口 | 说明 |
|---|---|
| A2A Task 入口 | LLM 工具选择 → `query_employee_trend` → 生成数据 + cardInstanceId |
| MCP Tool | `query_employee_trend`，返回 `_meta.ui.resourceUri` |
| MCP Resource | `ui://stargate/card/:id` → `{ componentName, remoteEntryUrl, props }` |
| `GET /api/card-instance/:id` | 返回卡片数据 |
| `POST /api/token/exchange` | mock 换取 stargateToken |
| `GET /api/employee/detail/:year` | 卡片内业务 API，携带 stargateToken 鉴权 |
| `GET /events` | SSE，推送结构化日志给前端数据流转记录器 |

### CodeFlicker Agent（端口 3002）

**关键接口：**

| 接口 | 说明 |
|---|---|
| `POST /chat` | LLM 意图识别 → A2A Task → SG-Agent → 透传 parts 给前端 |
| `GET /resource-proxy?uri=` | 解析 uri host，路由到对应 Agent 的 MCP resources/read |
| `GET /events` | SSE，推送结构化日志 |

### 前端（端口 3000）

**三区域布局：**

- **对话列表区**：文本气泡 + `<AppRenderer>` 卡片消息，视觉区分
- **输入框**：发送消息
- **右侧 Panel（数据流转记录器）**：订阅所有服务 `/events` SSE，实时展示调用链路

**AppRenderer 配置：**

```tsx
<AppRenderer
  client={mcpClient}
  toolName="query_employee_trend"
  sandbox={{ url: '/sandbox_proxy.html' }}
  toolInput={toolInput}
  toolResult={toolResult}
  onReadResource={({ uri }) => fetch(`/resource-proxy?uri=${uri}`)}
  onOpenLink={async ({ url }) => { window.open(url); return { isError: false }; }}
  onMessage={async (params) => { return { isError: false }; }}
/>
```

### 卡片组件（Webpack5 MF，端口 3004）

```javascript
// webpack.config.js
exposes: { './EmployeeChart': './src/EmployeeChart' }

// Props 接口
{ data: { year: number, count: number }[], token: string }
```

**两种交互路径：**

| 路径 | 触发方式 | 处理方 |
|---|---|---|
| 路径 A：普通业务交互 | Hover 查看年份详情 | 卡片直调 `GET /api/employee/detail/:year`（携带 stargateToken） |
| 路径 B：触发 Agent 推理 | 点击「分析趋势」按钮 | `postMessage({ type: 'agent_submit' })` → AppRenderer → CF-Agent → 新一轮对话 |

### 数据流转记录器日志格式

```
[时间]  来源          → 目标              消息类型
──────────────────────────────────────────────────────
12:01  Frontend       → CF-Agent          chat: "查询快手..."
12:01  CF-Agent       → LLM               llm-call: intent detection
12:01  CF-Agent       → SG-Agent          A2A Task
12:01  SG-Agent       → LLM               llm-call: tool selection
12:01  SG-Agent       → ResourceCenter    http: GET /components
12:01  SG-Agent       → CF-Agent          A2A Response: mcp_ui_resource
12:01  Frontend       → CF-Agent          resource-proxy
12:01  CF-Agent       → SG-Agent          MCP resources/read
12:01  Frontend       → SG-Agent          token/exchange
12:01  Frontend       → CDN(3004)         MF load: remoteEntry.js
12:01  Frontend       → ─                 card rendered ✓
```

### 环境变量

```
OPENAI_API_KEY=xxx
OPENAI_BASE_URL=xxx
LLM_MODEL=gpt-4o
```

### 鉴权策略（Demo 简化）

| 链路 | 处理方式 |
|---|---|
| CF 系统鉴权 | Demo 中不实现 |
| Stargate token 换取 | `POST /api/token/exchange` mock 返回固定 token |
| 卡片调业务 API | 携带 stargateToken，SG-Agent 侧 mock 验证 |
| cardInstanceId TTL | 设置为 1 小时，不实现刷新机制 |
