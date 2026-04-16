# a2a-sdk 服务器架构调研笔记

## 核心组件

### 1. A2AFastAPIApplication
创建 FastAPI 应用的入口点：

```python
from a2a.server.apps.jsonrpc import A2AFastAPIApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.agent_execution import AgentExecutor

app = A2AFastAPIApplication(
    agent_card=agent_card,
    http_handler=request_handler,
)
```

### 2. DefaultRequestHandler
处理 A2A 请求的默认处理器：

```python
handler = DefaultRequestHandler(
    agent_executor=agent_executor,  # 自定义 AgentExecutor
    task_store=InMemoryTaskStore(),
)
```

### 3. AgentExecutor (抽象类)
需要子类化来实现业务逻辑：

```python
from a2a.server.agent_execution import AgentExecutor

class StargateAgentExecutor(AgentExecutor):
    async def execute(self, task):
        # 处理任务，返回事件流
        yield TaskStatusUpdateEvent(task_id=task.id, state="working")
        # ... 处理逻辑 ...
        yield TaskStatusUpdateEvent(task_id=task.id, state="completed")
    
    async def cancel(self, task_id):
        # 取消任务
        pass
```

### 4. Streaming 流程

```
Client -> POST /tasks/sendSubscribe (JSON-RPC)
    -> JSONRPCHandler.on_message_send_stream
        -> DefaultRequestHandler.on_message_send_stream
            -> AgentExecutor.execute
                -> yields events (TaskStatusUpdateEvent, TaskArtifactUpdateEvent, Message)
```

## 关键发现

1. **必须使用 AgentExecutor**: 服务器架构依赖 `AgentExecutor.execute()` 方法产生事件流
2. **事件类型**:
   - `TaskStatusUpdateEvent` - 状态更新
   - `TaskArtifactUpdateEvent` - 产物更新
   - `Message` - 完整消息
   - `Task` - 任务对象

3. **服务器启动**: `A2AFastAPIApplication` 创建 FastAPI app，然后用 uvicorn 启动

## 简化方案建议

由于完整实现需要大量自定义代码，建议简化方案：

1. **先用原生 HTTP SSE** 实现 streaming
2. **AgentCard 仍用 a2a-sdk** 生成
3. **消息格式遵循 A2A 标准**
4. **后续逐步迁移** 到完整的 a2a-sdk 服务器架构

这样可以快速完成迁移，同时保持协议兼容性。
