# 业务数据获取解耦 Implementation Plan

**Goal:** 将业务数据（员工趋势数据、鉴权 token）从 `stargate-mcp-ui-server` 中彻底移除，改为由 `stargate-agent` 调用独立业务 API，实现 MCP Server 职责收窄为「仅提供 shell HTML」。

**Architecture:** MCP Server 删除所有业务数据常量与 `build_tool_result()`，`query_employee_trend` tool 不再携带 `toolResult` 业务数据。SG-Agent 新增 `GET /api/employee/trend` 路由作为业务数据的唯一出口，endpoint/mcp 两路均从该路由取数据并自行拼 `toolResult`。原 `_call_mcp_tool_result()` 函数删除，mcp 路径改为调 `/api/employee/trend`。场景 2（懒加载）下 `query_employee_trend_lazy` 的初始 A2A 响应只携带 token 不含 data，组件挂载后通过 `tools/call` 再次拉取完整数据，走 `/api/tool-result/` 路由。

**Tech Stack:** Python 3.11+, FastAPI, FastMCP (mcp[server] >=1.5.0), httpx, pytest, pytest-asyncio, uv

---

## 背景知识

**项目布局：**
```
packages/
  stargate-mcp-ui-server/   # 端口 3005，FastMCP SSE Server
    src/stargate_mcp_ui_server/
      tools.py              # HTML 构建 + 业务数据常量（待清理）
      main.py               # tool 注册（待清理）
    tests/
      test_tools.py
      test_main.py
  stargate-agent/           # 端口 3001/3011，FastAPI + Flask A2A
    src/stargate_agent/
      main.py               # 所有路由 + A2A 服务（需改动）
```

**运行测试命令：**
```bash
cd packages/stargate-mcp-ui-server
uv run pytest tests/ -v
```

**当前问题：**
- `tools.py` 中存在 `TOKEN`、`TREND_DATA`、`build_tool_result()` — 业务数据不应在 MCP Server 中
- `main.py` 的 `query_employee_trend` 调用 `build_tool_result()` 并将结果放入返回值的 `toolResult` 字段
- `stargate-agent/main.py` 中 `_call_mcp_tool_result()` 向 MCP Server 拉业务数据（错误依赖）
- mcp 路径的 `handle_message` 也使用了 `_call_mcp_tool_result()`
- `query_employee_trend_lazy` 的 mcp/endpoint 分支未从业务 API 取 token，场景 2 数据链路不完整

---

## Task 1: 删除 test_build_tool_result_structure 测试

**目标：** 移除已废弃的 `build_tool_result` 函数测试，为后续删除该函数做铺垫。

**Files:**
- Modify: `packages/stargate-mcp-ui-server/tests/test_tools.py:34-41`

**Step 1: 删除测试函数**

在 `test_tools.py` 中找到并删除以下代码块：

```python
def test_build_tool_result_structure():
    from stargate_mcp_ui_server.tools import build_tool_result
    result = build_tool_result()
    assert "data" in result
    assert "token" in result
    assert result["data"][0]["year"] == 2019
    assert result["token"] == "mock-stargate-token-12345"
```

删除后 `test_tools.py` 中不再有任何对 `build_tool_result` 的引用。

**Step 2: 确认测试仍可通过**

```bash
cd packages/stargate-mcp-ui-server
uv run pytest tests/test_tools.py -v
```

预期：所有其余测试 PASS，无 `test_build_tool_result_structure` 条目。

---

## Task 2: 更新 test_query_employee_trend_returns_tool_result 测试

**目标：** 将断言改为「tool 不再携带业务数据」——即 `toolResult` 字段不存在，或存在但不含 `data`/`token`。

**Files:**
- Modify: `packages/stargate-mcp-ui-server/tests/test_main.py:27-35`

**Step 1: 将旧断言改为新断言**

找到并替换：

```python
@pytest.mark.asyncio
async def test_query_employee_trend_returns_tool_result():
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    tool = tools["query_employee_trend"]
    result = await tool.fn()
    tool_result = result.get("toolResult", {})
    assert "data" in tool_result
    assert "token" in tool_result
    assert tool_result["data"][0]["year"] == 2019
```

替换为：

