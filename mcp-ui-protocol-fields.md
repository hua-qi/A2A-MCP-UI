# MCP-UI 协议完整字段解析

> 来源：https://mcpui.dev/guide/introduction  
> 版本：当前稳定版

## 一、顶层架构总览

```
Server 侧
  └── createUIResource()     → 生成 UIResource 对象
  └── registerAppResource()  → 注册资源处理器
  └── registerAppTool()      → 注册工具，通过 _meta.ui.resourceUri 绑定 UI

Client 侧
  └── AppRenderer            → 高层组件，自动拉取并渲染 UI
  └── AppFrame               → 低层组件，需自行管理 HTML 和 AppBridge

通信层（Host ↔ Guest iframe）
  └── JSON-RPC over postMessage
```

---

## 二、UIResource（核心数据结构）

MCP-UI 在传输层的完整数据结构：

```typescript
interface UIResource {
  type: 'resource';
  resource: {
    uri: string;                          // ui:// 开头的资源标识
    mimeType: 'text/html;profile=mcp-app'; // 固定值
    text?: string;                        // encoding: 'text' 时的 HTML 内容
    blob?: string;                        // encoding: 'blob' 时的 Base64 内容
    _meta?: object;                       // 元数据
  };
}
```

### UIResource 字段说明

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `type` | `"resource"` | 是 | 固定值 |
| `resource.uri` | string | 是 | 格式：`ui://<component-name>/<instance-id>` |
| `resource.mimeType` | string | 是 | 固定值 `"text/html;profile=mcp-app"` |
| `resource.text` | string | 二选一 | encoding 为 `text` 时的 HTML 字符串 |
| `resource.blob` | string | 二选一 | encoding 为 `blob` 时的 Base64 编码 HTML |
| `resource._meta` | object | 否 | 附加元数据 |

---

## 三、createUIResource 参数

Server 端生成 UIResource 的函数入参：

```typescript
createUIResource({
  uri: 'ui://my-server/widget',

  content: {
    type: 'rawHtml',
    htmlString: '<html>...</html>',
  },
  // 或
  content: {
    type: 'externalUrl',
    iframeUrl: 'https://my-server.com/widget',
  },

  encoding: 'text',  // 或 'blob'

  metadata: {
    title: 'My Widget',
    description: '...',
    created: '2026-09-04T00:00:00Z',
    author: 'dev',
    preferredRenderContext: 'inline',
  },

  uiMetadata: {
    'preferred-frame-size': ['800px', '600px'],
    'initial-render-data': { key: 'value' },
  },

  embeddedResourceProps: {
    annotations: { ... },
  },

  adapters: {
    mcpApps: {
      enabled: true,
      config: {
        timeout: 30000,
      },
    },
  },
})
```

### 参数字段说明

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `uri` | string | 是 | 必须以 `ui://` 开头，否则抛出错误 |
| `content.type` | `"rawHtml"` \| `"externalUrl"` | 是 | 内容来源类型 |
| `content.htmlString` | string | rawHtml 必填 | 直接传入的 HTML 字符串 |
| `content.iframeUrl` | string | externalUrl 必填 | 外部 URL，自动注入 `<base>` 标签 |
| `encoding` | `"text"` \| `"blob"` | 是 | text=直接传输，blob=Base64 编码 |
| `metadata.title` | string | 否 | 资源标题 |
| `metadata.description` | string | 否 | 资源描述 |
| `metadata.created` | string | 否 | 创建时间 |
| `metadata.author` | string | 否 | 作者 |
| `metadata.preferredRenderContext` | string | 否 | 建议渲染上下文 |
| `uiMetadata['preferred-frame-size']` | string[] | 否 | 建议的 iframe 尺寸 `[width, height]` |
| `uiMetadata['initial-render-data']` | object | 否 | 初始渲染数据 |
| `embeddedResourceProps.annotations` | object | 否 | MCP 嵌入资源注解 |
| `adapters.mcpApps.enabled` | boolean | 否 | 是否启用 MCP Apps 适配器 |
| `adapters.mcpApps.config.timeout` | number | 否 | 超时时间，默认 30000ms |

---

## 四、Tool 的 _meta 字段

工具与 UI 资源的绑定配置：

```typescript
{
  name: 'show_widget',
  description: '...',
  inputSchema: { ... },
  _meta: {
    ui: {
      resourceUri: 'ui://my-server/widget'
    }
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `_meta.ui.resourceUri` | string | 指向对应 UIResource 的 `ui://` URI |

---

## 五、Host → Guest 通知消息（postMessage）

Host（宿主页面）向 Guest（iframe）发送的通知：

| 方法 | 说明 | Payload |
|---|---|---|
| `ui/notifications/tool-input` | 完整工具参数 | `{ toolInput: any }` |
| `ui/notifications/tool-input-partial` | 流式部分参数 | `{ toolInput: any }` |
| `ui/notifications/tool-result` | 工具执行结果 | `{ toolResult: CallToolResult }` |
| `ui/notifications/host-context-changed` | 主机上下文变化 | `McpUiHostContext` |
| `ui/notifications/size-changed` | 尺寸约束通知 | `{ maxHeight?: number }` |
| `ui/notifications/tool-cancelled` | 工具执行被取消 | `{}` |
| `ui/resource-teardown` | 销毁前通知 | `{}` |

### McpUiHostContext 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `theme` | `"light"` \| `"dark"` \| `"system"` | 主题 |
| `locale` | string | 语言，如 `"zh-CN"` |
| `displayMode` | `"inline"` \| `"fullscreen"` \| `"pip"` | 显示模式 |
| `maxHeight` | number | 最大高度限制 |

