# MCP-UI 双路径改造 - 自动验收文档

**Date:** 2026-04-13  
**适用对象：** Agent 自动化验收  
**关联设计文档：** `docs/designs/2026-04-13-mcp-ui-dual-path-redesign.md`

---

## 验收前置条件

执行所有测试前，确保以下服务全部启动：

```bash
pnpm dev
```

等待所有服务就绪：
- `http://localhost:3000` 前端
- `http://localhost:3001` SG-Agent
- `http://localhost:3002` CF-Agent
- `http://localhost:3003` resource-center-mock
- `http://localhost:3004` employee-chart-card（MF 远程组件）
- `http://localhost:3005` stargate-mcp-ui-server

---

## T1：CF-Agent mode 接口

### T1-1 默认 mode 为 endpoint

```bash
curl -s http://localhost:3002/mode
```

**期望：**
```json
{"mode": "endpoint"}
```

### T1-2 切换到 mcp mode

```bash
curl -s -X POST http://localhost:3002/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "mcp"}'
```

**期望：**
```json
{"ok": true, "mode": "mcp"}
```

### T1-3 mode 切换后持久化

```bash
curl -s http://localhost:3002/mode
```

**期望：**
```json
{"mode": "mcp"}
```

### T1-4 切换回 endpoint

```bash
curl -s -X POST http://localhost:3002/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "endpoint"}'
curl -s http://localhost:3002/mode
```

**期望：**
```json
{"mode": "endpoint"}
```

---

## T2：Endpoint 路径 - /chat

### T2-1 endpoint mode 下 /chat 返回 mcp_ui_resource

```bash
curl -s -X POST http://localhost:3002/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "endpoint"}'

curl -s -X POST http://localhost:3002/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "查询快手历年员工人数趋势"}'
```

**期望：**
```json
{
  "parts": [
    {"kind": "text", "text": "..."},
    {
      "kind": "mcp_ui_resource",
      "resourceUri": "ui://stargate/card/...",
      "toolName": "query_employee_trend",
      "toolResult": {
        "data": [
          {"year": 2019, "count": 7000},
          {"year": 2020, "count": 10000},
          {"year": 2021, "count": 16000},
          {"year": 2022, "count": 22000},
          {"year": 2023, "count": 18000}
        ],
        "token": "mock-stargate-token-12345"
      }
    }
  ]
}
```

**验证点：**
- `parts` 数组长度 >= 2
- 存在 `kind = "mcp_ui_resource"` 的 part
- `resourceUri` 以 `ui://stargate/card/` 开头
- `toolName` 为 `"query_employee_trend"`
- `toolResult.data` 长度为 5
- `toolResult.token` 非空
- `toolResult` 中数据**不**内联在 HTML 中（即 resourceUri 对应的 resource HTML 是纯 shell）

---

## T3：MCP Server 路径 - /chat

### T3-1 mcp mode 下 /chat 返回 mcp_ui_resource

```bash
curl -s -X POST http://localhost:3002/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "mcp"}'

curl -s -X POST http://localhost:3002/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "查询快手历年员工人数趋势"}'
```

**验证点：**
- `resourceUri` 为 `"ui://stargate/employee-trend"`（静态，不含动态 id）
- `toolName` 为 `"query_employee_trend"`
- `toolResult.data` 包含 5 年数据
- `toolResult.token` 非空

---

## T4：/resource-proxy - Endpoint 路径

### T4-1 endpoint 路径 resource 为纯 shell HTML

```bash
# 先通过 /chat 获取 resourceUri（含 card id）
RESOURCE_URI=$(curl -s -X POST http://localhost:3002/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "查询快手历年员工人数趋势"}' \
  | python3 -c "import sys,json; parts=json.load(sys.stdin)['parts']; r=[p for p in parts if p.get('kind')=='mcp_ui_resource'][0]; print(r['resourceUri'])")

curl -s "http://localhost:3002/resource-proxy?uri=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$RESOURCE_URI'))")"
```

**验证点：**
- 返回 `contents` 数组，长度为 1
- `contents[0].uri` 与请求的 URI 一致
- `contents[0].mimeType` 为 `"text/html;profile=mcp-app"`
- `contents[0].text` 包含 `<html` 标签
- `contents[0].text` 包含 `employeeChartCard`（MF 容器名）
- `contents[0].text` **不**包含 `"year": 2019`（数据不内联在 HTML 中）

---

## T5：/resource-proxy - MCP Server 路径

### T5-1 mcp 路径 resource 为纯 shell HTML

```bash
curl -s "http://localhost:3002/resource-proxy?uri=ui%3A%2F%2Fstargate%2Femployee-trend"
```

