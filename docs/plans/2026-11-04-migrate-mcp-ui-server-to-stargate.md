# 将 @mcp-ui/server 迁移至 stargate-agent Implementation Plan

**Goal:** 将 HTML 生成逻辑从 `resource-center-mock`（Node.js）迁移到 `stargate-agent`（Python），使业务数据不再流经不该知道它的 mock 服务。

**Architecture:** `stargate-agent` 直接使用 Python 包 `mcp-ui-server` 的 `create_ui_resource()` 在本地生成 MCP UI Resource，只通过 `GET /api/components/:name` 向 `resource-center-mock` 获取 MF 组件元数据（containerName、remoteEntryUrl）。`resource-center-mock` 删除 `/api/ui-resource/:name` 路由及 `@mcp-ui/server` 依赖，退化为纯 MF 组件注册表。

**Tech Stack:** Python `mcp-ui-server==1.0.0`（PyPI）、`uv`（依赖管理）、TypeScript/Express（resource-center-mock）、`pnpm`（Node 依赖管理）。

---

## 背景：理解现有代码

在动手之前，先明白现状：

- `packages/stargate-agent/src/stargate_agent/main.py`：Python FastAPI 服务。`mcp_resources_read()` 函数（第 60-116 行）**已经**在本地手动拼 HTML 字符串，没有调用 mock 的 `/api/ui-resource`。但它没有使用任何 Python SDK 来构造符合 MCP-UI 协议的 `resource` 响应结构，只是直接 `return JSONResponse({"contents": [...]})` 手写了结构。
- `packages/resource-center-mock/src/index.ts`：Node.js Express 服务。`POST /api/ui-resource/EmployeeChart`（第 23-67 行）仍然存在，使用 `@mcp-ui/server` 的 `createUIResource()`，但目前没有被 stargate-agent 调用。
- `packages/stargate-agent/pyproject.toml`：依赖列表，还没有 `mcp-ui-server`。

迁移任务分两部分：
1. **stargate-agent**：引入 `mcp-ui-server` Python 包，用 `create_ui_resource()` 替换 `mcp_resources_read()` 里手写的 `JSONResponse` 结构。
2. **resource-center-mock**：删除 `POST /api/ui-resource/EmployeeChart` 路由及 `@mcp-ui/server` 依赖。

---

## Task 1：为 stargate-agent 添加 `mcp-ui-server` 依赖

**Files:**
- Modify: `packages/stargate-agent/pyproject.toml`

### Step 1：在 pyproject.toml 中添加依赖

编辑 `packages/stargate-agent/pyproject.toml`，在 `dependencies` 列表末尾加入 `mcp-ui-server`：

```toml
[project]
name = "stargate-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "python-a2a>=0.5.0",
    "mcp[server]>=1.5.0",
    "openai>=1.30.0",
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.29.0",
    "httpx>=0.27.0",
    "python-dotenv>=1.0.1",
    "mcp-ui-server>=1.0.0",
]
```

### Step 2：安装依赖

在 `packages/stargate-agent/` 目录下运行：

```bash
cd packages/stargate-agent && uv sync
```

预期输出：包含 `mcp-ui-server` 的安装行，最终 `All packages installed`。

### Step 3：验证安装

```bash
cd packages/stargate-agent && .venv/bin/python -c "from mcp_ui_server import create_ui_resource; print('ok')"
```

预期输出：`ok`

---

## Task 2：在 `mcp_resources_read()` 中使用 `create_ui_resource()`

**Files:**
- Modify: `packages/stargate-agent/src/stargate_agent/main.py`（第 1-10 行 import 区、第 60-116 行函数体）

### 现状说明

`mcp_resources_read()` 当前手写了如下 `JSONResponse`：

```python
return JSONResponse({
    "contents": [{
        "uri": uri,
        "mimeType": "text/html;profile=mcp-app",
        "text": html,
    }]
})
```

`mcp-ui-server` 的 `create_ui_resource()` 返回一个对象，其结构与 MCP-UI 协议对齐。查看其返回值，需要把它序列化为 dict 再用 JSONResponse 返回。

### Step 1：确认 `create_ui_resource()` 的返回类型

运行以下代码探查返回值结构：