```python
@pytest.mark.asyncio
async def test_query_employee_trend_has_no_business_data_in_tool_result():
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    tool = tools["query_employee_trend"]
    result = await tool.fn()
    tool_result = result.get("toolResult", {})
    assert "data" not in tool_result
    assert "token" not in tool_result
```

**Step 2: 运行新测试，确认它失败（因为实现还未改）**

```bash
cd packages/stargate-mcp-ui-server
uv run pytest tests/test_main.py::test_query_employee_trend_has_no_business_data_in_tool_result -v
```

预期：**FAIL** — `AssertionError: assert "data" not in {"data": [...], "token": ...}`

---

## Task 3: 清理 tools.py — 删除业务数据

**目标：** 从 `tools.py` 中删除 `TOKEN`、`TREND_DATA`、`build_tool_result()`。

**Files:**
- Modify: `packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/tools.py`

**Step 1: 删除三处业务数据相关代码**

在 `tools.py` 中删除以下内容（位于 `CONTAINER_NAME` 常量之后）：

```python
TOKEN = "mock-stargate-token-12345"

TREND_DATA = [
    {"year": 2019, "count": 7000},
    {"year": 2020, "count": 10000},
    {"year": 2021, "count": 16000},
    {"year": 2022, "count": 22000},
    {"year": 2023, "count": 18000},
]
```

以及整个 `build_tool_result()` 函数：

```python
def build_tool_result() -> dict:
    return {
        "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
        "data": TREND_DATA,
        "token": TOKEN,
    }
```

删除后文件中不再有 `TOKEN`、`TREND_DATA`、`build_tool_result` 任何引用。

**Step 2: 检查是否有遗漏的引用**

```bash
cd packages/stargate-mcp-ui-server
grep -r "build_tool_result\|TREND_DATA\|TOKEN" src/
```

预期：无输出（没有任何匹配）。

---

## Task 4: 清理 main.py — query_employee_trend 不再携带 toolResult 业务数据

**目标：** 修改 `main.py` 中的 `query_employee_trend` tool，移除对 `build_tool_result()` 的调用，同时更新 import。

**Files:**
- Modify: `packages/stargate-mcp-ui-server/src/stargate_mcp_ui_server/main.py`

**Step 1: 更新 import 行**

将：

```python
from stargate_mcp_ui_server.tools import get_ui_resource, build_tool_result, RESOURCE_URI, get_lazy_ui_resource, LAZY_RESOURCE_URI
```

改为：

```python
from stargate_mcp_ui_server.tools import get_ui_resource, RESOURCE_URI, get_lazy_ui_resource, LAZY_RESOURCE_URI
```

**Step 2: 移除 toolResult 字段**

将 `query_employee_trend` tool 从：

```python
@mcp.tool()
async def query_employee_trend() -> dict:
    r = get_ui_resource()
    return {
        "_meta": {"ui": {"resourceUri": RESOURCE_URI}},
        "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
        "resource": r["resource"],
        "toolName": "query_employee_trend",
        "toolResult": build_tool_result(),
    }
```

改为：

```python
@mcp.tool()
async def query_employee_trend() -> dict:
    r = get_ui_resource()
    return {
        "_meta": {"ui": {"resourceUri": RESOURCE_URI}},
        "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
        "resource": r["resource"],
        "toolName": "query_employee_trend",
    }
```

**Step 3: 运行全量测试，确认 Task 2 的测试现在通过**

```bash
cd packages/stargate-mcp-ui-server
uv run pytest tests/ -v
```

预期：所有测试 PASS，包括 `test_query_employee_trend_has_no_business_data_in_tool_result`。

---

## Task 5: stargate-agent 新增 GET /api/employee/trend 路由

**目标：** 在 `stargate-agent` 中新增独立业务 API，返回员工趋势数据（含 token），作为业务数据的唯一出口。

**Files:**
- Modify: `packages/stargate-agent/src/stargate_agent/main.py`

**背景：** 当前 `main.py` 中已有 `TREND_DATA` 常量（第 56-62 行）和 `/api/tool-result/{tool_name}` 路由（第 64-73 行），需要新增专用的 `/api/employee/trend` 路由复用此数据。

**Step 1: 在 `/api/tool-result/{tool_name}` 路由之后新增 trend 路由**

