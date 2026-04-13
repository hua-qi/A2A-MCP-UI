# MCP-UI 最小验证 Demo 实施计划

**Goal:** 搭建一个端到端可运行的技术验证 Demo，跑通"用户输入 → CF-Agent → A2A → SG-Agent → MCP-UI → 模块联邦卡片渲染"完整链路。

**Architecture:** Monorepo 含 5 个子包（2 个 Python Agent + 1 个 React 前端 + 1 个 Webpack5 MF 卡片 + 1 个 Mock 资源中心）。CF-Agent 负责 LLM 意图识别并通过 `python-a2a` SDK 调用 SG-Agent；SG-Agent 同时充当 A2A Agent 和 MCP-UI Server，生成 cardInstanceId 缓存卡片数据；前端使用 `@mcp-ui/client` 的 `AppRenderer` 触发资源读取，经由 CF-Agent `/resource-proxy` 代理，最终动态加载 MF 卡片组件渲染。

**Tech Stack:** Python 3.11+、`python-a2a`、`mcp[server]`（MCP Python SDK）、`openai`、FastAPI、uvicorn、React 18、TypeScript、Vite、`@mcp-ui/client`、Webpack 5 Module Federation、ECharts、pnpm workspaces

---

## 前置知识

### A2A 协议核心概念（本项目用到的部分）

A2A（Agent-to-Agent）是 Google 推出的多 Agent 通信协议，消息通过 JSON-RPC 传输。核心数据结构：

- **Task**：一次任务调用，有 `taskId`、`contextId`，状态流：`submitted → working → completed/failed`
- **Message**：单轮消息，含 `role`（`user`/`agent`）和 `parts` 列表
- **Part**：内容块，本项目扩展了 `kind: "mcp_ui_resource"` 类型：
  ```json
  {
    "data": {
      "kind": "mcp_ui_resource",
      "resourceUri": "ui://stargate/card/{cardInstanceId}",
      "uiMetadata": { "preferred-frame-size": { "width": 400, "height": 300 } }
    },
    "mediaType": "application/json"
  }
  ```

### MCP-UI 协议核心概念（本项目用到的部分）

MCP-UI 是 MCP 的 UI 扩展层。SG-Agent 实现 MCP Server，注册 `resources/read` 处理器，前端通过 `AppRenderer` 的 `onReadResource` 回调触发读取。资源 URI 格式：`ui://stargate/card/{cardInstanceId}`。

`AppRenderer` 不直接联网，所有 MCP 请求均通过 props 中的回调函数处理（本项目中 `onReadResource` 指向 CF-Agent 的 `/resource-proxy` 端点）。

### Module Federation 核心概念（本项目用到的部分）

Webpack 5 MF 允许运行时动态加载远程模块。`employee-chart-card` 包暴露 `./EmployeeChart` 组件，前端通过以下方式动态加载：

```javascript
const container = await import(/* webpackIgnore: true */ remoteEntryUrl);
await container.init(__webpack_share_scopes__.default);
const factory = await container.get('./EmployeeChart');
const EmployeeChart = factory().default;
```

---

## 环境准备

### 必须安装的工具

- Node.js 20+（`node --version` 验证）
- pnpm 9+（`npm i -g pnpm`）
- Python 3.11+（`python3 --version` 验证）
- uv（Python 包管理，`curl -LsSf https://astral.sh/uv/install.sh | sh`）

### 环境变量

在项目根目录创建 `.env`：

```bash
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
```

---

## Task 1: Monorepo 骨架

**Files:**
- Create: `package.json`
- Create: `pnpm-workspace.yaml`
- Create: `.env.example`
- Create: `.gitignore`

**Step 1: 创建根 package.json**

```json
{
  "name": "a2a-mcpui",
  "private": true,
  "scripts": {
    "dev": "pnpm --parallel -r run dev",
    "build": "pnpm -r run build"
  },
  "engines": { "node": ">=20", "pnpm": ">=9" }
}
```

**Step 2: 创建 pnpm-workspace.yaml**

```yaml
packages:
  - "packages/*"
```

**Step 3: 创建 .env.example**

```bash
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
```

**Step 4: 创建 .gitignore**

```gitignore
node_modules/
dist/
.env
__pycache__/
*.pyc
.venv/
*.egg-info/
```

**Step 5: 验证工作区初始化**

```bash
pnpm install
```

预期输出：`Done in ...s`，根目录出现 `node_modules/`。

---

## Task 2: resource-center-mock（端口 3003）

Mock 资源中心，纯静态 HTTP 服务，提供 `GET /api/components/EmployeeChart` 返回组件注册信息。

**Files:**
- Create: `packages/resource-center-mock/package.json`
- Create: `packages/resource-center-mock/src/index.ts`

**Step 1: 创建 package.json**

```json
{
  "name": "resource-center-mock",
  "version": "0.0.1",
  "scripts": {
    "dev": "tsx watch src/index.ts"
  },
  "dependencies": {
    "express": "^4.19.2",
    "cors": "^2.8.5"
  },
  "devDependencies": {
    "@types/express": "^4.17.21",
    "@types/cors": "^2.8.17",
    "tsx": "^4.7.0",
    "typescript": "^5.4.0"
  }
}
```

**Step 2: 创建 src/index.ts**

```typescript
import express from 'express';
import cors from 'cors';

const app = express();
app.use(cors());

app.get('/api/components/:name', (req, res) => {
  const { name } = req.params;
  if (name === 'EmployeeChart') {
    res.json({
      componentName: 'EmployeeChart',
      remoteEntryUrl: 'http://localhost:3004/remoteEntry.js',
    });
  } else {
    res.status(404).json({ error: 'Component not found' });
  }
});

app.get('/health', (_req, res) => res.json({ ok: true }));

app.listen(3003, () => console.log('resource-center-mock running on :3003'));
```

**Step 3: 安装依赖并手动测试**

```bash
cd packages/resource-center-mock && pnpm install
pnpm dev
```

另开终端验证：

```bash
curl http://localhost:3003/api/components/EmployeeChart
```

预期输出：

```json
{"componentName":"EmployeeChart","remoteEntryUrl":"http://localhost:3004/remoteEntry.js"}
```