```bash
cd packages/stargate-agent && .venv/bin/python - << 'EOF'
from mcp_ui_server import create_ui_resource
r = create_ui_resource({
    "uri": "ui://test/1",
    "content": {"type": "rawHtml", "htmlString": "<h1>hi</h1>"},
    "encoding": "text",
})
print(type(r))
print(r)
import json
try:
    print(json.dumps(r))
except Exception as e:
    print("not directly serializable:", e)
    if hasattr(r, '__dict__'):
        print(r.__dict__)
    if hasattr(r, 'model_dump'):
        print(r.model_dump())
EOF
```

根据输出决定序列化方式：如果有 `model_dump()`（Pydantic），则用 `.model_dump()`；如果直接是 dict，则直接用；如果是自定义对象带 `__dict__`，则用 `.__dict__`。

> 注意：根据 PyPI 页面描述，`create_ui_resource()` 返回 "UIResource instance"，大概率是 Pydantic 模型，调用 `.model_dump()` 即可。

### Step 2：在文件顶部添加 import

在 `packages/stargate-agent/src/stargate_agent/main.py` 的 import 区（第 1-9 行末尾）添加：

```python
from mcp_ui_server import create_ui_resource
```

完整 import 区示例（只展示变更行，其余不变）：

```python
import os
import json
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from python_a2a import A2AServer, Message, TextContent, MessageRole, AgentCard
from mcp_ui_server import create_ui_resource   # 新增

from stargate_agent import card_cache, llm, sse_logger
```

### Step 3：替换 `mcp_resources_read()` 末尾的 `return JSONResponse(...)`

找到 `mcp_resources_read()` 函数末尾（当前第 105-114 行）：

```python
    return JSONResponse({
        "contents": [{ 
            "uri": uri,
            "mimeType": "text/html;profile=mcp-app",
            "text": html,
        }]
    })
```

替换为：

```python
    resource = create_ui_resource({
        "uri": uri,
        "content": {"type": "rawHtml", "htmlString": html},
        "encoding": "text",
    })
    if hasattr(resource, "model_dump"):
        return JSONResponse(resource.model_dump())
    return JSONResponse(resource if isinstance(resource, dict) else resource.__dict__)
```

> 说明：`hasattr(resource, "model_dump")` 处理 Pydantic v2 对象；fallback 兜住其他序列化方式，保证代码健壮。

### Step 4：手动启动服务验证

```bash
cd packages/stargate-agent && uv run uvicorn stargate_agent.main:app --port 3001 --reload
```

在另一个终端请求（需要先有一个 card_id，可用步骤 5 的 curl 链先触发卡片创建）：

```bash
curl "http://localhost:3001/mcp/resources/read?uri=ui://stargate/card/test-id" 2>&1 | head -5
```

预期：返回 404（card 不存在），说明服务能正常启动并路由到该函数，没有 import 错误。

---

## Task 3：清理 `resource-center-mock` — 删除 `/api/ui-resource/:name` 路由

**Files:**
- Modify: `packages/resource-center-mock/src/index.ts`（第 23-67 行）

### 现状

`src/index.ts` 中第 23-67 行是 `app.post('/api/ui-resource/EmployeeChart', ...)` 路由，调用了 `createUIResource`。

### Step 1：删除路由代码

将 `packages/resource-center-mock/src/index.ts` 中的以下代码块**整体删除**：

```typescript
app.post('/api/ui-resource/EmployeeChart', (req, res) => {
  const data: { year: number; count: number }[] = req.body.data ?? [];
  const token: string = req.body.token ?? '';

  const propsJson = JSON.stringify(data);
  const html = `<!DOCTYPE html>
...（完整的 html 模板字符串）...
</body></html>`;

  const resource = createUIResource({
    uri: 'ui://resource-center/EmployeeChart',
    content: { type: 'rawHtml', htmlString: html },
    encoding: 'text',
  });

  res.json(resource);
});
```

同时删除顶部的 import：

```typescript
import { createUIResource } from '@mcp-ui/server';
```

删除后，文件应如下所示（完整新内容）：

```typescript
import express from 'express';
import cors from 'cors';

const app = express();
app.use(cors());
app.use(express.json());

const REMOTE_ENTRY_URL = 'http://localhost:3004/remoteEntry.js';

app.get('/api/components/:name', (req, res) => {
  const { name } = req.params;
  if (name === 'EmployeeChart') {
    res.json({
      componentName: 'EmployeeChart',
      containerName: 'employeeChartCard',
      remoteEntryUrl: REMOTE_ENTRY_URL,
    });
  } else {
    res.status(404).json({ error: 'Component not found' });
  }
});

app.get('/health', (_req, res) => res.json({ ok: true }));

app.listen(3003, () => console.log('resource-center-mock running on :3003'));
```

