# A2A 协议完整字段解析

> 来源：https://a2a-protocol.org/latest/topics/what-is-a2a/  
> GitHub：https://github.com/a2aproject/A2A  
> 版本：1.0

## 一、顶层核心对象总览

```
AgentCard         → Agent 的"身份证"，供客户端发现和初始化
  └── AgentSkill  → Agent 能力列表
  └── AgentCapabilities → 支持的协议特性

Message           → 单轮通信单元
  └── Part[]      → 内容容器（文本/文件/结构数据）

Task              → 有状态的工作单元
  ├── TaskStatus  → 当前状态
  └── Artifact[]  → 产出物
       └── Part[] → 内容容器
```

---

## 二、AgentCard

Agent 的元数据文档，托管在 `/.well-known/agent-card.json`。

```json
{
  "name": "Travel Agent",
  "description": "Helps plan international trips",
  "url": "https://agent.example.com/a2a",
  "version": "1.0.0",
  "documentationUrl": "https://agent.example.com/docs",

  "capabilities": {
    "streaming": true,
    "pushNotifications": true,
    "stateTransitionHistory": false
  },

  "skills": [
    {
      "id": "flight-booking",
      "name": "Flight Booking",
      "description": "Search and book flights",
      "tags": ["travel", "flight"],
      "examples": ["Book a flight from NYC to London"],
      "inputModes": ["text"],
      "outputModes": ["text", "data"]
    }
  ],

  "securitySchemes": {
    "bearerAuth": {
      "type": "http",
      "scheme": "bearer",
      "bearerFormat": "JWT"
    }
  },
  "security": [{ "bearerAuth": [] }],

  "provider": {
    "organization": "Example Corp",
    "url": "https://example.com"
  },

  "extensions": [
    {
      "uri": "https://example.com/ext/v1",
      "description": "Custom extension",
      "required": false
    }
  ]
}
```

### AgentCard 字段说明

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string | 是 | Agent 名称 |
| `description` | string | 否 | Agent 描述 |
| `url` | string | 是 | A2A 服务端点 URL |
| `version` | string | 是 | Agent 版本号 |
| `documentationUrl` | string | 否 | 文档链接 |
| `capabilities` | object | 是 | 支持的协议特性 |
| `capabilities.streaming` | bool | 否 | 是否支持 SSE 流式 |
| `capabilities.pushNotifications` | bool | 否 | 是否支持 Push 通知 |
| `capabilities.stateTransitionHistory` | bool | 否 | 是否返回状态历史 |
| `skills` | AgentSkill[] | 否 | 能力列表 |
| `securitySchemes` | object | 否 | 认证方案定义（OpenAPI 格式） |
| `security` | array | 否 | 启用的认证方案 |
| `provider` | object | 否 | 提供方信息 |
| `extensions` | array | 否 | 自定义协议扩展 |

### AgentSkill 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 技能唯一 ID |
| `name` | string | 技能名称 |
| `description` | string | 技能描述 |
| `tags` | string[] | 标签 |
| `examples` | string[] | 示例请求 |
| `inputModes` | string[] | 支持的输入模态（text/file/data） |
| `outputModes` | string[] | 支持的输出模态 |

---

## 三、Part（内容容器）

Message 和 Artifact 的最小内容单元，每个 Part **只能包含一种内容字段**：

```json
// 文本
{ "text": "Hello, please book a flight." }

// 文件（内联字节）
{ "raw": "<base64>", "mediaType": "image/png", "filename": "photo.png" }

// 文件（外部 URL）
{ "url": "https://example.com/file.pdf", "mediaType": "application/pdf" }

// 结构化数据
{ "data": { "origin": "NYC", "destination": "LHR" }, "mediaType": "application/json" }
```

### Part 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `text` | string | 纯文本内容（四选一） |
| `raw` | string | Base64 编码的二进制数据（四选一） |
| `url` | string | 外部文件 URI（四选一） |
| `data` | object | 结构化 JSON 数据（四选一） |
| `mediaType` | string | MIME 类型，如 `"image/png"` |
| `filename` | string | 文件名 |
| `metadata` | object | 附加 key-value 元信息 |

---

## 四、Message（消息）

单轮通信单元，角色为 `user` 或 `agent`。

```json
{
  "role": "user",
  "messageId": "msg-001",
  "contextId": "ctx-abc",
  "taskId": "task-xyz",
  "referenceTaskIds": ["task-prev-001"],
  "parts": [
    { "text": "Plan a trip to Tokyo for 5 days." }
  ],
  "metadata": {}
}
```

### Message 字段说明

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `role` | `"user"` \| `"agent"` | 是 | 消息发送方角色 |
| `messageId` | string | 是 | 消息唯一 ID |
| `contextId` | string | 否 | 所属会话上下文 ID |
| `taskId` | string | 否 | 关联的 Task ID |
| `referenceTaskIds` | string[] | 否 | 引用的历史 Task ID |
| `parts` | Part[] | 是 | 消息内容 |
| `metadata` | object | 否 | 附加元信息 |

---

## 五、Task（任务）

有状态的工作单元，用于跟踪长时运行操作。