**Step 4: Ctrl+C 停止服务，提交**

```bash
git add packages/resource-center-mock && git commit -m "feat: resource-center-mock"
```

---

## Task 3: employee-chart-card（Webpack5 MF，端口 3004）

暴露 `./EmployeeChart` 的模块联邦卡片，用 ECharts 展示员工趋势折线图，支持路径 A（直调 SG-Agent API）和路径 B（postMessage 触发 Agent 推理）。

**Files:**
- Create: `packages/employee-chart-card/package.json`
- Create: `packages/employee-chart-card/webpack.config.js`
- Create: `packages/employee-chart-card/src/index.tsx`（入口，开发预览用）
- Create: `packages/employee-chart-card/src/EmployeeChart.tsx`（暴露的组件）
- Create: `packages/employee-chart-card/public/index.html`

**Step 1: 创建 package.json**

```json
{
  "name": "employee-chart-card",
  "version": "0.0.1",
  "scripts": {
    "dev": "webpack serve --mode development",
    "build": "webpack --mode production"
  },
  "dependencies": {
    "echarts": "^5.5.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.1",
    "@types/react-dom": "^18.3.0",
    "css-loader": "^7.1.1",
    "html-webpack-plugin": "^5.6.0",
    "style-loader": "^4.0.0",
    "ts-loader": "^9.5.1",
    "typescript": "^5.4.0",
    "webpack": "^5.91.0",
    "webpack-cli": "^5.1.4",
    "webpack-dev-server": "^5.0.4"
  }
}
```

**Step 2: 创建 webpack.config.js**

```javascript
const { ModuleFederationPlugin } = require('webpack').container;
const HtmlWebpackPlugin = require('html-webpack-plugin');
const path = require('path');

module.exports = {
  entry: './src/index.tsx',
  output: {
    path: path.resolve(__dirname, 'dist'),
    publicPath: 'http://localhost:3004/',
    uniqueName: 'employeeChartCard',
  },
  resolve: { extensions: ['.tsx', '.ts', '.js'] },
  module: {
    rules: [
      { test: /\.tsx?$/, use: 'ts-loader', exclude: /node_modules/ },
      { test: /\.css$/, use: ['style-loader', 'css-loader'] },
    ],
  },
  plugins: [
    new ModuleFederationPlugin({
      name: 'employeeChartCard',
      filename: 'remoteEntry.js',
      exposes: {
        './EmployeeChart': './src/EmployeeChart',
      },
      shared: {
        react: { singleton: true, requiredVersion: '^18.3.1' },
        'react-dom': { singleton: true, requiredVersion: '^18.3.1' },
      },
    }),
    new HtmlWebpackPlugin({ template: './public/index.html' }),
  ],
  devServer: { port: 3004, headers: { 'Access-Control-Allow-Origin': '*' } },
};
```

**Step 3: 创建 tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "esModuleInterop": true
  },
  "include": ["src"]
}
```

**Step 4: 创建 public/index.html**

```html
<!DOCTYPE html>
<html>
  <head><meta charset="UTF-8" /><title>EmployeeChart Dev</title></head>
  <body><div id="root"></div></body>
</html>
```

**Step 5: 创建 src/EmployeeChart.tsx**

```tsx
import React, { useEffect, useRef } from 'react';
import * as echarts from 'echarts';

export interface EmployeeChartProps {
  data: { year: number; count: number }[];
  token: string;
  sgAgentBaseUrl?: string;
}

