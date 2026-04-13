# stargate-mcp-ui-server Implementation Plan

**Goal:** 新增独立 Python 服务 `stargate-mcp-ui-server`（端口 3002），通过标准 MCP 协议（SSE + JSON-RPC）暴露 `query_employee_trend` tool 及 `ui://stargate/employee-trend` resource，完整实现 MCP-UI 规范。

**Architecture:** 使用 `mcp[server]` SDK 在 `main.py` 中注册 SSE 传输的 MCP Server；tool 与 resource 均定义在该 server 内，`tools.py` 负责内联业务数据并调用 `mcp_ui_server.create_ui_resource()` 生成 UIResource；resource URI 为静态（`ui://stargate/employee-trend`），每次 tool 调用覆盖同一份内容，无需缓存层。

**Tech Stack:** Python 3.11、`mcp[server]>=1.5.0`、`mcp-ui-server>=1.0.0`、`uvicorn[standard]`、`python-dotenv`、`uv`（依赖管理）。

---

## 背景：理解现有代码

**你需要读懂以下内容才能顺利实施：**

- `packages/stargate-agent/pyproject.toml`：现有 agent 的依赖配置。新服务的 `pyproject.toml` 结构与之完全相同，照搬即可。
- `packages/stargate-agent/src/stargate_agent/main.py`：
  - `EMPLOYEE_DETAIL` 字典（第 23-28 行）是业务数据来源，`stargate-mcp-ui-server` 会内联相同数据。
  - `mcp_resources_read()` 函数（约第 60-116 行）内有完整 HTML 模板，`build_html()` 将提取这段逻辑。
  - `create_ui_resource()` 调用方式：`create_ui_resource({"uri": ..., "content": {"type": "rawHtml", "htmlString": ...}, "encoding": "text"})`，返回 Pydantic 对象，用 `.model_dump(mode="json")` 序列化。
- `packages/stargate-agent/src/stargate_agent/sse_logger.py`：新服务 **不需要** sse_logger，不要复制。
- `packages/stargate-agent/src/stargate_agent/llm.py`：新服务 **不需要** LLM 调用，tool handler 直接返回 UIResource。

**MCP SDK 关键 API（`mcp[server]`）：**

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("stargate-mcp-ui-server")

@mcp.tool()
async def query_employee_trend() -> dict:
    ...

@mcp.resource("ui://stargate/employee-trend")
async def employee_trend_resource() -> str:
    ...

if __name__ == "__main__":
    mcp.run(transport="sse")  # 默认监听 0.0.0.0:8000，通过环境变量 PORT 覆盖
```

> 注意：`FastMCP.run(transport="sse")` 会启动内置 uvicorn，端口通过环境变量 `PORT`（或 `FASTMCP_PORT`）配置，具体以 SDK 文档为准。启动后检查实际监听端口。

**`create_ui_resource()` 返回值结构：**

```python
resource = create_ui_resource({...})
r = resource.model_dump(mode="json")
# r["resource"]["uri"]  → "ui://stargate/employee-trend"
# r["resource"]["text"] → HTML 字符串
```

---

## Task 1：创建包目录结构

**Files:**
- Create: `packages/stargate-mcp-ui-server/pyproject.toml`
- Create: `packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/__init__.py`

### Step 1：创建目录

```bash
mkdir -p packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server
```

### Step 2：创建 `pyproject.toml`

创建 `packages/stargate-mcp-ui-server/pyproject.toml`，内容：

```toml
[project]
name = "stargate-mcp-ui-server"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "mcp[server]>=1.5.0",
    "mcp-ui-server>=1.0.0",
    "uvicorn[standard]>=0.29.0",
    "python-dotenv>=1.0.1",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/stargate_mcp_ui_server"]
```

### Step 3：创建空 `__init__.py`

创建 `packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/__init__.py`，内容为空（文件存在即可）。

### Step 4：安装依赖

```bash
cd packages/stargate-mcp-ui-server && uv sync
```

预期：输出 `Resolved ... packages` 并最终无报错。

### Step 5：验证依赖可导入

```bash
cd packages/stargate-mcp-ui-server && .venv/bin/python -c "from mcp.server.fastmcp import FastMCP; from mcp_ui_server import create_ui_resource; print('ok')"
```

预期输出：`ok`

---

## Task 2：实现 `tools.py`（业务数据 + HTML 生成）

**Files:**
- Create: `packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/tools.py`

### 背景说明

`tools.py` 只做两件事：
1. `build_html()` —— 内联员工数据，生成与 `stargate-agent` 中 `mcp_resources_read()` 完全相同格式的 HTML（复制 Module Federation 引导代码）。
2. `get_ui_resource()` —— 调用 `create_ui_resource()` 并返回 `.model_dump(mode="json")` 结果。

HTML 模板直接从 `packages/stargate-agent/src/stargate_agent/main.py`（第 68-101 行）复制并去掉动态 `card_id`/`uri` 变量，改用固定的 `RESOURCE_URI`。

### Step 1：编写测试文件（先写测试）

创建 `packages/stargate-mcp-ui-server/tests/__init__.py`（空文件）。

创建 `packages/stargate-mcp-ui-server/tests/test_tools.py`：

```python
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from stargate_mcp_ui_server.tools import build_html, get_ui_resource, RESOURCE_URI


