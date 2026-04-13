# A2A + MCP-UI 多 Agent Demo 设计方案

**Date:** 2026-04-10

---

## Context

在多 Agent 协作架构下，实现从用户对话到前端渲染模块联邦 UI 组件的完整技术验证链路。具体业务场景为：用户在 CodeFlicker 前端查询「快手近5年员工数量趋势」，CodeFlicker Agent 通过 A2A 协议委托 Stargate Agent 完成查询，Stargate 返回业务数据并携带 MCP-UI 资源标识，前端最终通过模块联邦加载并渲染趋势图卡片。

核心目标是**技术验证**：验证 A2A 协议、MCP-UI、模块联邦、多 Agent 协作的完整链路能够跑通。

---

## Discussion

### 关键决策

| 问题 | 选项 | 最终决策 |
|---|---|---|
| Demo 目标 | 技术验证 / 对外演示 / 参考实现 | **技术验证** |
| Agent 是否接入真实 LLM | 真实 LLM / Mock | **真实 LLM** |
| 业务场景 | 项目查询 / 商品列表 / 自定义 | **快手员工数量趋势** |
| 渲染方案 | HTML片段(iframe srcdoc) / 模块联邦完整链路 / 简化版(跳过token) | **模块联邦完整链路** |
| A2A 协议实现程度 | 标准协议 / 简化实现 | **标准 A2A 协议**（Task/Artifact/streaming）|
| MCP 连接方式 | 标准 MCP 客户端连接 / SDK 直调 | **标准 MCP 连接**（SSE/stdio）|
| 技术栈 | TypeScript 全栈 / Python Agent + Node.js | **Python Agent + Node.js 前端** |
| LLM 配置 | 硬编码 / 环境变量 | **.env 环境变量**，支持替换 |

### 探索的替代方案

**方案 A（HTML片段）**：Stargate Agent 直接生成内嵌 ECharts 的 rawHtml，用 iframe srcdoc 渲染。优点是链路最简，但无法验证模块联邦这条核心链路，被排除。

**方案 C（跳过 token）**：与完整链路相同，但 mock 掉 token 换取步骤。考虑到 demo 目标是完整技术验证，最终选择保留 token 换取流程（mock 实现）。

---

## Approach

采用模块联邦完整链路方案，5 个子包组成 monorepo：

1. **resource-center-mock**：模拟资源管理中心，存储卡片组件名和 CDN 地址
2. **employee-chart-card**：独立构建的模块联邦卡片组件（趋势折线图）
3. **stargate-agent**：Python 实现，同时作为 MCP-UI Server，处理业务数据和卡片实例管理
4. **codeflicker-agent**：Python 实现，通过 A2A 协作 Stargate，透传 MCP-UI 资源标识，代理 resources/read 请求
5. **codeflicker-frontend**：React 前端，极简对话 UI + AppRenderer + 数据流转记录器

---

## Architecture

### 工程结构

```
A2A-mcpUI/
├── packages/
│   ├── codeflicker-frontend/     # React Web UI（端口 3000）
│   ├── codeflicker-agent/        # CodeFlicker Agent，Python（端口 3002）
│   ├── stargate-agent/           # Stargate Agent + MCP-UI Server，Python（端口 3001）
│   ├── employee-chart-card/      # 模块联邦卡片组件（端口 3004）
│   └── resource-center-mock/     # 资源管理中心 Mock 服务（端口 3003）
```

### A2A 协议扩展结构

在 A2A message 的 `parts` 中新增 `kind: "mcp_ui_resource"` 类型：

```json
{
  "message": {
    "role": "ROLE_AGENT",
    "parts": [
      {
        "data": {
          "kind": "text",
          "text": "2019-2023年快手员工数量如下..."
        }
      },
      {
        "data": {
          "kind": "mcp_ui_resource",
          "resourceUri": "ui://stargate/card/{cardInstanceId}",
          "uiMetadata": {
            "preferred-frame-size": { "width": 600, "height": 400 }
          }
        },
        "mediaType": "application/json"
      }
    ]
  }
}
```

### 各模块职责

**resource-center-mock（端口 3003）**
- 纯静态 mock 数据服务
- `GET /api/components/:name` → `{ componentName, remoteEntryUrl }`

**employee-chart-card（端口 3004）**
- Webpack 5 Module Federation 构建，暴露 `EmployeeChart` 组件
- 接收 props：`{ data: { year, count }[], token }`
- ECharts 渲染折线图
- 支持两种交互：hover 查看详情（直调业务 API）、点击「分析趋势」（postMessage 通知 Agent）

**stargate-agent（端口 3001）**
- Python 实现，同时作为 MCP-UI Server（SSE 模式）
- 注册 Tool：`query_employee_trend({ year_range })`
  - 生成 mock 员工数据
  - 查询 resource-center-mock 拿 CDN 地址
  - 生成 cardInstanceId，写入缓存
  - 返回 `_meta.ui.resourceUri: ui://stargate/card/{id}`