const EmployeeChart: React.FC<EmployeeChartProps> = ({
  data,
  token,
  sgAgentBaseUrl = 'http://localhost:3001',
}) => {
  const chartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!chartRef.current) return;
    const chart = echarts.init(chartRef.current);
    chart.setOption({
      title: { text: '快手员工趋势' },
      xAxis: { type: 'category', data: data.map((d) => String(d.year)) },
      yAxis: { type: 'value' },
      series: [{ type: 'line', data: data.map((d) => d.count), smooth: true }],
    });
    return () => chart.dispose();
  }, [data]);

  const handleAnalyze = () => {
    window.parent.postMessage({ type: 'agent_submit', payload: { action: 'analyze_trend', data } }, '*');
  };

  const handleHoverYear = async (year: number) => {
    const res = await fetch(`${sgAgentBaseUrl}/api/employee/detail/${year}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const detail = await res.json();
    alert(`${year} 年详情：${JSON.stringify(detail)}`);
  };

  return (
    <div style={{ padding: 16 }}>
      <div ref={chartRef} style={{ width: 500, height: 300 }} />
      <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
        <button onClick={handleAnalyze}>分析趋势</button>
        {data.map((d) => (
          <button key={d.year} onClick={() => handleHoverYear(d.year)}>
            {d.year} 详情
          </button>
        ))}
      </div>
    </div>
  );
};

export default EmployeeChart;
```

**Step 6: 创建 src/index.tsx（开发预览入口）**

```tsx
import React from 'react';
import { createRoot } from 'react-dom/client';
import EmployeeChart from './EmployeeChart';

const mockData = [
  { year: 2019, count: 7000 },
  { year: 2020, count: 10000 },
  { year: 2021, count: 16000 },
  { year: 2022, count: 22000 },
  { year: 2023, count: 18000 },
];

createRoot(document.getElementById('root')!).render(
  <EmployeeChart data={mockData} token="dev-token" />
);
```

**Step 7: 安装依赖并验证**

```bash
cd packages/employee-chart-card && pnpm install
pnpm dev
```

浏览器打开 `http://localhost:3004`，应看到折线图和按钮。

**Step 8: 验证 remoteEntry.js 可访问**

```bash
curl -I http://localhost:3004/remoteEntry.js
```

预期：`HTTP/1.1 200 OK`。

**Step 9: 提交**

```bash
git add packages/employee-chart-card && git commit -m "feat: employee-chart-card MF"
```

---

## Task 4: stargate-agent（Python，端口 3001）

同时扮演 A2A Agent 和 MCP-UI Server 两个角色。使用 `python-a2a` SDK 处理 A2A Task，使用 `mcp` Python SDK 的 `resource` decorator 注册 MCP 资源读取处理器。

**Files:**
- Create: `packages/stargate-agent/pyproject.toml`
- Create: `packages/stargate-agent/src/stargate_agent/__init__.py`
- Create: `packages/stargate-agent/src/stargate_agent/main.py`
- Create: `packages/stargate-agent/src/stargate_agent/card_cache.py`
- Create: `packages/stargate-agent/src/stargate_agent/llm.py`
- Create: `packages/stargate-agent/src/stargate_agent/sse_logger.py`
- Create: `packages/stargate-agent/package.json`（只含 `dev` 脚本，供 pnpm 并发启动）

**Step 1: 理解 python-a2a SDK 的使用方式**

```python
from python_a2a import A2AServer, TaskHandler, Task, Message, TextPart

class MyAgent(TaskHandler):
    async def handle_task(self, task: Task) -> Task:
        user_text = task.history[-1].parts[0].text
        task.artifacts = [Message(role="agent", parts=[TextPart(text=f"echo: {user_text}")])]
        task.status.state = "completed"
        return task

server = A2AServer(task_handler=MyAgent(), port=3001)
server.run()
```

**Step 2: 理解本项目中 A2A 协议的扩展 Part 结构**

SG-Agent 在响应的 `artifacts` 中同时返回文本 Part 和 mcp_ui_resource Part：

```python
from python_a2a import DataPart
import json

mcp_ui_part = DataPart(
    data={
        "kind": "mcp_ui_resource",
        "resourceUri": f"ui://stargate/card/{card_instance_id}",
        "uiMetadata": {"preferred-frame-size": {"width": 500, "height": 400}},
    },
    media_type="application/json",
)
```

**Step 3: 创建 pyproject.toml**

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
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/stargate_agent"]
```

**Step 4: 创建 src/stargate_agent/card_cache.py**

内存缓存，存储 `cardInstanceId → {componentName, remoteEntryUrl, props}`，TTL 1 小时。

```python
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

TTL = 3600

@dataclass
class CardInstance:
    component_name: str
    remote_entry_url: str
    props: dict[str, Any]
    created_at: float = field(default_factory=time.time)

_store: dict[str, CardInstance] = {}

def put(component_name: str, remote_entry_url: str, props: dict[str, Any]) -> str:
    cid = str(uuid.uuid4())
    _store[cid] = CardInstance(component_name, remote_entry_url, props)
    return cid

def get(cid: str) -> CardInstance | None:
    inst = _store.get(cid)
    if inst is None:
        return None
    if time.time() - inst.created_at > TTL:
        del _store[cid]
        return None
    return inst
```

**Step 5: 创建 src/stargate_agent/llm.py**

封装 OpenAI 工具调用，返回工具名和参数。

```python
import os
import json
from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None

def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
    return _client

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_employee_trend",
            "description": "查询快手历年员工人数趋势数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "公司名称"},
                },
                "required": ["company"],
            },
        },
    }
]

async def select_tool(user_message: str) -> tuple[str, dict]:
    client = _get_client()
    model = os.environ.get("LLM_MODEL", "gpt-4o")
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": user_message}],
        tools=TOOLS,
        tool_choice="auto",
    )
    msg = response.choices[0].message
    if msg.tool_calls:
        tc = msg.tool_calls[0]
        return tc.function.name, json.loads(tc.function.arguments)
    return "none", {}
```

**Step 6: 创建 src/stargate_agent/sse_logger.py**

SSE 事件广播器，前端数据流转记录器订阅 `/events`。

```python
import asyncio
from datetime import datetime
from typing import AsyncGenerator

_queues: list[asyncio.Queue] = []

def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")

async def subscribe() -> AsyncGenerator[str, None]:
    q: asyncio.Queue = asyncio.Queue()
    _queues.append(q)
    try:
        while True:
            event = await q.get()
            yield f"data: {event}\n\n"
    finally:
        _queues.remove(q)

def emit(source: str, target: str, msg_type: str, detail: str = "") -> None:
    import json
    event = json.dumps({
        "time": _now(),
        "source": source,
        "target": target,
        "type": msg_type,
        "detail": detail,
    })
    for q in list(_queues):
        q.put_nowait(event)
```

**Step 7: 创建 src/stargate_agent/main.py**

这是最核心的文件，整合 A2A Server、FastAPI HTTP 接口和 MCP Resources。

```python
import asyncio
import os
import json
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from python_a2a import A2AServer, TaskHandler, Task, Message, TextPart, DataPart

from stargate_agent import card_cache, llm, sse_logger

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../../.env"))

RESOURCE_CENTER_URL = os.environ.get("RESOURCE_CENTER_URL", "http://localhost:3003")
PORT = int(os.environ.get("SG_AGENT_PORT", 3001))