### Step 2：验证 TypeScript 能编译

```bash
cd packages/resource-center-mock && npx tsx src/index.ts
```

预期输出：`resource-center-mock running on :3003`（无报错）。用 `Ctrl+C` 停止。

---

## Task 4：从 `resource-center-mock` 移除 `@mcp-ui/server` 依赖

**Files:**
- Modify: `packages/resource-center-mock/package.json`

### Step 1：移除依赖

```bash
cd packages/resource-center-mock && pnpm remove @mcp-ui/server
```

预期：`package.json` 的 `dependencies` 中 `@mcp-ui/server` 行消失，`pnpm-lock.yaml` 更新。

### Step 2：验证服务仍可启动

```bash
cd packages/resource-center-mock && pnpm dev
```

预期输出：`resource-center-mock running on :3003`（无 import 错误）。

### Step 3：验证 `/api/components/EmployeeChart` 接口

在另一个终端：

```bash
curl http://localhost:3003/api/components/EmployeeChart
```

预期输出：

```json
{"componentName":"EmployeeChart","containerName":"employeeChartCard","remoteEntryUrl":"http://localhost:3004/remoteEntry.js"}
```

### Step 4：验证 `/api/ui-resource/EmployeeChart` 已被删除

```bash
curl -X POST http://localhost:3003/api/ui-resource/EmployeeChart \
  -H "Content-Type: application/json" \
  -d '{"data":[]}'
```

预期：HTTP 404，返回类似 `Cannot POST /api/ui-resource/EmployeeChart`。

---

## Task 5：端到端冒烟测试

验证整个链路在迁移后仍能正常工作。

### 前置条件

确保所有服务均已启动（分别在不同终端）：

```bash
# 终端 1：employee-chart-card（MF 远程组件，端口 3004）
cd packages/employee-chart-card && pnpm dev

# 终端 2：resource-center-mock（端口 3003）
cd packages/resource-center-mock && pnpm dev

# 终端 3：stargate-agent（端口 3001 + 3011）
cd packages/stargate-agent && uv run python -m stargate_agent.main

# 终端 4：codeflicker-frontend（端口 5173，可选）
cd packages/codeflicker-frontend && pnpm dev
```

### Step 1：触发卡片创建（A2A 链路）

向 stargate-agent 发送 A2A 消息，让它返回一个 `mcp_ui_resource`：

```bash
curl -s -X POST http://localhost:3011 \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "tasks/send",
    "params": {
      "id": "task-1",
      "message": {
        "role": "user",
        "parts": [{"type": "text", "text": "查询快手员工趋势"}]
      }
    }
  }' | python3 -m json.tool
```

在响应 JSON 中找到 `resourceUri`，格式为 `ui://stargate/card/<uuid>`，记录下 `<uuid>` 部分。

### Step 2：调用 `mcp/resources/read` 获取 HTML

```bash
curl -s "http://localhost:3001/mcp/resources/read?uri=ui://stargate/card/<uuid>" | python3 -m json.tool
```

将 `<uuid>` 替换为 Step 1 中得到的值。

预期：响应 JSON 结构符合 MCP-UI 协议，包含 `contents` 数组，其中有 `uri`、`mimeType`（`text/html;profile=mcp-app`）、`text`（HTML 字符串）。

### Step 3：确认 HTML 内容正确

检查 Step 2 响应中 `contents[0].text` 的 HTML：
- 应包含 `<script src="http://localhost:3004/remoteEntry.js"></script>`
- 应包含 `employeeChartCard`
- 应包含员工数据（`2019`、`7000` 等）

---

## 总结：变更文件清单

| 文件 | 变更类型 | 内容 |
|---|---|---|
| `packages/stargate-agent/pyproject.toml` | 修改 | 添加 `mcp-ui-server>=1.0.0` 依赖 |
| `packages/stargate-agent/src/stargate_agent/main.py` | 修改 | 添加 `from mcp_ui_server import create_ui_resource`；替换 `mcp_resources_read()` 末尾的手写 `JSONResponse` |
| `packages/resource-center-mock/src/index.ts` | 修改 | 删除 `import { createUIResource }` 及 `POST /api/ui-resource/EmployeeChart` 路由 |
| `packages/resource-center-mock/package.json` | 修改 | 移除 `@mcp-ui/server` 依赖 |
