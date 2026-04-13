# MCP UI 协议总结

> 来源：https://mcpui.dev/guide/server/typescript/usage-examples

## 概述

MCP UI（Model Context Protocol UI）是在 MCP 基础上扩展的 UI 层协议，允许 MCP Server 向客户端返回可渲染的 UI 资源，实现工具与界面的绑定。

---

## 核心 API：`createUIResource`

用于创建 UI 资源对象，URI 必须以 `ui://` 开头。

### 内容类型（Content Type）

| 类型 | 说明 |
|---|---|
| `rawHtml` | 直接传入 HTML 字符串 |
| `externalUrl` | 传入外部 URL，服务端获取页面 HTML 并注入 `<base>` 标签 |

### 编码方式（Encoding）

| 类型 | 说明 |
|---|---|
| `text` | 直接文本传输 |
| `blob` | Base64 编码传输 |

---

## 元数据配置

### `metadata`
标准 MCP 资源信息：标题、描述、时间戳等。

### `uiMetadata`
客户端渲染提示：
- `preferred-frame-size`：建议的渲染框架尺寸
- `initial-render-data`：初始渲染数据

### `embeddedResourceProps`
MCP 嵌入资源属性（如 `annotations`）。

---

## 推荐模式：MCP Apps

使用 `registerAppTool` + `_meta.ui.resourceUri` 将工具与 UI 绑定。

### 核心流程

1. 使用 `McpServer` 创建服务器
2. 通过 `createUIResource` 创建 UI 资源
3. 用 `registerAppResource` 注册资源处理器
4. 用 `registerAppTool` 注册工具，在 `_meta.ui.resourceUri` 中指定对应的 `ui://` URI

### HTML 端通信

在 HTML 中使用 `@modelcontextprotocol/ext-apps` 的 `App` 类与宿主（Host）进行双向通信。

---

## 错误处理

- URI 不以 `ui://` 开头时，系统抛出错误：`URI must start with 'ui://'`

---

## 安装

```bash
npm i @mcp-ui/server @modelcontextprotocol/ext-apps
```

---

## 协议定位

MCP UI 是对 MCP 协议的 UI 层扩展，专注于让 MCP 工具能够携带可视化界面返回，适用于需要富交互界面的 AI 工具场景。

---

## MCP Apps、MCP-UI 与 MCP App 的关系

| 层级 | 名称 | 本质 | npm 包 |
|---|---|---|---|
| 协议层 | **MCP Apps** | 定义 Host ↔ iframe postMessage 通信规范，以及 MCP Server 注册 UI 资源的标准 | `@modelcontextprotocol/ext-apps` |
| SDK 层 | **MCP-UI** | 对 MCP Apps 协议的封装，提供更易用的开发工具 | `@mcp-ui/client` / `@mcp-ui/server` |
| 应用层 | **MCP App** | 基于上述协议/SDK 开发出来的具体 iframe UI 应用 | 开发者自己写 |

一句话总结：**MCP Apps 是协议，MCP-UI 是实现该协议的 SDK，MCP App 是用这套协议/SDK 开发出来的产物。**

---

## Host 定义

Host 是指**运行对话、管理 iframe 生命周期的宿主应用**，即 Web UI 这一侧。

核心职责：
- 创建并管理沙箱 iframe（Guest）
- 通过 postMessage 向 iframe 推送 `tool-input` / `tool-result`
- 接收 iframe 发来的 `tools/call`、`ui/message` 等请求并处理

在多 Agent 架构中，Host = **Web UI + Agent** 共同构成的宿主环境，iframe 内运行的 MCP App 是 Guest。