# ── FastAPI app ──────────────────────────────────────────────────
app = FastAPI(title="stargate-agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mock 员工详情数据 ─────────────────────────────────────────────
EMPLOYEE_DETAIL = {
    2019: {"year": 2019, "count": 7000, "note": "快速扩张期"},
    2020: {"year": 2020, "count": 10000, "note": "疫情期逆势增长"},
    2021: {"year": 2021, "count": 16000, "note": "业务多元化"},
    2022: {"year": 2022, "count": 22000, "note": "峰值"},
    2023: {"year": 2023, "count": 18000, "note": "降本增效"},
}

# ── HTTP 接口 ────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/events")
async def events():
    return StreamingResponse(sse_logger.subscribe(), media_type="text/event-stream")

@app.get("/api/card-instance/{card_id}")
async def get_card_instance(card_id: str):
    inst = card_cache.get(card_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="Card instance not found or expired")
    return {
        "componentName": inst.component_name,
        "remoteEntryUrl": inst.remote_entry_url,
        "props": inst.props,
    }

@app.post("/api/token/exchange")
async def token_exchange():
    return {"token": "mock-stargate-token-12345"}

@app.get("/api/employee/detail/{year}")
async def employee_detail(year: int, authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    detail = EMPLOYEE_DETAIL.get(year)
    if detail is None:
        raise HTTPException(status_code=404, detail="Year not found")
    return detail

# ── MCP resources/read 接口 ───────────────────────────────────────
# AppRenderer 通过 onReadResource 回调间接调用此接口（经由 CF-Agent /resource-proxy）
@app.get("/mcp/resources/read")
async def mcp_resources_read(uri: str):
    if not uri.startswith("ui://stargate/card/"):
        raise HTTPException(status_code=404, detail="Unknown resource URI")
    card_id = uri.removeprefix("ui://stargate/card/")
    inst = card_cache.get(card_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="Card instance not found or expired")
    sse_logger.emit("SG-Agent", "CF-Agent", "mcp-resources/read", uri)
    return {
        "componentName": inst.component_name,
        "remoteEntryUrl": inst.remote_entry_url,
        "props": inst.props,
    }

# ── A2A Task Handler ──────────────────────────────────────────────

class StargateTaskHandler(TaskHandler):
    async def handle_task(self, task: Task) -> Task:
        user_text = ""
        if task.history:
            last_msg = task.history[-1]
            for part in last_msg.parts:
                if hasattr(part, "text"):
                    user_text = part.text
                    break

        sse_logger.emit("SG-Agent", "LLM", "llm-call", "tool selection")
        tool_name, tool_args = await llm.select_tool(user_text)

        if tool_name == "query_employee_trend":
            sse_logger.emit("SG-Agent", "ResourceCenter", "http", "GET /api/components/EmployeeChart")
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{RESOURCE_CENTER_URL}/api/components/EmployeeChart")
                component_info = resp.json()

            trend_data = [
                {"year": 2019, "count": 7000},
                {"year": 2020, "count": 10000},
                {"year": 2021, "count": 16000},
                {"year": 2022, "count": 22000},
                {"year": 2023, "count": 18000},
            ]
            card_id = card_cache.put(
                component_name=component_info["componentName"],
                remote_entry_url=component_info["remoteEntryUrl"],
                props={"data": trend_data},
            )
            sse_logger.emit("SG-Agent", "CF-Agent", "A2A Response", f"mcp_ui_resource card/{card_id}")
            task.artifacts = [
                Message(
                    role="agent",
                    parts=[
                        TextPart(text=f"已为您查询快手历年员工趋势数据，共 {len(trend_data)} 年记录。"),
                        DataPart(
                            data={
                                "kind": "mcp_ui_resource",
                                "resourceUri": f"ui://stargate/card/{card_id}",
                                "uiMetadata": {
                                    "preferred-frame-size": {"width": 560, "height": 420}
                                },
                            },
                            media_type="application/json",
                        ),
                    ],
                )
            ]
        else:
            task.artifacts = [
                Message(
                    role="agent",
                    parts=[TextPart(text="抱歉，我目前只支持查询员工趋势数据。")],
                )
            ]

        task.status.state = "completed"
        return task

# ── 启动 ─────────────────────────────────────────────────────────

def main():
    import uvicorn
    from python_a2a import run_server

    # A2A Server 挂载到 FastAPI app 上
    a2a_handler = StargateTaskHandler()
    # python-a2a 支持 mount_to_app 方式
    # 将 A2A 路由注册到 /a2a 前缀
    try:
        from python_a2a import mount_a2a_routes
        mount_a2a_routes(app, handler=a2a_handler, prefix="/a2a")
    except ImportError:
        # 若 python-a2a 版本不支持 mount，单独起 A2A Server
        pass

    uvicorn.run(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
```

> **注意：** `python-a2a` 各版本 API 略有差异。若 `mount_a2a_routes` 不存在，参考下方"Step 8：处理 A2A 与 FastAPI 共存"。

**Step 8: 处理 A2A 与 FastAPI 共存**

检查 `python-a2a` 实际安装版本：

```bash
cd packages/stargate-agent && uv run python -c "import python_a2a; print(python_a2a.__version__)"
```

若版本 < 0.5 或无 `mount_a2a_routes`，改用并行启动方式：在 `main.py` 末尾替换为：

```python
def main():
    import threading
    import uvicorn
    from python_a2a import A2AServer

    a2a_server = A2AServer(
        task_handler=StargateTaskHandler(),
        host="0.0.0.0",
        port=3011,  # A2A 走独立端口
    )
    t = threading.Thread(target=a2a_server.run, daemon=True)
    t.start()
    uvicorn.run(app, host="0.0.0.0", port=PORT)
```

此时 CF-Agent 调用 SG-Agent 的 A2A 地址改为 `http://localhost:3011`，FastAPI HTTP 接口仍在 3001。

**Step 9: 创建 src/stargate_agent/__init__.py**

```python
```

（空文件，使 Python 识别为包）

**Step 10: 创建 package.json（pnpm dev 启动脚本）**

```json
{
  "name": "stargate-agent",
  "version": "0.0.1",
  "scripts": {
    "dev": "cd packages/stargate-agent && uv run python -m stargate_agent.main"
  }
}
```

**Step 11: 安装 Python 依赖**

```bash
cd packages/stargate-agent && uv sync
```

**Step 12: 启动并手动测试**

先启动 resource-center-mock（端口 3003），然后：

```bash
cd packages/stargate-agent && uv run python -m stargate_agent.main
```

另开终端测试健康检查：

```bash
curl http://localhost:3001/health
```

预期：`{"ok":true}`

**Step 13: 测试 token/exchange**

```bash
curl -X POST http://localhost:3001/api/token/exchange
```

预期：`{"token":"mock-stargate-token-12345"}`

**Step 14: 提交**

```bash
git add packages/stargate-agent && git commit -m "feat: stargate-agent"
```

---

## Task 5: codeflicker-agent（Python，端口 3002）

LLM 意图识别 → A2A 调用 SG-Agent → 透传 parts 给前端。提供 `/chat`（POST）、`/resource-proxy`（GET）、`/events`（GET SSE）接口。

**Files:**
- Create: `packages/codeflicker-agent/pyproject.toml`
- Create: `packages/codeflicker-agent/src/codeflicker_agent/__init__.py`
- Create: `packages/codeflicker-agent/src/codeflicker_agent/main.py`
- Create: `packages/codeflicker-agent/src/codeflicker_agent/llm.py`
- Create: `packages/codeflicker-agent/src/codeflicker_agent/sse_logger.py`
- Create: `packages/codeflicker-agent/package.json`

**Step 1: 创建 pyproject.toml**

```toml
[project]
name = "codeflicker-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "python-a2a>=0.5.0",
    "openai>=1.30.0",
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.29.0",
    "httpx>=0.27.0",
    "python-dotenv>=1.0.1",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/codeflicker_agent"]
```

**Step 2: 复用 sse_logger.py**

将 `stargate-agent` 中的 `sse_logger.py` 内容原样复制到 `packages/codeflicker-agent/src/codeflicker_agent/sse_logger.py`（两个 Agent 各自独立，不共享包）。

**Step 3: 创建 src/codeflicker_agent/llm.py**

CF-Agent 的 LLM 用于意图识别，判断用户消息是否需要转发给 SG-Agent。

```python
import os
from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None

def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
    return _client

async def detect_intent(user_message: str) -> str:
    """返回 'query_data' 或 'general_chat'"""
    client = _get_client()
    model = os.environ.get("LLM_MODEL", "gpt-4o")
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是 CodeFlicker 助手的意图识别器。"
                    "如果用户想查询数据（如员工、财务、趋势等），回复 'query_data'；"
                    "否则回复 'general_chat'。只返回这两个值之一，不要其他内容。"
                ),
            },
            {"role": "user", "content": user_message},
        ],
    )
    return response.choices[0].message.content.strip()
```

**Step 4: 创建 src/codeflicker_agent/main.py**

```python
import os
import json
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from python_a2a import A2AClient, Message, TextPart

from codeflicker_agent import llm, sse_logger

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../../.env"))

SG_AGENT_A2A_URL = os.environ.get("SG_AGENT_A2A_URL", "http://localhost:3001/a2a")
SG_AGENT_BASE_URL = os.environ.get("SG_AGENT_BASE_URL", "http://localhost:3001")
PORT = int(os.environ.get("CF_AGENT_PORT", 3002))

app = FastAPI(title="codeflicker-agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/events")
async def events():
    return StreamingResponse(sse_logger.subscribe(), media_type="text/event-stream")

@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    user_message: str = body.get("message", "")

    sse_logger.emit("Frontend", "CF-Agent", "chat", user_message[:50])
    sse_logger.emit("CF-Agent", "LLM", "llm-call", "intent detection")

    intent = await llm.detect_intent(user_message)

    if intent == "query_data":
        sse_logger.emit("CF-Agent", "SG-Agent", "A2A Task", user_message[:50])
        client = A2AClient(base_url=SG_AGENT_A2A_URL)
        task = await client.send_message(
            Message(role="user", parts=[TextPart(text=user_message)])
        )
        parts = []
        if task.artifacts:
            for artifact in task.artifacts:
                for part in artifact.parts:
                    if hasattr(part, "text"):
                        parts.append({"kind": "text", "text": part.text})
                    elif hasattr(part, "data"):
                        parts.append(part.data)

        sse_logger.emit("SG-Agent", "CF-Agent", "A2A Response", f"{len(parts)} parts")
        return JSONResponse({"parts": parts})
    else:
        return JSONResponse({
            "parts": [{"kind": "text", "text": "您好！我是 CodeFlicker 助手，可以帮您查询快手员工趋势等数据。"}]
        })

@app.get("/resource-proxy")
async def resource_proxy(uri: str):
    """代理 MCP resources/read 请求到对应 Agent"""
    sse_logger.emit("Frontend", "CF-Agent", "resource-proxy", uri)
    # 解析 uri host，路由到对应 Agent
    # uri 格式：ui://stargate/card/{id}
    if uri.startswith("ui://stargate/"):
        sse_logger.emit("CF-Agent", "SG-Agent", "MCP resources/read", uri)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{SG_AGENT_BASE_URL}/mcp/resources/read",
                params={"uri": uri},
            )
            return JSONResponse(resp.json())
    return JSONResponse({"error": "Unknown resource host"}, status_code=404)

def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
```

**Step 5: 创建 src/codeflicker_agent/__init__.py**

```python
```

**Step 6: 创建 package.json**

```json
{
  "name": "codeflicker-agent",
  "version": "0.0.1",
  "scripts": {
    "dev": "cd packages/codeflicker-agent && uv run python -m codeflicker_agent.main"
  }
}
```

**Step 7: 安装依赖并测试**

```bash
cd packages/codeflicker-agent && uv sync
uv run python -m codeflicker_agent.main
```

另开终端：

```bash
curl http://localhost:3002/health
```

预期：`{"ok":true}`

**Step 8: 测试 /chat（先确保 SG-Agent 运行中）**

```bash
curl -X POST http://localhost:3002/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"帮我查一下快手历年员工人数趋势"}'
```

预期返回包含 `"kind": "mcp_ui_resource"` 的 parts 数组：

```json
{
  "parts": [
    {"kind": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"},
    {"kind": "mcp_ui_resource", "resourceUri": "ui://stargate/card/xxxx-xxxx", ...}
  ]
}
```

**Step 9: 提交**

```bash
git add packages/codeflicker-agent && git commit -m "feat: codeflicker-agent"
```

---

## Task 6: codeflicker-frontend（React，端口 3000）

三区域布局：对话列表（文本气泡 + AppRenderer 卡片）、输入框、右侧数据流转记录器 Panel。

**Files:**
- Create: `packages/codeflicker-frontend/package.json`
- Create: `packages/codeflicker-frontend/vite.config.ts`
- Create: `packages/codeflicker-frontend/tsconfig.json`
- Create: `packages/codeflicker-frontend/index.html`
- Create: `packages/codeflicker-frontend/src/main.tsx`
- Create: `packages/codeflicker-frontend/src/App.tsx`
- Create: `packages/codeflicker-frontend/src/components/ChatMessage.tsx`
- Create: `packages/codeflicker-frontend/src/components/CardMessage.tsx`
- Create: `packages/codeflicker-frontend/src/components/EventLog.tsx`
- Create: `packages/codeflicker-frontend/src/hooks/useEventLog.ts`
- Create: `packages/codeflicker-frontend/src/types.ts`
- Create: `packages/codeflicker-frontend/public/sandbox_proxy.html`

**Step 1: 了解 @mcp-ui/client AppRenderer 的工作方式**

`AppRenderer` 不内置 MCP Client 网络层，所有 MCP 请求通过回调处理。本项目核心用法：

```tsx
<AppRenderer
  onReadResource={async ({ uri }) => {
    const res = await fetch(`http://localhost:3002/resource-proxy?uri=${encodeURIComponent(uri)}`);
    const data = await res.json();
    return {
      contents: [{
        uri,
        mimeType: 'application/json',
        text: JSON.stringify(data),
      }],
    };
  }}
  toolName="query_employee_trend"
  toolResult={toolResult}  // 从 /chat 响应的 mcp_ui_resource part 中提取
/>
```

`toolResult` 的结构需符合 MCP `CallToolResult` 格式：

```typescript
{
  content: [{
    type: 'resource',
    resource: {
      uri: 'ui://stargate/card/xxxx',
      mimeType: 'text/html;profile=mcp-app',
      text: '',  // 占位，实际内容由 onReadResource 获取
    }
  }]
}
```

**Step 2: 了解模块联邦动态加载方式**

`AppRenderer` 拿到 `onReadResource` 返回的数据后（`componentName` + `remoteEntryUrl` + `props`），前端需要自己实现 MF 加载逻辑并渲染卡片。本项目通过 `CardMessage` 组件实现：

```typescript
declare const __webpack_share_scopes__: { default: object };

async function loadRemoteComponent(remoteEntryUrl: string, exposedModule: string) {
  const container = await import(/* webpackIgnore: true */ remoteEntryUrl) as any;
  await container.init(__webpack_share_scopes__.default);
  const factory = await container.get(exposedModule);
  return factory().default;
}
```

> **注意：** 前端也使用 Vite，Vite 不原生支持 `__webpack_share_scopes__`。此处采用更简单的方式：直接通过 `<script>` 标签动态注入 `remoteEntry.js`，再通过 `window[containerName]` 访问。详见 Step 6。

**Step 3: 创建 package.json**

```json
{
  "name": "codeflicker-frontend",
  "version": "0.0.1",
  "scripts": {
    "dev": "vite --port 3000",
    "build": "tsc && vite build"
  },
  "dependencies": {
    "@mcp-ui/client": "^0.1.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.1",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.4.0",
    "vite": "^5.2.0"
  }
}
```

**Step 4: 创建 vite.config.ts**

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/chat': 'http://localhost:3002',
      '/resource-proxy': 'http://localhost:3002',
    },
  },
});
```

**Step 5: 创建 tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "lib": ["ES2020", "DOM"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "esModuleInterop": true
  },
  "include": ["src"]
}
```

**Step 6: 创建 src/types.ts**

```typescript
export interface TextPart {
  kind: 'text';
  text: string;
}