在 `main.py` 的 `@app.get("/api/employee/detail/{year}")` 路由**之前**，插入：

```python
@app.get("/api/employee/trend")
async def employee_trend():
    return {
        "data": TREND_DATA,
        "token": "mock-stargate-token-12345",
    }
```

**Step 2: 手动验证路由可访问（需要服务运行中，可跳过，仅做参考）**

```bash
curl http://localhost:3001/api/employee/trend
```

预期响应：
```json
{
  "data": [
    {"year": 2019, "count": 7000},
    ...
  ],
  "token": "mock-stargate-token-12345"
}
```

---

## Task 6: 删除 _call_mcp_tool_result()，mcp 路径改为调业务 API

**目标：** 删除 `_call_mcp_tool_result()` 函数，将 `handle_message` 中 mcp 路径的 `query_employee_trend` 和 `query_employee_trend_lazy` 两个分支均改为调用本地 `/api/employee/trend`。

**场景覆盖：**
- 场景 1/2 初始响应：`query_employee_trend` 携带 `{ data, token }`；`query_employee_trend_lazy` 只携带 `{ token }`（data 留给组件挂载后通过 tools/call 拉取）

**Files:**
- Modify: `packages/stargate-agent/src/stargate_agent/main.py`

**Step 1: 新增内部调用业务 API 的辅助函数**

在 `_fetch_component_info()` 函数附近，新增：

```python
async def _fetch_employee_trend() -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"http://localhost:{PORT}/api/employee/trend")
        return resp.json()
```

**Step 2: 删除 _call_mcp_tool_result() 函数**

找到并删除整个函数（约第 185-204 行）：

```python
async def _call_mcp_tool_result() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{os.environ.get('MCP_SERVER_URL', 'http://localhost:3005')}/tool-result/query_employee_trend"
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return {
        "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
        "data": [
            {"year": 2019, "count": 7000},
            {"year": 2020, "count": 10000},
            {"year": 2021, "count": 16000},
            {"year": 2022, "count": 22000},
            {"year": 2023, "count": 18000},
        ],
        "token": "mock-stargate-token-12345",
    }
```

同时删除顶部已无用的常量（如果存在）：
```python
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:3005")
```

**Step 3: 更新 handle_message 中 mcp 路径的 query_employee_trend 分支**

找到：

```python
if mode == "mcp":
    sse_logger.emit("SG-Agent", "MCP-Server", "mcp-tool-call", "query_employee_trend")
    mcp_result = _run_async(_call_mcp_tool_result())
    resource_uri = "ui://stargate/employee-trend"
    tool_result = mcp_result
```

替换为：

```python
if mode == "mcp":
    sse_logger.emit("SG-Agent", "BusinessAPI", "http", "GET /api/employee/trend")
    trend_resp = _run_async(_fetch_employee_trend())
    resource_uri = "ui://stargate/employee-trend"
    tool_result = {
        "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
        "data": trend_resp["data"],
        "token": trend_resp["token"],
    }
```

**Step 4: 更新 handle_message 中 mcp 路径的 query_employee_trend_lazy 分支**

当前 lazy mcp 分支只设置了 `resource_uri`，没有从业务 API 取 token。找到：

```python
if mode == "mcp":
    sse_logger.emit("SG-Agent", "MCP-Server", "mcp-tool-call", "query_employee_trend_lazy")
    resource_uri = "ui://stargate/employee-trend-lazy"
```

替换为：

```python
if mode == "mcp":
    sse_logger.emit("SG-Agent", "BusinessAPI", "http", "GET /api/employee/trend (token only)")
    trend_resp = _run_async(_fetch_employee_trend())
    resource_uri = "ui://stargate/employee-trend-lazy"
    tool_result = {
        "content": [{"type": "text", "text": "正在为您准备员工趋势数据，请稍候..."}],
        "token": trend_resp["token"],
    }
```

注意：lazy 的 `tool_result` 中**不包含 `data`**，data 由 `EmployeeChartLazy` 挂载后通过 `tools/call` 拉取（走场景 2 的第二段链路）。

**Step 5: 检查 main.py 中是否还有 _call_mcp_tool_result 或 MCP_SERVER_URL 引用**

```bash
grep -n "_call_mcp_tool_result\|MCP_SERVER_URL" packages/stargate-agent/src/stargate_agent/main.py
```

