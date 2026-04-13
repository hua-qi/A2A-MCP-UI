# 将 @mcp-ui/server 迁移至 stargate-agent 侧

**Date:** 2026-11-04

## Context

当前项目中，`resource-center-mock` 承担了两个职责：

1. 提供模块联邦（Module Federation）组件的元数据（`containerName`、`remoteEntryUrl` 等）
2. 使用 `@mcp-ui/server`（Node.js）生成 UI Resource，即将业务数据与 MF 加载脚本拼合成完整 HTML

这导致 `stargate-agent` 在处理 MCP `resources/read` 请求时，必须先 HTTP 调用 `resource-center-mock` 的 `/api/ui-resource/:name` 接口才能得到 HTML 内容，业务数据（props、token 等）也因此流经了本不该知道这些数据的 mock 服务。

设计目标是：**让 HTML 生成逻辑归属于真正持有数据的一方——stargate-agent**，`resource-center-mock` 回归其本职，只托管模块联邦静态资源与组件元数据。

## Discussion

**职责边界问题**

讨论了迁移后 `resource-center-mock` 应扮演的角色，最终确定：删除 `/api/ui-resource/:name` 接口，仅保留 `/api/components/:name` 元数据接口，并移除对 `@mcp-ui/server` 的依赖。

**Python SDK 可行性**

确认 PyPI 上存在两个候选包：
- `mcp-ui`（0.1.2）：TypeScript SDK 的 Python 移植，API 与 `@mcp-ui/server` 对齐
- `mcp-ui-server`：额外提供 `wrap_html_with_communication()` 等工具函数

最终选择 **`mcp-ui-server`**，因其工具函数更完整，便于处理 iframe 通信增强等场景。

**方案对比**

| 方案 | 描述 | 结论 |
|---|---|---|
| A：Python 内联实现 | 手动拼 HTML，无外部 SDK 依赖 | 维护成本高，放弃 |
| B：独立 Node.js 微服务 | stargate 旁新增 Node 进程 | 架构复杂，放弃 |
| C：改造 mock 服务 | mock 仍持有业务数据逻辑 | 职责仍不清晰，放弃 |
| **A 升级版（选定）** | stargate 直接使用 `mcp-ui-server` Python 包 | 无额外进程，语言统一，职责清晰 |

## Approach

`stargate-agent` 在处理 MCP `resources/read` 时，直接调用 Python 包 `mcp-ui-server` 的 `create_ui_resource()` 生成 HTML，不再依赖 `resource-center-mock` 生成内容。

`resource-center-mock` 退化为纯粹的"MF 组件注册表"：只告知调用方某个组件叫什么名字、入口文件在哪里，不再参与任何 HTML 渲染或数据处理。

数据流向变化：

```
迁移前：
  stargate read_resource()
    → HTTP POST resource-center-mock /api/ui-resource/EmployeeChart（携带业务数据）
      → @mcp-ui/server createUIResource() → HTML

迁移后：
  stargate read_resource()
    → HTTP GET resource-center-mock /api/components/EmployeeChart（仅获取元数据）
    → mcp_ui_server.create_ui_resource()（本地调用，业务数据留在 stargate 内部）
```

## Architecture

### stargate-agent 变更

**依赖（`pyproject.toml`）**

```toml
dependencies = [
    ...
    "mcp-ui-server>=<latest>",
]
```

**`main.py` 中 `read_resource` 处理器**

```python
from mcp_ui_server import create_ui_resource

async def read_resource(uri: str):
    card = card_cache.get(card_id)

    # 1. 仅从 resource-center-mock 获取组件元数据（containerName、remoteEntryUrl）
    meta = await http.get(f"http://localhost:3003/api/components/{card.component_name}")

    # 2. 本地生成 MF 加载 HTML
    html_string = build_mf_html(
        meta["containerName"],
        meta["remoteEntryUrl"],
        card.props,
    )

    # 3. 调用 Python SDK 构造 UI Resource
    resource = create_ui_resource({
        "uri": uri,
        "content": {"type": "rawHtml", "htmlString": html_string},
        "encoding": "text",
    })
    return resource
```

**`build_mf_html()` 函数**：将原先在 `resource-center-mock` 中的 MF 加载脚本模板（动态 `import()`、ShareScope 初始化、`ReactDOM.createRoot` 等）迁移至 stargate-agent 内部维护。

### resource-center-mock 变更

- **删除** `/api/ui-resource/:name` 路由及其实现
- **删除** `package.json` 中 `@mcp-ui/server` 依赖
- **保留** `/api/components/:name` 路由，返回格式不变：

```json
{
  "componentName": "EmployeeChart",
  "containerName": "employeeChartCard",
  "remoteEntryUrl": "http://localhost:3004/remoteEntry.js"
}
```

### 组件职责对照表

| 组件 | 迁移前职责 | 迁移后职责 |
|---|---|---|
| `resource-center-mock` | 组件元数据 + HTML 生成（含业务数据） | 仅组件元数据（MF 注册表） |
| `stargate-agent` | 调用 mock 获取 HTML | 自持业务数据，本地生成 HTML |
| `employee-chart-card` | MF 远程组件（不变） | 不变 |
| `codeflicker-frontend` | 渲染卡片（不变） | 不变 |