export interface McpUiResourcePart {
  kind: 'mcp_ui_resource';
  resourceUri: string;
  uiMetadata?: { 'preferred-frame-size'?: { width: number; height: number } };
}

export type MessagePart = TextPart | McpUiResourcePart;

export interface ChatMessage {
  id: string;
  role: 'user' | 'agent';
  parts: MessagePart[];
}

export interface CardData {
  componentName: string;
  remoteEntryUrl: string;
  props: Record<string, unknown>;
}

export interface EventLogEntry {
  time: string;
  source: string;
  target: string;
  type: string;
  detail: string;
}
```

**Step 7: 创建 src/hooks/useEventLog.ts**

```typescript
import { useEffect, useState } from 'react';
import type { EventLogEntry } from '../types';

export function useEventLog(urls: string[]) {
  const [entries, setEntries] = useState<EventLogEntry[]>([]);

  useEffect(() => {
    const sources = urls.map((url) => {
      const es = new EventSource(url);
      es.onmessage = (e) => {
        try {
          const entry: EventLogEntry = JSON.parse(e.data);
          setEntries((prev) => [...prev.slice(-99), entry]);
        } catch {}
      };
      return es;
    });
    return () => sources.forEach((es) => es.close());
  }, []);

  return entries;
}
```

**Step 8: 创建 src/components/EventLog.tsx**

```tsx
import React from 'react';
import type { EventLogEntry } from '../types';

