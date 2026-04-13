# Architecture Decisions

本文档记录项目关键架构决策，供后续设计和实现参考。

---

## ADR-001：MCP-UI Server 的职责边界

**日期：** 2026-11-04

### 决策

MCP-UI server 的职责是：**当 MCP tool 被调用时，返回一个可渲染的 UIResource**。

UIResource 包含一段 HTML 壳子，放在 tool result 的 `content` 数组中。server 本身不预取业务数据。

### 理由

- MCP-UI 协议只规定 server 返回 `UIResource`（`mimeType: text/html;profile=mcp-app`），不规定数据来源
- 让组件在客户端挂载后自己取数据，server 保持无状态、无数据依赖
- 无状态的 server 可以被多个 agent 共用，不与任何特定 agent 的数据接口耦合

### HTML 壳子的两个职责

每个 tool 的 HTML 壳子自己定义两件事，互不干扰：

1. **怎么获取组件** —— 从哪个地址加载、容器名、组件名
2. **组件怎么获取数据** —— 传什么初始 props、组件内部调哪个接口、如何鉴权

### 正确分层

```
多个 MCP Clients / Agents
         ↓ tools/call
  stargate-mcp-server      ← 通用，只管"返回什么 UI"
         ↓ 生成 HTML 壳子
  UI 组件（运行时加载）     ← 挂载后自己取数据
         ↓ fetch + token
  业务后端数据接口          ← 真实数据来源
```

### 推论

- MCP-UI server 不应持有 card_cache、不应做数据预取
- 若 server 预取数据再内联 HTML，则它与特定 agent 耦合，失去通用性
- `resource-center-mock` 作为 MF 组件注册表，为 MCP-UI server 提供 `remoteEntryUrl`，职责对齐

---

## ADR-002：UI 组件的加载方式

**日期：** 2026-11-04

### 决策

使用**模块联邦（Module Federation）** 作为 HTML 壳子加载 UI 组件的方式。

### 各方案对比

| 方案 | 优势 | 劣势 | 适用场景 |
|------|------|------|----------|
| **模块联邦** | 运行时加载、独立部署、共享依赖（React 只加载一份）、支持私有部署 | 配置复杂、调试困难、强依赖 webpack/rspack 构建体系 | 私有组件、团队自研、需共享依赖 |
| **ESM CDN**（esm.sh / unpkg）| 极简、无需构建、版本固定 | 依赖公网 CDN、私有组件无法发布、无法共享 React 实例 | 快速原型、公开组件库 |
| **iframe（externalUrl）** | 完全隔离、任意技术栈、MCP-UI 协议原生支持 | postMessage 通信复杂、样式尺寸难控制、性能差 | 完全独立的页面级 UI |
| **Web Components** | 原生浏览器支持、框架无关、封装性好 | 与 React/Vue 集成繁琐、Shadow DOM 样式隔离处理麻烦 | 跨框架复用 |

### 选择模块联邦的理由

- `EmployeeChart` 是私有组件，需要部署在内网，无法走公网 CDN
- 组件基于 React，与宿主共享 React 实例可避免重复加载
- 组件需要独立部署、独立更新，MCP-UI server 不应打包组件代码
- `resource-center-mock` 作为组件注册表，提供 `containerName` 和 `remoteEntryUrl`，MCP-UI server 运行时查询即可

---

## ADR-003：新增 stargate-mcp-ui-server

**日期：** 2026-11-04

### 决策

新增独立 Python 服务 `stargate-mcp-ui-server`，作为 **stargate-agent 的专属 MCP Server**，完整实现 MCP-UI 规范（SSE + JSON-RPC）。tool 与 resource 均定义在 mcp-server 内，通过 `_meta.ui.resourceUri` 绑定。

### 理由

stargate-agent 当前通过自定义 HTTP 接口（`GET /mcp/resources/read`）暴露资源，外部 MCP 客户端无法通过标准协议直接订阅和读取 UI Resource。

### 架构模式

各方案对比：

| 方案 | 描述 | 结论 |
|---|---|---|
| **mcp-server 自持 tool（选定）** | tool 和 resource 均在 mcp-server 内，完全遵循 MCP-UI 规范 | 架构清晰，符合规范 |
| Push 模型 | agent 推送 HTML，mcp-server 做缓存层 | 与 MCP-UI tool 模式冲突，放弃 |
| Pull 回调 | mcp-server 收到 tool 调用后反向回调 agent | tool 仍在 agent 侧，架构割裂，放弃 |

### tool 归属

tool 与 resource 均定义在 `stargate-mcp-ui-server` 内，业务数据内联在 mcp-server 中。`stargate-agent` 现有的 `GET /mcp/resources/read` 接口在 mcp-server 上线后逐步废弃。

### 通用化方向（待讨论）

本次 `stargate-mcp-ui-server` 定位为 stargate 专属服务。长远可将其抽象为通用脚手架/模板（暂命名 `mcp-ui-resource-server`），供任意 agent 项目 fork 后注入自己的业务逻辑。**此方向暂不实施，待后续单独讨论。**