def test_resource_uri_is_static():
    assert RESOURCE_URI == "ui://stargate/employee-trend"


def test_build_html_contains_employee_data():
    html = build_html()
    assert "2019" in html
    assert "7000" in html
    assert "employeeChartCard" in html


def test_build_html_contains_react_scripts():
    html = build_html()
    assert "react.production.min.js" in html
    assert "react-dom.production.min.js" in html


def test_get_ui_resource_structure():
    result = get_ui_resource()
    assert isinstance(result, dict)
    assert "resource" in result
    assert result["resource"]["uri"] == RESOURCE_URI
    assert len(result["resource"]["text"]) > 100
```

### Step 2：运行测试确认失败

```bash
cd packages/stargate-mcp-ui-server && .venv/bin/python -m pytest tests/test_tools.py -v
```

预期：`ModuleNotFoundError: No module named 'stargate_mcp_ui_server'`（文件还不存在）。

### Step 3：实现 `tools.py`

创建 `packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/tools.py`：

```python
from mcp_ui_server import create_ui_resource

RESOURCE_URI = "ui://stargate/employee-trend"

REMOTE_ENTRY_URL = "http://localhost:3004/remoteEntry.js"
COMPONENT_NAME = "EmployeeChart"
CONTAINER_NAME = "employeeChartCard"
TOKEN = "mock-stargate-token-12345"

TREND_DATA = [
    {"year": 2019, "count": 7000},
    {"year": 2020, "count": 10000},
    {"year": 2021, "count": 16000},
    {"year": 2022, "count": 22000},
    {"year": 2023, "count": 18000},
]