interface Props {
  entries: EventLogEntry[];
}

export const EventLog: React.FC<Props> = ({ entries }) => (
  <div style={{ fontFamily: 'monospace', fontSize: 12, overflowY: 'auto', height: '100%', background: '#1a1a2e', color: '#a0d2eb', padding: 8 }}>
    <div style={{ marginBottom: 4, color: '#e0e0e0', borderBottom: '1px solid #333', paddingBottom: 4 }}>
      数据流转记录器
    </div>
    {entries.map((e, i) => (
      <div key={i} style={{ marginBottom: 2 }}>
        <span style={{ color: '#888' }}>[{e.time}]</span>{' '}
        <span style={{ color: '#64dfdf' }}>{e.source.padEnd(12)}</span>
        {' → '}
        <span style={{ color: '#80ed99' }}>{e.target.padEnd(14)}</span>
        {' '}
        <span style={{ color: '#f9c74f' }}>{e.type}</span>
        {e.detail ? <span style={{ color: '#ccc' }}>: {e.detail}</span> : null}
      </div>
    ))}
  </div>
);
```

**Step 9: 创建 src/components/ChatMessage.tsx**

```tsx
import React from 'react';
import type { ChatMessage as ChatMessageType } from '../types';
import { CardMessage } from './CardMessage';

interface Props {
  message: ChatMessageType;
}