- 注册 Resource handler：`ui://stargate/card/:id` → 返回 `{ componentName, remoteEntryUrl, props }`
- HTTP 接口：
  - `GET /api/card-instance/:id`：返回卡片数据
  - `POST /api/token/exchange`：mock token 换取 → 返回 stargateToken
  - `GET /api/employee/detail/:year`：卡片内业务 API

**codeflicker-agent（端口 3002）**
- Python 实现，标准 MCP 客户端连接 Stargate MCP-UI Server
- 接收前端对话 → LLM 意图识别 → A2A Task 调用 Stargate
- 透传 `mcp_ui_resource` part，不做额外处理
- 提供 `GET /resource-proxy?uri=` 代理接口：按 uri host 路由到对应下游 Agent 的 resources/read

**codeflicker-frontend（端口 3000）**
- 极简对话列表：文本气泡 vs 卡片消息视觉区分
- 检测 `mcp_ui_resource` part → 使用 `AppRenderer`
- `AppRenderer.onReadResource` 指向 codeflicker-agent 代理接口
- SDK 串行流程：拉取 cardInstance → 换取 stargateToken → MF 动态加载 → 渲染组件
- 右侧固定 panel：数据流转记录器（SSE 收集各服务日志实时展示）

### 完整业务时序

```
用户输入 "查询快手近5年员工数量趋势"
  → [CF-Frontend] POST /chat → [CF-Agent]
  → [CF-Agent] LLM 意图识别 → A2A Task → [SG-Agent]
  → [SG-Agent] LLM 选择 tool → query_employee_trend({ year_range: "2019-2023" })
  → [SG-Agent] GET /api/components/EmployeeChart → [Resource Center]
  → [SG-Agent] 生成 mock 数据 + cardInstanceId 写缓存
  → [SG-Agent] A2A Response: [ text part, mcp_ui_resource part ]
  → [CF-Agent] 透传 parts → [CF-Frontend]
  → [CF-Frontend] 渲染 text 气泡 + 触发 AppRenderer
  → [CF-Frontend] GET /resource-proxy?uri=ui://stargate/card/{id} → [CF-Agent]
  → [CF-Agent] 路由 → [SG-Agent] resources/read → 返回 { componentName, remoteEntryUrl, props }
  → [CF-Frontend] POST /api/token/exchange → [SG-Agent] → stargateToken
  → [CF-Frontend] 动态加载 remoteEntry.js（MF）
  → 渲染 <EmployeeChart data={props} token={stargateToken} />
```

### 卡片内两种交互路径

**路径 A：普通业务交互（直调 Stargate API）**
```
用户 hover 某年 → EmployeeChart
  → GET /api/employee/detail/:year（携带 stargateToken）
  → [SG-Agent] 返回详情数据
  → 卡片内更新 tooltip
```

**路径 B：触发 Agent 推理（postMessage）**
```
用户点击「分析趋势」→ EmployeeChart
  → postMessage({ type: "agent_submit", payload: "分析趋势" })
  → [AppRenderer/SDK] 新一轮对话 → [CF-Agent] → A2A → [SG-Agent]
  → LLM 生成分析文本
  → 返回新 text part → 前端渲染新文本气泡
```

### 数据流转记录器

各服务通过 SSE 向前端推送结构化日志，前端右侧 panel 实时展示：

```
[时间]  来源系统 → 目标系统      消息类型        摘要
────────────────────────────────────────────────────────
12:01  Frontend  → CF-Agent     chat            "查询快手近5年..."
12:01  CF-Agent  → LLM          llm-call        intent detection
12:01  CF-Agent  → SG-Agent     A2A             Task: query_employee_trend
12:01  SG-Agent  → LLM          llm-call        tool selection
12:01  SG-Agent  → Resource     http            GET /components/EmployeeChart
12:01  SG-Agent  → CF-Agent     A2A             Response: text + mcp_ui_resource
12:01  CF-Agent  → Frontend     chat-resp       透传 parts
12:01  Frontend  → CF-Agent     resource-proxy  ui://stargate/card/xxx
12:01  CF-Agent  → SG-Agent     resources/read  proxy
12:01  Frontend  → SG-Agent     token           POST /token/exchange
12:01  Frontend  → CDN          mf-load         remoteEntry.js
```

### 鉴权设计

| 链路 | 处理方式 |
|---|---|
| CF 系统鉴权 | demo 中暂不实现 |
| Stargate token 换取 | `POST /api/token/exchange` mock 返回固定 token |
| 卡片调业务 API 鉴权 | 携带 stargateToken，Stargate 侧 mock 验证 |
| 资源管理中心鉴权 | Stargate 侧内部消化，CF 无感知 |
| cardInstanceId TTL | demo 中设置为 1小时，不实现刷新机制 |
