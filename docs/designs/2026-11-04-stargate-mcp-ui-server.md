# stargate-mcp-ui-server 设计文档

**Date:** 2026-11-04

## Context

在完成「将 @mcp-ui/server 迁移至 stargate-agent 侧」之后，stargate-agent 已能在本地生成 MCP UI Resource HTML。但 stargate-agent 当前通过自定义 HTTP 接口（`GET /mcp/resources/read`）暴露资源，并未运行标准 MCP 协议（SSE + JSON-RPC）。

外部 MCP 客户端无法通过标准 MCP 协议直接订阅和读取这些 UI Resource。

## Discussion

**通用性边界**

讨论了是否将 MCP Server 做成通用中间层。结论是：

> MCP-UI 规范的意图是一个 MCP Server 同时注册 tool + resource，两者通过 `_meta.ui.resourceUri` 绑定，这个 server 本身就是业务 server，不存在纯通用中间层。

因此本次 `stargate-mcp-ui-server` 定位为 **stargate-agent 的专属 MCP Server**，不追求跨 agent 通用性。

**Push 模型 vs MCP-UI 规范 tool 模式**

初期探索了 Push 模型（agent 创建卡片后主动推送 HTML 到 mcp-server），但与 MCP-UI 规范存在根本冲突：

- MCP-UI 规范要求 tool 与 resource 通过 `_meta.ui.resourceUri` 绑定，tool 被调用时直接生成并返回 UIResource
- Push 模型要求 agent 感知 mcp-server 的存在，tool 在 agent 侧执行，mcp-server 仅做缓存中转
- 两者在 tool 执行位置上自相矛盾

各方案对比：

| 方案 | 描述 | 结论 |
|---|---|---|
| **mcp-server 自持 tool（选定）** | tool 和 resource 均定义在 mcp-server 内，完全遵循 MCP-UI 规范 | 架构清晰，符合规范 |
| Push 模型 | agent 推送 HTML，mcp-server 做缓存层 | 与 MCP-UI tool 模式冲突，放弃 |
| Pull 回调 | mcp-server 收到 tool 调用后反向回调 agent | tool 仍在 agent 侧，架构割裂，放弃 |

**Resource URI：静态 vs 动态**

| 方案 | 描述 | 结论 |
|---|---|---|
| **静态 URI（选定）** | 每次 tool 调用返回同一 URI，内容覆盖 | 简单，符合大多数 MCP-UI 示例 |
| 动态 URI | 每次生成唯一 URI，需 store 缓存多份 | 引入 TTL 管理复杂度，仅多会话并发场景需要 |

**tool 归属**

tool 与 resource 均定义在 `stargate-mcp-ui-server` 内，业务数据（员工趋势等）内联在 mcp-server 中，不再依赖 stargate-agent 提供数据。

**stargate-agent 的 MCP 相关逻辑**

`stargate-agent` 现有的 `GET /mcp/resources/read` 接口及 `card_cache` 中与 MCP 相关的部分，在 `stargate-mcp-ui-server` 上线后可逐步废弃。

**脚手架方向（待讨论）**

长远可将 `stargate-mcp-ui-server` 抽象为可复用脚手架，暂命名 `mcp-ui-resource-server`，供任意 agent 项目 fork 后注入自己的业务逻辑。**此方向暂不实施，待后续单独讨论。**

## Approach

新增独立 Python 服务 `stargate-mcp-ui-server`（端口 3002），完整实现 MCP-UI 规范：

- 使用 `mcp[server]` SDK 运行标准 MCP 协议（SSE 传输）
- 使用 `mcp_ui_server` Python 包的 `create_ui_resource()` 构建 UIResource
- tool 与 resource 绑定通过 `_meta.ui.resourceUri` 实现
- resource URI 为静态，每次 tool 调用覆盖同一份内容，无需缓存层

数据流：

```
MCP 客户端
  → GET /sse（建立 SSE 长连接）
  → tools/call query_employee_trend
      → tool handler 内联业务数据，生成 HTML
      → create_ui_resource() 构建 UIResource
      → 返回 { _meta: { ui: { resourceUri: "ui://stargate/employee-trend" } }, content: [...] }
  → resources/read "ui://stargate/employee-trend"
      → resource handler 重新生成并返回 UIResource
```

## Architecture

### 目录结构

```
packages/
  stargate-mcp-ui-server/
    pyproject.toml
    src/
      stargate_mcp_ui_server/
        __init__.py
        main.py       ← MCP Server（SSE）入口，tool/resource 注册
        tools.py      ← tool handler 实现（业务数据 + HTML 生成）
```

### MCP 协议端点

```
GET  /sse       ← MCP 客户端建立 SSE 长连接
POST /messages  ← MCP JSON-RPC（tools/call、resources/read、resources/list 等）
```

### tool 与 resource 绑定（Python，遵循 MCP-UI 规范）

```python
from mcp_ui_server import create_ui_resource

RESOURCE_URI = "ui://stargate/employee-trend"

@server.tool("query_employee_trend", meta={"ui": {"resourceUri": RESOURCE_URI}})
async def query_employee_trend():
    resource = create_ui_resource({
        "uri": RESOURCE_URI,
        "content": {"type": "rawHtml", "htmlString": build_html()},
        "encoding": "text",
    })
    return resource

@server.resource(RESOURCE_URI)
async def employee_trend_resource():
    resource = create_ui_resource({
        "uri": RESOURCE_URI,
        "content": {"type": "rawHtml", "htmlString": build_html()},
        "encoding": "text",
    })
    return resource
```

### 服务职责对照表

| 服务 | 职责 |
|---|---|
| `stargate-mcp-ui-server` | 标准 MCP 协议、tool 定义、UIResource 生成 |
| `stargate-agent` | A2A 协议、`/mcp/resources/read` 接口（逐步废弃） |
| `resource-center-mock` | MF 组件元数据注册表（不变） |