def build_html() -> str:
    import json
    props_json = json.dumps(TREND_DATA, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
</head>
<body style="margin:0">
<div id="root"></div>
<script src="{REMOTE_ENTRY_URL}"></script>
<script>
(function() {{
  var data = {props_json};
  var token = "{TOKEN}";
  Promise.resolve().then(function() {{
    if (typeof {CONTAINER_NAME} === 'undefined') throw new Error('Container {CONTAINER_NAME} not found');
    var shareScope = Object.create(null);
    shareScope['default'] = {{}};
    shareScope['default']['react'] = {{
      '18.3.1': {{ get: function() {{ return function() {{ return React; }}; }}, loaded: 1, from: 'host' }}
    }};
    shareScope['default']['react-dom'] = {{
      '18.3.1': {{ get: function() {{ return function() {{ return ReactDOM; }}; }}, loaded: 1, from: 'host' }}
    }};
    if ({CONTAINER_NAME}.init) {{
      try {{ {CONTAINER_NAME}.init(shareScope['default']); }} catch(e) {{}}
    }}
    return {CONTAINER_NAME}.get('./{COMPONENT_NAME}');
  }}).then(function(factory) {{
    var Comp = factory().default;
    ReactDOM.createRoot(document.getElementById('root'))
      .render(React.createElement(Comp, {{ data: data, token: token }}));
  }}).catch(function(e) {{
    document.body.innerHTML = '<p style="color:red;padding:16px">加载失败: ' + e.message + '</p>';
  }});
}})();
</script>
</body></html>"""


def get_ui_resource() -> dict:
    resource = create_ui_resource({
        "uri": RESOURCE_URI,
        "content": {"type": "rawHtml", "htmlString": build_html()},
        "encoding": "text",
    })
    return resource.model_dump(mode="json")
```

### Step 4：运行测试确认通过

```bash
cd packages/stargate-mcp-ui-server && .venv/bin/python -m pytest tests/test_tools.py -v
```

预期：4 个测试全部 PASS。

---

## Task 3：实现 `main.py`（MCP Server 入口）

**Files:**
- Create: `packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/main.py`
- Test: `packages/stargate-mcp-ui-server/tests/test_main.py`

### Step 1：编写测试

创建 `packages/stargate-mcp-ui-server/tests/test_main.py`：

```python
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
from stargate_mcp_ui_server.main import mcp
from stargate_mcp_ui_server.tools import RESOURCE_URI


def test_mcp_server_name():
    assert mcp.name == "stargate-mcp-ui-server"


def test_tool_registered():
    tool_names = [t.name for t in mcp._tool_manager.list_tools()]
    assert "query_employee_trend" in tool_names


@pytest.mark.asyncio
async def test_query_employee_trend_returns_resource_uri():
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    tool = tools["query_employee_trend"]
    result = await tool.fn()
    assert isinstance(result, dict)
    assert result.get("_meta", {}).get("ui", {}).get("resourceUri") == RESOURCE_URI
```

### Step 2：运行测试确认失败

```bash
cd packages/stargate-mcp-ui-server && .venv/bin/python -m pytest tests/test_main.py -v
```

预期：`ModuleNotFoundError: No module named 'stargate_mcp_ui_server.main'`。

> **注意**：如果 pytest 提示 `asyncio` 相关错误，需要先安装：
> ```bash
> cd packages/stargate-mcp-ui-server && uv add --dev pytest pytest-asyncio
> ```
> 并在 `pyproject.toml` 中添加：
> ```toml
> [tool.pytest.ini_options]
> asyncio_mode = "auto"
> ```

### Step 3：实现 `main.py`

创建 `packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/main.py`：

```python
import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from stargate_mcp_ui_server.tools import get_ui_resource, RESOURCE_URI

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../../../.env"))

mcp = FastMCP("stargate-mcp-ui-server")


@mcp.tool()
async def query_employee_trend() -> dict:
    r = get_ui_resource()
    return {
        "_meta": {"ui": {"resourceUri": RESOURCE_URI}},
        "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
        "resource": r["resource"],
    }


@mcp.resource(RESOURCE_URI)
async def employee_trend_resource() -> str:
    r = get_ui_resource()
    return r["resource"]["text"]


def main():
    port = int(os.environ.get("PORT", 3002))
    mcp.run(transport="sse", port=port)


if __name__ == "__main__":
    main()
```

> **重要**：`FastMCP.run()` 的签名因 SDK 版本而异。如果 `port` 参数报错，改为通过环境变量设置：
> ```python
> os.environ.setdefault("FASTMCP_PORT", str(port))
> mcp.run(transport="sse")
> ```
> 或查阅 SDK 源码：`packages/stargate-agent/.venv/lib/python3.11/site-packages/mcp/server/fastmcp/`

### Step 4：运行测试确认通过

```bash
cd packages/stargate-mcp-ui-server && .venv/bin/python -m pytest tests/ -v
```

预期：所有测试 PASS（`test_tools.py` 4 个 + `test_main.py` 3 个）。

---

## Task 4：手动验证 SSE 服务可启动

**Files:**（无新增文件）

### Step 1：启动服务

```bash
cd packages/stargate-mcp-ui-server && PORT=3002 .venv/bin/python -m stargate_mcp_ui_server.main
```

预期：服务启动，输出类似 `INFO: Uvicorn running on http://0.0.0.0:3002`。

### Step 2：验证 SSE 端点存在

打开新终端：

```bash
curl -N -H "Accept: text/event-stream" http://localhost:3002/sse
```

预期：连接建立，不立即返回（保持长连接）。用 `Ctrl+C` 断开。

### Step 3：验证 MCP JSON-RPC 初始化握手

```bash
curl -s -X POST http://localhost:3002/messages \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}}}'
```

预期：返回包含 `"result"` 字段的 JSON，其中 `serverInfo.name` 为 `"stargate-mcp-ui-server"`。

### Step 4：验证 tools/list

```bash
curl -s -X POST http://localhost:3002/messages \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

预期：返回包含 `query_employee_trend` 的 tool 列表。

### Step 5：验证 resources/list

```bash
curl -s -X POST http://localhost:3002/messages \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"resources/list","params":{}}'
```

预期：返回包含 `ui://stargate/employee-trend` 的 resource 列表。

### Step 6：调用 tools/call

```bash
curl -s -X POST http://localhost:3002/messages \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"query_employee_trend","arguments":{}}}'
```

预期：返回包含 `_meta.ui.resourceUri` 为 `"ui://stargate/employee-trend"` 的结果。

### Step 7：验证 resources/read

```bash
curl -s -X POST http://localhost:3002/messages \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":5,"method":"resources/read","params":{"uri":"ui://stargate/employee-trend"}}'
```

预期：返回包含 HTML 的 resource 内容，HTML 中含 `employeeChartCard` 和 `2019`。

---

## Task 5：集成到 monorepo 启动脚本

**Files:**
- Create: `packages/stargate-mcp-ui-server/package.json`

### 背景

`packages/` 下每个服务都有 `package.json`，根目录 `package.json` 用 `pnpm -r run dev` 并行启动所有服务。查看 `packages/stargate-agent/package.json` 了解格式。

### Step 1：查看 stargate-agent 的 package.json

```bash
cat packages/stargate-agent/package.json
```

记下 `scripts.dev` 的命令格式。

### Step 2：创建 `packages/stargate-mcp-ui-server/package.json`

```json
{
  "name": "stargate-mcp-ui-server",
  "version": "0.1.0",
  "scripts": {
    "dev": "PORT=3002 ../.venv/bin/python -m stargate_mcp_ui_server.main || PORT=3002 .venv/bin/python -m stargate_mcp_ui_server.main"
  }
}
```

> **注意**：实际 Python 路径取决于 uv venv 位置。查看 `packages/stargate-agent/package.json` 确认格式后，使用 `.venv/bin/python`（相对于 `packages/stargate-mcp-ui-server/` 目录）。实际内容应为：
> ```json
> {
>   "name": "stargate-mcp-ui-server",
>   "version": "0.1.0",
>   "scripts": {
>     "dev": "cd packages/stargate-mcp-ui-server && PORT=3002 .venv/bin/python -m stargate_mcp_ui_server.main"
>   }
> }
> ```

### Step 3：验证根目录 dev 命令能识别新服务

```bash
pnpm -r run dev --filter stargate-mcp-ui-server
```

预期：启动 `stargate-mcp-ui-server`，端口 3002 上线。

---

## Task 6：端到端冒烟测试（完整链路）

本 task 验证 `stargate-mcp-ui-server` 与其他服务协作正常。

### 前置条件：启动所有依赖服务

分别在不同终端：

```bash
# 终端 1：employee-chart-card（MF 远程组件，端口 3004）
cd packages/employee-chart-card && pnpm dev

# 终端 2：resource-center-mock（端口 3003）
cd packages/resource-center-mock && pnpm dev

# 终端 3：stargate-mcp-ui-server（端口 3002）
cd packages/stargate-mcp-ui-server && PORT=3002 .venv/bin/python -m stargate_mcp_ui_server.main
```

### Step 1：确认 /sse 端点可连接

```bash
curl -N --max-time 3 http://localhost:3002/sse 2>&1 | head -5
```

预期：有 SSE 格式输出（`data:` 行），或超时退出（超时也说明连接建立了）。

### Step 2：通过 MCP 调用 tool，确认返回 resourceUri

```bash
curl -s -X POST http://localhost:3002/messages \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"query_employee_trend","arguments":{}}}' \
  | python3 -m json.tool
```

预期：JSON 中包含 `"resourceUri": "ui://stargate/employee-trend"`。

### Step 3：读取 resource，确认返回正确 HTML

```bash
curl -s -X POST http://localhost:3002/messages \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"resources/read","params":{"uri":"ui://stargate/employee-trend"}}' \
  | python3 -m json.tool
```

验证点：
- `contents[0].uri` 为 `"ui://stargate/employee-trend"`
- `contents[0].text` 包含 `employeeChartCard`
- `contents[0].text` 包含 `"year": 2019`（或 `2019`）
- `contents[0].text` 包含 `http://localhost:3004/remoteEntry.js`

### Step 4：确认静态 URI 覆盖行为（多次调用 tool 返回相同 URI）

连续调用两次 `tools/call`，确认两次返回的 `resourceUri` 完全相同（均为 `ui://stargate/employee-trend`）——这是静态 URI 设计的核心验证。

---

## 总结：变更文件清单

| 文件 | 变更类型 | 内容 |
|---|---|---|
| `packages/stargate-mcp-ui-server/pyproject.toml` | 创建 | 项目元数据及依赖 |
| `packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/__init__.py` | 创建 | 空文件 |
| `packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/tools.py` | 创建 | 业务数据 + HTML 生成 + `get_ui_resource()` |
| `packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/main.py` | 创建 | MCP Server（SSE）、tool/resource 注册 |
| `packages/stargate-mcp-ui-server/package.json` | 创建 | monorepo `dev` 脚本 |
| `packages/stargate-mcp-ui-server/tests/__init__.py` | 创建 | 空文件 |
| `packages/stargate-mcp-ui-server/tests/test_tools.py` | 创建 | tools.py 单元测试 |
| `packages/stargate-mcp-ui-server/tests/test_main.py` | 创建 | main.py 单元测试 |

**不修改任何现有文件。**（`stargate-agent` 的废弃清理为后续独立任务。）
