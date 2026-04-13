# 补充完整 Demo Implementation Plan

**Goal:** 打通 mode=mcp 的完整链路（SG-Agent 通过 MCP SSE Client 委托 stargate-mcp-ui-server 执行 tool 和读取 resource），并修复 EmployeeChartLazy 的 size notification 缺陷。

**Architecture:**
- `stargate-mcp-ui-server`（:3005）职责：提供 HTML Shell，tool 返回 resourceUri，resource 返回 HTML
- `stargate-agent` 职责：mode=mcp 时用 MCP SSE Client 调用 MCP Server；业务数据（data/token）仍从 `/api/employee/trend` 取
- resource 读取路径：`CF-Agent /resource-proxy → SG-Agent /mcp/resources/read → MCP Server`

**Tech Stack:** Python 3.11+, FastAPI, mcp[server]>=1.5.0（含 client SDK）, pytest

---

## 背景知识

**当前 mode=mcp 的问题：**
- `handle_message` 的 mcp 分支只换了 `resource_uri`，并没有调用 MCP Server
- `/mcp/resources/read` 对 `ui://stargate/employee-trend` 直接生成 HTML，没有委托 MCP Server
- `stargate-mcp-ui-server` 实际上从未被调用

**目标 mode=mcp 链路：**
```
SG-Agent.handle_message (mode=mcp)
  → _call_mcp_tool("query_employee_trend")   [MCP SSE Client → :3005]
      ← { _meta.ui.resourceUri: "ui://stargate/employee-trend", resource: ... }
  → _fetch_employee_trend()                  [HTTP → /api/employee/trend]
  → 组装 A2A 响应，resourceUri 来自 MCP Server

CF-Agent /resource-proxy?uri=ui://stargate/employee-trend
  → SG-Agent /mcp/resources/read
      → _read_mcp_resource(uri)              [MCP SSE Client → :3005]
          ← HTML Shell
```

**MCP SSE Client 用法（mcp SDK）：**
```python
from mcp.client.sse import sse_client
from mcp import ClientSession

async def _call_mcp_tool(tool_name: str) -> dict:
    async with sse_client("http://localhost:3005/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, {})
            return json.loads(result.content[0].text)

async def _read_mcp_resource(uri: str) -> list:
    async with sse_client("http://localhost:3005/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.read_resource(uri)
            return [
                {"uri": c.uri, "mimeType": getattr(c, "mimeType", "text/html"), "text": c.text}
                for c in result.contents
            ]
```

**运行测试命令：**
```bash
cd packages/stargate-mcp-ui-server
uv run pytest tests/ -v
```

---

## Task 1: 新增 _call_mcp_tool() 和 _read_mcp_resource() 辅助函数

**目标：** 在 `stargate-agent/main.py` 中新增两个通过 MCP SSE Client 调用 MCP Server 的辅助函数。

**Files:**
- Modify: `packages/stargate-agent/src/stargate_agent/main.py`

**Step 1: 检查 mcp client 相关 import**

在文件顶部，确认已有或新增以下 import：

```python
from mcp.client.sse import sse_client
from mcp import ClientSession
```

**Step 2: 在 _fetch_component_info() 附近新增两个函数**

在 `_fetch_component_info()` 函数之后插入：

```python
MCP_SERVER_SSE_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:3005") + "/sse"

async def _call_mcp_tool(tool_name: str) -> dict:
    async with sse_client(MCP_SERVER_SSE_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, {})
            if result.content and hasattr(result.content[0], "text"):
                return json.loads(result.content[0].text)
            return {}

async def _read_mcp_resource(uri: str) -> list:
    async with sse_client(MCP_SERVER_SSE_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.read_resource(uri)
            return [
                {
                    "uri": c.uri,
                    "mimeType": getattr(c, "mimeType", "text/html;profile=mcp-app"),
                    "text": c.text,
                }
                for c in result.contents
            ]
```

**Step 3: 手动验证 import 不报错**

```bash
cd packages/stargate-agent
uv run python -c "from mcp.client.sse import sse_client; from mcp import ClientSession; print('OK')"
```

预期：输出 `OK`，无 ImportError。

---

## Task 2: 更新 handle_message 的 mcp 分支，改为委托 MCP Server

**目标：** mode=mcp 时，`query_employee_trend` 和 `query_employee_trend_lazy` 两个分支均改为通过 `_call_mcp_tool()` 委托 MCP Server，resource_uri 来自 MCP Server 的返回值。

**Files:**
- Modify: `packages/stargate-agent/src/stargate_agent/main.py`

**Step 1: 更新 query_employee_trend 的 mcp 分支**

找到：

```python
        if tool_name == "query_employee_trend":
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

替换为：

```python
        if tool_name == "query_employee_trend":
            if mode == "mcp":
                sse_logger.emit("SG-Agent", "MCP-Server", "mcp-tool-call", "query_employee_trend")
                mcp_result = _run_async(_call_mcp_tool("query_employee_trend"))
                resource_uri = mcp_result.get("_meta", {}).get("ui", {}).get("resourceUri", "ui://stargate/employee-trend")
                sse_logger.emit("SG-Agent", "BusinessAPI", "http", "GET /api/employee/trend")
                trend_resp = _run_async(_fetch_employee_trend())
                tool_result = {
                    "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
                    "data": trend_resp["data"],
                    "token": trend_resp["token"],
                }