**验证点：**
- 返回 `contents` 数组，长度为 1
- `contents[0].uri` 为 `"ui://stargate/employee-trend"`
- `contents[0].text` 包含 `employeeChartCard`
- `contents[0].text` **不**包含 `"year": 2019`（数据不内联在 HTML 中）
- 多次调用返回内容相同（静态 resource）

---

## T6：stargate-mcp-ui-server MCP 协议验证

### T6-1 SSE 连接建立

```bash
curl -s -N --max-time 2 http://localhost:3005/sse 2>&1 | head -3
```

**期望：** 返回 `event: endpoint` 和 `data: /messages/?session_id=...`

### T6-2 tools/list 包含 query_employee_trend

通过 SSE session 发送：
```json
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
```

**期望：** `result.tools` 包含名为 `"query_employee_trend"` 的条目

### T6-3 resources/list 包含 employee-trend

```json
{"jsonrpc":"2.0","id":3,"method":"resources/list","params":{}}
```

**期望：** `result.resources[0].uri` 为 `"ui://stargate/employee-trend"`

### T6-4 tools/call 返回 toolResult 格式正确

```json
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"query_employee_trend","arguments":{}}}
```

**验证点：**
- `result.content[0].text` 可解析为 JSON
- 解析后包含 `_meta.ui.resourceUri = "ui://stargate/employee-trend"`
- 包含 `data` 数组，长度为 5
- 包含 `token` 字段
- **不**包含内联 HTML（数据与 resource 分离）

### T6-5 resources/read 返回 shell HTML

```json
{"jsonrpc":"2.0","id":5,"method":"resources/read","params":{"uri":"ui://stargate/employee-trend"}}
```

**验证点：**
- `result.contents[0].uri` 为 `"ui://stargate/employee-trend"`
- `result.contents[0].text` 含 `employeeChartCard`
- `result.contents[0].text` **不**含 `"year": 2019`

---

## T7：SG-Agent 业务接口鉴权（场景 D）

### T7-1 无 token 返回 401

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:3001/api/employee/detail/2022
```

**期望：** `401`

### T7-2 有效 token 返回详情数据

```bash
curl -s http://localhost:3001/api/employee/detail/2022 \
  -H "Authorization: Bearer mock-stargate-token-12345"
```

**期望：**
```json
{"year": 2022, "count": 22000, "note": "峰值"}
```

### T7-3 不存在的年份返回 404

```bash
curl -s -o /dev/null -w "%{http_code}" \
  http://localhost:3001/api/employee/detail/2000 \
  -H "Authorization: Bearer mock-stargate-token-12345"
```

**期望：** `404`

---

## T8：/tool-call 接口（场景 C）

### T8-1 /tool-call 返回新 toolResult

```bash
curl -s -X POST http://localhost:3002/tool-call \
  -H "Content-Type: application/json" \
  -d '{"name": "query_employee_trend", "arguments": {}}'
```

**验证点：**
- 返回包含 `data` 数组
- `data` 长度为 5，包含 2019-2023 年数据

---

## T9：前端类型结构验证

### T9-1 McpUiResourcePart 包含 toolName 字段

检查 `packages/codeflicker-frontend/src/types.ts`：

```bash
grep "toolName" packages/codeflicker-frontend/src/types.ts
```

**期望：** 文件中存在 `toolName` 字段定义

### T9-2 CardMessage 不再硬编码 toolName

```bash
grep "query_employee_trend" packages/codeflicker-frontend/src/components/CardMessage.tsx
```

**期望：** 无匹配（不存在硬编码的 tool name）

### T9-3 App.tsx 存在 mode 切换逻辑

```bash
grep "/mode" packages/codeflicker-frontend/src/App.tsx
```

**期望：** 存在调用 `/mode` 接口的代码

---

## T10：employee-chart-card 改造验证

### T10-1 不从 HTML props 读取数据

```bash
grep "TREND_DATA\|props_json" packages/employee-chart-card/src/EmployeeChart.tsx 2>/dev/null || echo "not found"
```

**期望：** 不存在内联数据相关代码（`not found` 或无匹配）

### T10-2 从 toolResult 读取数据

```bash
grep "toolResult\|tool-result\|tool_result" packages/employee-chart-card/src/EmployeeChart.tsx
```

**期望：** 存在 toolResult 相关处理代码

---

## 验收通过标准

| 测试组 | 必须全通过 |
|---|---|
| T1 mode 接口 | 是 |
| T2 Endpoint /chat | 是 |
| T3 MCP /chat | 是 |
| T4 Endpoint resource-proxy | 是 |
| T5 MCP resource-proxy | 是 |
| T6 MCP 协议 | 是 |
| T7 业务接口鉴权 | 是 |
| T8 /tool-call | 是 |
| T9 前端类型 | 是 |
| T10 employee-chart-card | 是 |