预期：无输出。

---

## Task 7: endpoint 路径改为调 /api/employee/trend

**目标：** 将 endpoint 模式下 `handle_message` 中硬编码的 `trend_data` 列表改为从 `/api/employee/trend` 动态获取；同时修正 `query_employee_trend_lazy` 的 endpoint 分支，使其 `tool_result` 只含 token 不含 data（与场景 2 设计对齐）。

**Files:**
- Modify: `packages/stargate-agent/src/stargate_agent/main.py`

**Step 1: 更新 endpoint 路径的 query_employee_trend 分支**

找到：

```python
else:
    sse_logger.emit("SG-Agent", "ResourceCenter", "http", "GET /api/components/EmployeeChart")
    component_info = _run_async(_fetch_component_info())
    trend_data = [
        {"year": 2019, "count": 7000},
        {"year": 2020, "count": 10000},
        {"year": 2021, "count": 16000},
        {"year": 2022, "count": 22000},
        {"year": 2023, "count": 18000},
    ]
    card_id = card_cache.put(
        component_name=component_info["componentName"],
        container_name=component_info.get("containerName", component_info["componentName"]),
        remote_entry_url=component_info["remoteEntryUrl"],
        props={"data": trend_data},
    )
    resource_uri = f"ui://stargate/card/{card_id}"
    tool_result = {
        "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
        "data": trend_data,
        "token": "mock-stargate-token-12345",
    }
```

替换为：

```python
else:
    sse_logger.emit("SG-Agent", "ResourceCenter", "http", "GET /api/components/EmployeeChart")
    component_info = _run_async(_fetch_component_info())
    sse_logger.emit("SG-Agent", "BusinessAPI", "http", "GET /api/employee/trend")
    trend_resp = _run_async(_fetch_employee_trend())
    card_id = card_cache.put(
        component_name=component_info["componentName"],
        container_name=component_info.get("containerName", component_info["componentName"]),
        remote_entry_url=component_info["remoteEntryUrl"],
        props={"data": trend_resp["data"]},
    )
    resource_uri = f"ui://stargate/card/{card_id}"
    tool_result = {
        "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
        "data": trend_resp["data"],
        "token": trend_resp["token"],
    }
```

**Step 2: 更新 endpoint 路径的 query_employee_trend_lazy 分支**

lazy endpoint 分支当前 `tool_result` 中没有 token。找到（位于 `query_employee_trend_lazy` 的 `else` 块之后）：

```python
tool_result = {
    "content": [{"type": "text", "text": "正在为您准备员工趋势数据，请稍候..."}],
}
```

替换为：

```python
sse_logger.emit("SG-Agent", "BusinessAPI", "http", "GET /api/employee/trend (token only)")
trend_resp = _run_async(_fetch_employee_trend())
tool_result = {
    "content": [{"type": "text", "text": "正在为您准备员工趋势数据，请稍候..."}],
    "token": trend_resp["token"],
}
```

**Step 3: 检查 main.py 中是否还有硬编码的 trend_data 列表**

```bash
grep -n "count.*7000\|count.*10000\|count.*16000" packages/stargate-agent/src/stargate_agent/main.py
```

预期：只剩 `TREND_DATA` 常量定义（第 56-62 行）和 `EMPLOYEE_DETAIL`，`handle_message` 中不再有硬编码列表。

---

## Task 8: /api/tool-result/{tool_name} 改为调 /api/employee/trend

**目标：** 将 `/api/tool-result/` 路由改为内部调用 `/api/employee/trend` 实时获取。这条路由是**场景 2 的第二段链路**——`EmployeeChartLazy` 挂载后通过 `tools/call` 触发，需要返回完整的 `{ data, token }`。

**Files:**
- Modify: `packages/stargate-agent/src/stargate_agent/main.py`

**Step 1: 更新路由实现**

找到：

```python
@app.get("/api/tool-result/{tool_name}")
async def get_tool_result(tool_name: str):
    if tool_name in ("query_employee_trend", "query_employee_trend_lazy"):
        import asyncio
        await asyncio.sleep(1.5)
        return {
            "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
            "data": TREND_DATA,
            "token": "mock-stargate-token-12345",
        }
    raise HTTPException(status_code=404, detail="Unknown tool")
```