export const ChatMessage: React.FC<Props> = ({ message }) => (
  <div style={{ marginBottom: 12, display: 'flex', flexDirection: message.role === 'user' ? 'row-reverse' : 'row', gap: 8 }}>
    <div style={{ maxWidth: '80%' }}>
      {message.parts.map((part, i) => {
        if (part.kind === 'text') {
          return (
            <div key={i} style={{
              background: message.role === 'user' ? '#0084ff' : '#f0f0f0',
              color: message.role === 'user' ? '#fff' : '#333',
              padding: '8px 12px',
              borderRadius: 12,
              marginBottom: 4,
            }}>
              {part.text}
            </div>
          );
        }
        if (part.kind === 'mcp_ui_resource') {
          return <CardMessage key={i} resourceUri={part.resourceUri} uiMetadata={part.uiMetadata} />;
        }
        return null;
      })}
    </div>
  </div>
);
```

**Step 10: 创建 src/components/CardMessage.tsx**

此组件负责：调用 `/resource-proxy` 获取卡片数据 → 换取 stargateToken → 动态加载 MF 组件 → 渲染。

```tsx
import React, { useEffect, useState } from 'react';
import type { CardData, McpUiResourcePart } from '../types';

interface Props {
  resourceUri: string;
  uiMetadata?: McpUiResourcePart['uiMetadata'];
}

type Status = 'loading' | 'error' | 'ready';

async function loadMFComponent(remoteEntryUrl: string, componentName: string): Promise<React.ComponentType<any>> {
  return new Promise((resolve, reject) => {
    const containerId = `mf_${componentName}`;
    if ((window as any)[containerId]) {
      resolveMF(containerId, componentName, resolve, reject);
      return;
    }
    const script = document.createElement('script');
    script.src = remoteEntryUrl;
    script.onload = () => resolveMF(containerId, componentName, resolve, reject);
    script.onerror = () => reject(new Error(`Failed to load ${remoteEntryUrl}`));
    document.head.appendChild(script);
  });
}

async function resolveMF(
  containerId: string,
  componentName: string,
  resolve: (c: React.ComponentType<any>) => void,
  reject: (e: Error) => void
) {
  const container = (window as any)[containerId];
  if (!container) { reject(new Error('Container not found')); return; }
  await container.init({});
  const factory = await container.get(`./${componentName}`);
  resolve(factory().default);
}

export const CardMessage: React.FC<Props> = ({ resourceUri, uiMetadata }) => {
  const [status, setStatus] = useState<Status>('loading');
  const [cardData, setCardData] = useState<CardData | null>(null);
  const [token, setToken] = useState('');
  const [Component, setComponent] = useState<React.ComponentType<any> | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const proxyRes = await fetch(`/resource-proxy?uri=${encodeURIComponent(resourceUri)}`);
        const data: CardData = await proxyRes.json();

        const tokenRes = await fetch('http://localhost:3001/api/token/exchange', { method: 'POST' });
        const { token: stargateToken } = await tokenRes.json();

        const Comp = await loadMFComponent(data.remoteEntryUrl, data.componentName);

        setCardData(data);
        setToken(stargateToken);
        setComponent(() => Comp);
        setStatus('ready');
      } catch (e) {
        console.error(e);
        setStatus('error');
      }
    })();
  }, [resourceUri]);

  const { width = 560, height = 420 } = uiMetadata?.['preferred-frame-size'] ?? {};

  if (status === 'loading') return <div style={{ padding: 12, color: '#888' }}>加载卡片中...</div>;
  if (status === 'error') return <div style={{ padding: 12, color: 'red' }}>卡片加载失败</div>;
  if (!Component || !cardData) return null;

  return (
    <div style={{ border: '1px solid #e0e0e0', borderRadius: 8, overflow: 'hidden', width, height }}>
      <Component {...cardData.props} token={token} />
    </div>
  );
};
```

**Step 11: 创建 src/App.tsx**

```tsx
import React, { useState, useRef } from 'react';
import type { ChatMessage as ChatMessageType, MessagePart } from './types';
import { ChatMessage } from './components/ChatMessage';
import { EventLog } from './components/EventLog';
import { useEventLog } from './hooks/useEventLog';

let msgIdCounter = 0;
const newId = () => String(++msgIdCounter);

export const App: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const eventEntries = useEventLog([
    'http://localhost:3002/events',
    'http://localhost:3001/events',
  ]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput('');
    setLoading(true);

    const userMsg: ChatMessageType = {
      id: newId(),
      role: 'user',
      parts: [{ kind: 'text', text }],
    };
    setMessages((prev) => [...prev, userMsg]);

    try {
      const res = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json();
      const parts: MessagePart[] = (data.parts ?? []).map((p: any) => {
        if (p.kind === 'text') return { kind: 'text' as const, text: p.text };
        if (p.kind === 'mcp_ui_resource') return {
          kind: 'mcp_ui_resource' as const,
          resourceUri: p.resourceUri,
          uiMetadata: p.uiMetadata,
        };
        return { kind: 'text' as const, text: JSON.stringify(p) };
      });
      const agentMsg: ChatMessageType = { id: newId(), role: 'agent', parts };
      setMessages((prev) => [...prev, agentMsg]);
    } catch {
      setMessages((prev) => [...prev, {
        id: newId(), role: 'agent',
        parts: [{ kind: 'text', text: '请求失败，请检查服务是否启动。' }],
      }]);
    } finally {
      setLoading(false);
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh', fontFamily: 'system-ui, sans-serif' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', borderRight: '1px solid #e0e0e0' }}>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid #e0e0e0', fontWeight: 600 }}>
          CodeFlicker x MCP-UI Demo
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          {messages.map((m) => <ChatMessage key={m.id} message={m} />)}
          {loading && <div style={{ color: '#888', padding: '8px 0' }}>思考中...</div>}
          <div ref={bottomRef} />
        </div>
        <div style={{ padding: 12, borderTop: '1px solid #e0e0e0', display: 'flex', gap: 8 }}>
          <input
            style={{ flex: 1, padding: '8px 12px', borderRadius: 8, border: '1px solid #ccc', fontSize: 14 }}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
            placeholder="输入消息，例如：查询快手历年员工人数趋势"
            disabled={loading}
          />
          <button
            style={{ padding: '8px 16px', borderRadius: 8, background: '#0084ff', color: '#fff', border: 'none', cursor: 'pointer' }}
            onClick={sendMessage}
            disabled={loading}
          >
            发送
          </button>
        </div>
      </div>
      <div style={{ width: 420, overflow: 'hidden' }}>
        <EventLog entries={eventEntries} />
      </div>
    </div>
  );
};
```

**Step 12: 创建 src/main.tsx**

```tsx
import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';

