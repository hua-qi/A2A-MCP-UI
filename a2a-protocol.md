# A2A 协议总结

> 来源：https://a2a-protocol.org/latest/topics/what-is-a2a/#a2a-and-mcp  
> GitHub：https://github.com/a2aproject/A2A

## 概述

A2A（Agent2Agent）是一个开放标准协议，用于实现不同框架、不同厂商构建的 AI Agent 之间的无缝通信与协作。它为 Agent 提供通用语言，打破生态孤岛，使跨组织、跨框架的 Agent 能够联合工作。

---

## A2A 解决的核心问题

在没有 A2A 的情况下，多 Agent 协作面临以下挑战：

| 问题 | 说明 |
|---|---|
| Agent 被迫包装为工具 | 限制了 Agent 的完整能力，效率低下 |
| 点对点自定义集成 | 每次新集成都需要大量定制开发 |
| 创新速度慢 | 定制开发拖慢系统演进 |
| 扩展性差 | Agent 数量增加后难以维护 |
| 互操作性不足 | 无法有机形成复杂 AI 生态系统 |
| 安全隐患 | 临时通信方案缺乏一致安全保障 |

---

## 核心优势

- **安全协作**：基于 HTTPS 通信，Agent 内部逻辑对外不透明
- **互操作性**：不同厂商、不同框架的 Agent 可无缝协作
- **Agent 自治**：Agent 保留独立能力，作为自治实体参与协作
- **降低集成复杂度**：标准化通信，团队可专注于核心业务价值
- **支持长时任务（LRO）**：通过 SSE 流式传输和异步执行支持长时运行操作

---

## 关键设计原则

| 原则 | 说明 |
|---|---|
| **简洁性** | 复用 HTTP、JSON-RPC、SSE 等成熟标准 |
| **企业级就绪** | 支持标准 Web 认证、授权、安全、追踪、监控 |
| **异步优先** | 原生支持长时任务、断连重连、流推送 |
| **模态无关** | 支持多种内容类型，不限于纯文本 |
| **不透明执行** | Agent 不暴露内部逻辑、内存或专有工具 |

---

## A2A 与 MCP 的关系

A2A 和 MCP 是**互补**而非竞争的协议，分别处于 Agent 栈的不同层次：

| 协议 | 定位 | 典型场景 |
|---|---|---|
| **MCP** | 连接模型与工具/数据 | 调用工具、查询数据库（无状态、单次操作） |
| **A2A** | Agent 之间的协作通信 | 多轮对话、任务委派、谈判（有状态、复杂交互） |

**核心区别**：MCP 将 Agent 视为工具调用的消费者；A2A 允许 Agent 以完整 Agent 身份与其他 Agent 通信，支持协商、澄清等复杂多轮交互，不受"工具"抽象的限制。

> 参见：[Why Agents Are Not Tools](https://discuss.google.dev/t/agents-are-not-tools/192812)

### Agent 完整技术栈

```
┌──────────────────────────────────┐
│           A2A 协议               │  Agent 间通信（跨组织/框架）
├──────────────────────────────────┤
│           MCP 协议               │  模型与工具/数据连接
├──────────────────────────────────┤
│     框架（ADK / LangGraph 等）   │  Agent 构建工具包
├──────────────────────────────────┤
│           LLM 模型               │  Agent 推理核心
└──────────────────────────────────┘
```

---

## 请求生命周期

```
1. Agent Discovery  →  GET /.well-known/agent-card  →  获取 Agent Card
2. Authentication   →  解析 securitySchemes，获取 JWT Token
3. sendMessage API  →  POST /sendMessage（同步返回 Task）
4. sendMessageStream API  →  POST /sendMessageStream（SSE 流式返回）
    ├── Task (Submitted)
    ├── TaskStatusUpdateEvent (Working)
    ├── TaskArtifactUpdateEvent (artifact A)
    ├── TaskArtifactUpdateEvent (artifact B)
    └── TaskStatusUpdateEvent (Completed)
```

---

## 与 ADK 的关系

- **ADK（Agent Development Kit）**：Google 开源的 Agent 开发框架，模型无关、部署无关
- **A2A**：通信协议，与框架无关，ADK、LangGraph、Crew AI 构建的 Agent 均可使用 A2A 互联

---

## 协议定位总结

A2A 是 AI Agent 生态中的**互联互通层**，专注于让任意框架、任意组织的 Agent 能够安全、标准化地协同工作，是构建大规模多 Agent 系统的基础设施协议。