```

**Step 2: 更新 query_employee_trend_lazy 的 mcp 分支**

找到：

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

替换为：

```python
            if mode == "mcp":
                sse_logger.emit("SG-Agent", "MCP-Server", "mcp-tool-call", "query_employee_trend_lazy")
                mcp_result = _run_async(_call_mcp_tool("query_employee_trend_lazy"))
                resource_uri = mcp_result.get("_meta", {}).get("ui", {}).get("resourceUri", "ui://stargate/employee-trend-lazy")
                sse_logger.emit("SG-Agent", "BusinessAPI", "http", "GET /api/employee/trend (token only)")
                trend_resp = _run_async(_fetch_employee_trend())
                tool_result = {
                    "content": [{"type": "text", "text": "正在为您准备员工趋势数据，请稍候..."}],
                    "token": trend_resp["token"],
                }
```

---

## Task 3: 更新 /mcp/resources/read，将 employee-trend URI 转发给 MCP Server

**目标：** `/mcp/resources/read` 对 `ui://stargate/employee-trend` 和 `ui://stargate/employee-trend-lazy` 的处理，改为通过 `_read_mcp_resource()` 从 MCP Server 读取，不再本地生成 HTML Shell。

**Files:**
- Modify: `packages/stargate-agent/src/stargate_agent/main.py`

**Step 1: 找到 mcp_resources_read 中处理两个 employee-trend URI 的代码块**

当前代码（约第 96-120 行）：

```python
    if uri == "ui://stargate/employee-trend":
        html = build_employee_trend_shell()
        resource = create_ui_resource({...})
        r = resource.model_dump(mode="json")
        return JSONResponse({"contents": [...]})

    if uri == "ui://stargate/employee-trend-lazy":
        html = build_employee_trend_shell("EmployeeChartLazy")
        ...
```

**Step 2: 将这两个 if 块替换为转发逻辑**

```python
    if uri in ("ui://stargate/employee-trend", "ui://stargate/employee-trend-lazy"):
        sse_logger.emit("SG-Agent", "MCP-Server", "mcp-resources/read", uri)
        contents = _run_async(_read_mcp_resource(uri))
        return JSONResponse({"contents": contents})
```

注意：`_run_async` 在这里是 FastAPI 的 async 路由，可以直接 `await`，改为：

```python
    if uri in ("ui://stargate/employee-trend", "ui://stargate/employee-trend-lazy"):
        sse_logger.emit("SG-Agent", "MCP-Server", "mcp-resources/read", uri)
        contents = await _read_mcp_resource(uri)
        return JSONResponse({"contents": contents})
```

**Step 3: 确认 build_employee_trend_shell import 是否仍被其他地方使用**

```bash
grep -n "build_employee_trend_shell" packages/stargate-agent/src/stargate_agent/main.py
```

如果只剩 `ui://stargate/card/` 分支用到（生成 inline HTML），则 `build_employee_trend_shell` 的 import 保留；如果已无引用，删除该 import 行。

---

## Task 4: 修复 EmployeeChartLazy 的 size notification

**目标：** 图表渲染完成后调用 `notifySize()`，使 iframe 高度自动适配。

**Files:**
- Modify: `packages/employee-chart-card/src/EmployeeChartLazy.tsx`

**Step 1: 在图表渲染的 useEffect 中添加 finished 事件监听**

找到：

```typescript
  useEffect(() => {
    if (!chartRef.current || data.length === 0) return;
    const chart = echarts.init(chartRef.current);
    chart.setOption({
      title: { text: '快手员工趋势（懒加载）' },
      xAxis: { type: 'category', data: data.map((d) => String(d.year)) },
      yAxis: { type: 'value' },
      series: [{ type: 'line', data: data.map((d) => d.count), smooth: true }],
    });
    return () => chart.dispose();
  }, [data]);
```

替换为：

```typescript
  useEffect(() => {
    if (!chartRef.current || data.length === 0) return;
    const chart = echarts.init(chartRef.current);
    chart.setOption({
      title: { text: '快手员工趋势（懒加载）' },
      xAxis: { type: 'category', data: data.map((d) => String(d.year)) },
      yAxis: { type: 'value' },
      series: [{ type: 'line', data: data.map((d) => d.count), smooth: true }],
    });
    chart.on('finished', () => notifySize(containerRef.current));
    return () => chart.dispose();
  }, [data]);
```

---

## Task 5: 全量回归测试

**目标：** 确认 stargate-mcp-ui-server 测试全部通过，MCP Server 仍可正常启动。

**Step 1: 运行 MCP Server 测试**

```bash
cd packages/stargate-mcp-ui-server
uv run pytest tests/ -v
```

预期：15 passed。

**Step 2: 验证 SG-Agent import 无误**

```bash
cd packages/stargate-agent
uv run python -c "from stargate_agent.main import app; print('import OK')"
```

预期：输出 `import OK`，无报错。

**Step 3: 端到端冒烟（服务均启动时）**

切换前端到 mcp 模式，发送「查询快手员工趋势」：
- Log 中应出现 `SG-Agent → MCP-Server mcp-tool-call: query_employee_trend`
- 之后出现 `SG-Agent → MCP-Server mcp-resources/read: ui://stargate/employee-trend`
- 图表正常渲染