createRoot(document.getElementById('root')!).render(<App />);
```

**Step 13: 创建 index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>CodeFlicker x MCP-UI Demo</title>
    <style>* { box-sizing: border-box; margin: 0; padding: 0; }</style>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

**Step 14: 创建 public/sandbox_proxy.html**

AppRenderer 使用此文件作为 iframe 沙箱代理（`sandbox.url`），若不用 AppRenderer 可忽略，但需要文件存在。

```html
<!DOCTYPE html>
<html>
  <head><meta charset="UTF-8" /></head>
  <body><script>
    window.addEventListener('message', (e) => {
      if (e.data && e.data.type === 'mcp-ui-proxy-init') {
        window.parent.postMessage({ type: 'mcp-ui-proxy-ready' }, '*');
      }
    });
  </script></body>
</html>
```

**Step 15: 安装依赖并启动**

```bash
cd packages/codeflicker-frontend && pnpm install
pnpm dev
```

浏览器打开 `http://localhost:3000`，应看到聊天界面。

**Step 16: 提交**

```bash
git add packages/codeflicker-frontend && git commit -m "feat: codeflicker-frontend"
```

---

## Task 7: 端到端联调

**Step 1: 确认所有服务依次启动**

按以下顺序，各开一个终端：

```bash
# Terminal 1
cd packages/resource-center-mock && pnpm dev

# Terminal 2
cd packages/employee-chart-card && pnpm dev

# Terminal 3
cd packages/stargate-agent && uv run python -m stargate_agent.main

# Terminal 4
cd packages/codeflicker-agent && uv run python -m codeflicker_agent.main

# Terminal 5
cd packages/codeflicker-frontend && pnpm dev
```

**Step 2: 健康检查所有服务**

```bash
curl http://localhost:3003/health
curl http://localhost:3001/health
curl http://localhost:3002/health
curl -I http://localhost:3004/remoteEntry.js
```

全部预期：200 OK。

**Step 3: 验证完整链路**

浏览器打开 `http://localhost:3000`，在输入框输入：

```
帮我查一下快手历年员工人数趋势
```

**预期行为（按顺序）：**

1. 右侧 EventLog 出现：`Frontend → CF-Agent: chat`
2. 出现：`CF-Agent → LLM: llm-call: intent detection`
3. 出现：`CF-Agent → SG-Agent: A2A Task`
4. 出现：`SG-Agent → LLM: llm-call: tool selection`
5. 出现：`SG-Agent → ResourceCenter: http: GET /api/components/EmployeeChart`
6. 出现：`SG-Agent → CF-Agent: A2A Response: mcp_ui_resource`
7. 对话区出现文本气泡："已为您查询快手历年员工趋势数据..."
8. 出现：`Frontend → CF-Agent: resource-proxy`
9. 出现：`CF-Agent → SG-Agent: MCP resources/read`
10. 对话区出现 EmployeeChart 折线图卡片

**Step 4: 验证路径 A（卡片直调 API）**

在渲染出的卡片中点击任意"XXXX 详情"按钮，应弹出 alert 显示年份详情数据。

**Step 5: 验证路径 B（postMessage 触发 Agent）**

点击卡片中的"分析趋势"按钮，应在对话区触发新一轮 Agent 对话（注意：需在 `App.tsx` 的 `CardMessage` 中监听 `agent_submit` postMessage 并调用 `sendMessage`，见下方补充）。

**Step 5 补充：在 App.tsx 中监听卡片 postMessage**

在 `App.tsx` 的 `useEffect` 中添加全局监听：

```tsx
useEffect(() => {
  const handler = (e: MessageEvent) => {
    if (e.data?.type === 'agent_submit') {
      setInput(`分析以下员工趋势数据：${JSON.stringify(e.data.payload?.data)}`);
    }
  };
  window.addEventListener('message', handler);
  return () => window.removeEventListener('message', handler);
}, []);
```

**Step 6: 提交**

```bash
git add -A && git commit -m "feat: end-to-end integration complete"
```

---

## Task 8: pnpm dev 并发启动（可选优化）

为了一条命令启动所有服务，需要每个 `package.json` 都有 `dev` 脚本，且 Python 服务通过 `package.json` 包装（Task 4、5 已完成）。

**Step 1: 更新根 package.json**

```json
{
  "name": "a2a-mcpui",
  "private": true,
  "scripts": {
    "dev": "pnpm --parallel --stream -r run dev",
    "build": "pnpm -r run build"
  }
}
```

**Step 2: 验证并发启动**

```bash
pnpm dev
```

预期：5 个服务同时启动，日志混合输出，前缀标注各包名。

**Step 3: 提交**

```bash
git add package.json && git commit -m "chore: add parallel dev script"
```

---

## 常见问题排查

### python-a2a 版本兼容性

若 `A2AClient.send_message` 不存在，查看实际 API：

```bash
cd packages/codeflicker-agent && uv run python -c "import python_a2a; help(python_a2a.A2AClient)"
```

`python-a2a` 0.5.x 的 `A2AClient` 方法名可能为 `send_task` 或 `create_task`，按实际 API 调整 `codeflicker_agent/main.py`。

### MF 加载失败（`container.init({})` 报错）

Webpack 5 的 `container.init()` 需要传入共享作用域。若纯 HTML/Vite 环境没有 `__webpack_share_scopes__`，传空对象 `{}` 即可：

```javascript
await container.init({});
```

若仍报错，尝试：

```javascript
if (container.__initialized) {
  // skip
} else {
  await container.init({});
  container.__initialized = true;
}
```

### CORS 错误

所有 Python 服务已配置 `allow_origins=["*"]`。若仍有 CORS 错误，检查 Vite proxy 配置，确认 `/chat` 和 `/resource-proxy` 请求走代理（返回 vite-proxied 请求而非直接请求 3002）。

### SSE 连接断开

浏览器对同域 SSE 连接数有限制（HTTP/1.1 默认 6 个）。本项目连接 2 个 SSE（CF-Agent + SG-Agent），不超限。若断开，检查防火墙或代理是否超时断开长连接。