```json
{
  "id": "task-123",
  "contextId": "ctx-abc",
  "status": {
    "state": "completed",
    "message": { "role": "agent", "parts": [{ "text": "Done!" }] },
    "timestamp": "2026-09-04T10:00:00Z"
  },
  "artifacts": [],
  "history": [],
  "metadata": {}
}
```

### Task 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | Task 唯一 ID |
| `contextId` | string | 所属会话上下文 ID |
| `status` | TaskStatus | 当前状态对象 |
| `artifacts` | Artifact[] | 产出物列表 |
| `history` | Message[] | 历史消息（可选） |
| `metadata` | object | 附加元信息 |

### TaskStatus 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `state` | TaskState | 当前状态值（见下表） |
| `message` | Message | 附带的 Agent 消息 |
| `timestamp` | string | 状态变更时间（ISO 8601） |

### TaskState 枚举值

| 状态 | 类型 | 说明 |
|---|---|---|
| `submitted` | 进行中 | 已提交，等待处理 |
| `working` | 进行中 | 处理中 |
| `input-required` | **中断** | 需要用户补充输入 |
| `auth-required` | **中断** | 需要用户授权 |
| `completed` | **终止** | 成功完成 |
| `canceled` | **终止** | 已取消 |
| `rejected` | **终止** | 被拒绝 |
| `failed` | **终止** | 执行失败 |

> Task 一旦进入终止状态，**不可重启**，续接交互需在同一 `contextId` 下创建新 Task。

---

## 六、Artifact（产出物）

Agent 执行任务后产生的具体交付物。

```json
{
  "artifactId": "artifact-001",
  "name": "travel_plan.pdf",
  "description": "Complete travel itinerary",
  "parts": [
    {
      "url": "https://agent.example.com/files/plan.pdf",
      "mediaType": "application/pdf",
      "filename": "travel_plan.pdf"
    }
  ],
  "metadata": {}
}
```

### Artifact 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `artifactId` | string | 产出物唯一 ID |
| `name` | string | 人类可读名称 |
| `description` | string | 描述 |
| `parts` | Part[] | 内容（支持多 Part） |
| `metadata` | object | 附加元信息 |

---

## 七、JSON-RPC 方法一览

所有请求统一格式：`POST <agentUrl>`，`Content-Type: application/json`。

| 方法 | 说明 |
|---|---|
| `message/send` | 发送消息（同步，返回 Message 或 Task） |
| `message/stream` | 发送消息（SSE 流式） |
| `tasks/get` | 查询 Task 状态 |
| `tasks/cancel` | 取消 Task |
| `tasks/subscribe` | 重新订阅 SSE（断线重连） |
| `tasks/pushNotificationConfig/set` | 配置推送通知 |
| `tasks/pushNotificationConfig/get` | 获取推送配置 |
| `tasks/pushNotificationConfig/delete` | 删除推送配置 |
| `agent/getAuthenticatedExtendedCard` | 获取认证后的扩展 AgentCard |

### 请求结构

```json
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "messageId": "msg-001",
      "parts": [{ "text": "Hello" }]
    },
    "configuration": {
      "acceptedOutputModes": ["text"],
      "pushNotificationConfig": {
        "url": "https://client.example.com/webhook",
        "token": "secret-token"
      }
    }
  }
}
```

### SSE 流式事件类型

| 事件类型 | 说明 |
|---|---|
| `Task` | 当前工作状态快照 |
| `TaskStatusUpdateEvent` | 任务状态变更（如 working → completed） |
| `TaskArtifactUpdateEvent` | 产出物新增或更新（含 `append`、`lastChunk` 字段用于分块重组） |

---

## 八、错误码

| 错误码 | 名称 | 说明 |
|---|---|---|
| `-32700` | JSONParseError | JSON 格式无效 |
| `-32600` | InvalidRequestError | 请求体校验失败 |
| `-32601` | MethodNotFoundError | 方法不存在 |
| `-32602` | InvalidParamsError | 参数无效 |
| `-32603` | InternalError | 内部错误 |
| `-32001` | TaskNotFoundError | Task 不存在 |
| `-32006` | InvalidAgentResponseError | Agent 响应格式无效 |

---

## 九、标识符体系

| 标识符 | 作用域 | 说明 |
|---|---|---|
| `contextId` | 会话级 | 将多个 Task/Message 归组为一个会话 |
| `taskId` | Task 级 | 唯一标识一个工作单元 |
| `messageId` | Message 级 | 唯一标识一条消息 |
| `artifactId` | Artifact 级 | 唯一标识一个产出物 |

---

## 十、认证方案类型

| 类型 | 字段 `type` | 说明 |
|---|---|---|
| HTTP Bearer | `http` | JWT 等 Bearer Token，`scheme: "bearer"` |
| API Key | `apiKey` | 通过 Header/Query 传递 |
| OAuth2 | `oauth2` | 标准 OAuth2 流程 |
| OpenID Connect | `openIdConnect` | OIDC，含 `openIdConnectUrl` |

---

## 十一、PushNotificationConfig

```json
{
  "url": "https://client.example.com/webhook",
  "token": "client-validation-token",
  "authentication": {
    "type": "http",
    "scheme": "bearer"
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `url` | string | 客户端 HTTPS Webhook 地址 |
| `token` | string | 客户端用于验证推送来源的 token |
| `authentication` | object | Server 向 Webhook 认证的方案 |