---

## 六、Guest → Host 请求消息（postMessage）

Guest（iframe）向 Host 发送的请求：

| 方法 | 说明 | Payload |
|---|---|---|
| `tools/call` | 调用其他 MCP 工具 | `{ toolName: string, params: object }` |
| `ui/message` | 发送后续消息到会话 | `{ role, content }` |
| `ui/open-link` | 在新标签页打开 URL | `{ url: string }` |
| `notifications/message` | 向主机记录日志 | `{ message: string }` |
| `ui/notifications/size-changed` | 请求调整组件尺寸 | `{ height: number }` |

### postMessage 消息结构

```javascript
// 基础消息（fire-and-forget）
{ type: 'tool', payload: { toolName, params } }

// 异步消息（需要响应）
{ type: 'tool', messageId: 'unique-id', payload: { toolName, params } }

// Host 确认
{ type: 'ui-message-received', messageId: 'unique-id' }

// Host 成功响应
{ type: 'ui-message-response', messageId: 'unique-id', payload: { response: {...} } }

// Host 错误响应
{ type: 'ui-message-response', messageId: 'unique-id', payload: { error: {...} } }
```

### Widget 发送消息类型（Legacy 兼容）

| type | 说明 | payload |
|---|---|---|
| `prompt` | 发送提示消息 | `{ prompt: string }` |
| `link` | 打开外部链接 | `{ url: string }` |
| `tool` | 调用 MCP 工具 | `{ toolName: string, params: object }` |
| `notify` | 发送日志通知 | `{ message: string }` |
| `intent` | 发送意图 | `{ ... }` |
| `ui-size-change` | 请求调整尺寸 | `{ height: number }` |
| `ui-lifecycle-iframe-ready` | iframe 就绪信号 | `{}` |

---

## 七、AppRenderer Props（客户端组件）

### 核心 Props

| Prop | 类型 | 必填 | 说明 |
|---|---|---|---|
| `client` | `Client` | 否 | MCP 客户端实例，用于自动拉取资源 |
| `toolName` | string | 否 | 要渲染 UI 的工具名称 |
| `sandbox` | `SandboxConfig` | 否 | 沙箱配置，含代理 URL 和 CSP |
| `html` | string | 否 | 预加载的 HTML，跳过资源拉取 |
| `toolResourceUri` | string | 否 | 预设的资源 URI |
| `toolInput` | `Record<string, unknown>` | 否 | 传给 Guest 的工具入参 |
| `toolResult` | `CallToolResult` | 否 | 传给 Guest 的工具执行结果 |
| `toolInputPartial` | object | 否 | 流式部分参数 |
| `toolCancelled` | boolean | 否 | 设为 `true` 通知 Guest 取消 |
| `hostContext` | `McpUiHostContext` | 否 | 主机上下文（主题、语言等） |

### 事件回调 Props

| Prop | 类型 | 说明 |
|---|---|---|
| `onOpenLink` | `(params, extra) => Promise<McpUiOpenLinkResult>` | 处理链接打开请求 |
| `onMessage` | `(params, extra) => Promise<McpUiMessageResult>` | 处理消息请求 |
| `onLoggingMessage` | `(params) => void` | 处理日志消息 |
| `onSizeChanged` | `(params) => void` | 处理尺寸变化 |
| `onError` | `(error: Error) => void` | 错误回调 |
| `onFallbackRequest` | `(request, extra) => Promise<...>` | 未处理请求的兜底 |

### MCP 请求处理 Props

| Prop | 说明 |
|---|---|
| `onCallTool` | 处理 `tools/call` |
| `onReadResource` | 处理 `resources/read` |
| `onListResources` | 处理 `resources/list` |
| `onListResourceTemplates` | 处理 `resources/templates/list` |
| `onListPrompts` | 处理 `prompts/list` |

### Ref 方法（AppRendererHandle）

| 方法 | 说明 |
|---|---|
| `sendToolListChanged()` | 通知工具列表变更 |
| `sendResourceListChanged()` | 通知资源列表变更 |
| `sendPromptListChanged()` | 通知提示列表变更 |
| `teardownResource()` | 组件卸载前优雅关闭 |

---

## 八、renderData 结构

Host 向 Guest 传递的渲染数据（Legacy 适配器模式）：

```typescript
{
  toolInput: any;
  toolOutput?: any;
  widgetState?: any;
  theme: 'light' | 'dark' | 'system';
  locale: string;
  displayMode: 'inline' | 'fullscreen' | 'pip';
  maxHeight?: number;
}
```

---

## 九、URI 规范

```
ui://<component-name>/<instance-id>

示例：
ui://weather-server/current-weather
ui://my-app/dashboard-widget
```

- scheme 必须为 `ui://`
- component-name：服务名称
- instance-id：实例标识

---

## 十、MIME Type 规范

| 场景 | MIME Type |
|---|---|
| 标准 MCP-UI（MCP Apps 模式） | `text/html;profile=mcp-app` |
| 普通 HTML | `text/html` |

客户端通过 `mimeType === 'text/html;profile=mcp-app'` 识别 MCP-UI 资源。

---

## 十一、完整数据流

```
1. Server 调用 createUIResource() 生成 UIResource
2. Server 通过 registerAppTool() 注册工具，_meta.ui.resourceUri 指向 UIResource
3. Client 调用工具，从响应 _meta.ui.resourceUri 读取资源 URI
4. Client 通过 resources/read 拉取 UIResource
5. AppRenderer 将 UIResource.resource.text/blob 渲染进沙箱 iframe
6. iframe（Guest）通过 postMessage JSON-RPC 与 Host 双向通信
```