替换为：

```python
@app.get("/api/tool-result/{tool_name}")
async def get_tool_result(tool_name: str):
    if tool_name in ("query_employee_trend", "query_employee_trend_lazy"):
        await asyncio.sleep(1.5)
        trend_resp = await _fetch_employee_trend()
        return {
            "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
            "data": trend_resp["data"],
            "token": trend_resp["token"],
        }
    raise HTTPException(status_code=404, detail="Unknown tool")
```

注意：`import asyncio` 移到文件顶部（如果还没有的话）——检查顶部 import 区域，确保 `import asyncio` 存在。

**Step 2: 确认 `asyncio` 已在顶部 import**

```bash
grep -n "^import asyncio" packages/stargate-agent/src/stargate_agent/main.py
```

如果没有输出，在文件顶部 `import` 区域添加：

```python
import asyncio
```

---

## Task 9: 清理孤立的 TREND_DATA 常量（可选但推荐）

**目标：** 如果 `TREND_DATA` 常量在 `main.py` 中只剩定义但已无处使用，将其删除，让 `GET /api/employee/trend` 作为唯一数据来源。

**Files:**
- Modify: `packages/stargate-agent/src/stargate_agent/main.py`

**Step 1: 检查 TREND_DATA 是否还被引用**

```bash
grep -n "TREND_DATA" packages/stargate-agent/src/stargate_agent/main.py
```

如果只有定义行（约第 56-62 行），没有其他引用，则删除：

```python
TREND_DATA = [
    {"year": 2019, "count": 7000},
    {"year": 2020, "count": 10000},
    {"year": 2021, "count": 16000},
    {"year": 2022, "count": 22000},
    {"year": 2023, "count": 18000},
]
```

**Step 2: 确认删除后 /api/employee/trend 路由数据来源正确**

`/api/employee/trend` 现在直接返回内联常量 `TREND_DATA`（删除前）或直接 inline 数据（删除后需同步更新路由）。

**若选择删除 TREND_DATA**，将 `/api/employee/trend` 路由改为：

```python
@app.get("/api/employee/trend")
async def employee_trend():
    return {
        "data": [
            {"year": 2019, "count": 7000},
            {"year": 2020, "count": 10000},
            {"year": 2021, "count": 16000},
            {"year": 2022, "count": 22000},
            {"year": 2023, "count": 18000},
        ],
        "token": "mock-stargate-token-12345",
    }
```

---

## Task 10: 全量回归测试

**目标：** 确认所有改动后 `stargate-mcp-ui-server` 测试全部通过，无遗漏。

**Files:**
- Test: `packages/stargate-mcp-ui-server/tests/`

**Step 1: 运行全量测试**

```bash
cd packages/stargate-mcp-ui-server
uv run pytest tests/ -v
```

预期输出（示例）：
```
tests/test_main.py::test_mcp_server_name PASSED
tests/test_main.py::test_tool_registered PASSED
tests/test_main.py::test_query_employee_trend_returns_resource_uri PASSED
tests/test_main.py::test_query_employee_trend_has_no_business_data_in_tool_result PASSED
tests/test_main.py::test_lazy_tool_registered PASSED
tests/test_main.py::test_query_employee_trend_lazy_has_no_tool_result PASSED
tests/test_tools.py::test_resource_uri_is_static PASSED
tests/test_tools.py::test_build_html_contains_container_name PASSED
tests/test_tools.py::test_build_html_contains_react_scripts PASSED
tests/test_tools.py::test_get_ui_resource_structure PASSED
tests/test_tools.py::test_build_html_does_not_contain_employee_data PASSED
tests/test_tools.py::test_lazy_resource_uri_is_static PASSED
tests/test_tools.py::test_build_lazy_html_contains_lazy_component PASSED
tests/test_tools.py::test_build_lazy_html_does_not_contain_employee_data PASSED
tests/test_tools.py::test_get_lazy_ui_resource_structure PASSED

15 passed in X.XXs
```

**Step 2: 若有测试失败，按错误信息定位到对应 Task 修复**

常见原因：
- `ImportError: cannot import name 'build_tool_result'` → Task 3/4 import 清理不彻底
- `AssertionError` in tool result 测试 → Task 4 main.py 改动未完成
