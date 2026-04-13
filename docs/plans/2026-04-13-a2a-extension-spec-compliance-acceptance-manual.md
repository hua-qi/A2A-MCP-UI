# A2A 扩展规范合规改造 — 手动验收清单

**目标：** 由开发者逐项执行，结合浏览器、终端、代码 Review 三种方式全面确认改造效果。

**前置条件：** 按顺序启动以下服务

```bash
# 终端 1 — ResourceCenter
cd packages/resource-center-mock && pnpm start

# 终端 2 — employee-chart-card（Module Federation）
cd packages/employee-chart-card && pnpm start

# 终端 3 — MCP-Server（mcp 模式需要）
cd packages/stargate-mcp-ui-server && .venv/bin/python -m stargate_mcp_ui_server.main

# 终端 4 — SG-Agent
cd packages/stargate-agent && .venv/bin/python -m stargate_agent.main

# 终端 5 — CF-Agent
cd packages/codeflicker-agent && .venv/bin/python -m codeflicker_agent.main

# 终端 6 — CF-Frontend
cd packages/codeflicker-frontend && pnpm dev
```

---

## 一、文件检查（代码 Review）

### 1.1 扩展规范文档

- [ ] `ext-mcp-ui-resource/spec.md` 文件存在
- [ ] 包含 Extension URI：`https://stargate.example.com/ext/mcp-ui-resource/v1`
- [ ] 包含 data part schema 表格（kind / resourceUri / toolName / toolResult / uiMetadata）
- [ ] 包含激活方式说明（`A2A-Extensions` Header）
- [ ] 包含降级行为说明（不带 Header 只返回 text part）
- [ ] 包含 Breaking Change 策略（字段变更升级 /v2）

### 1.2 SG-Agent 代码

打开 `packages/stargate-agent/src/stargate_agent/main.py`：

- [ ] 文件顶部有 `from flask import Flask, request as flask_request, jsonify as flask_jsonify`
- [ ] 定义了常量 `MCP_UI_EXTENSION_URI = "https://stargate.example.com/ext/mcp-ui-resource/v1"`
- [ ] 存在 `_build_a2a_response()` 函数，返回包含双 part 的 dict
- [ ] `_start_a2a_flask()` 内手工注册了 `/.well-known/agent-card.json` 和 `/message` 两个路由
- [ ] `/message` 路由读取 `A2A-Extensions` 请求 Header
- [ ] 扩展激活时调用 `_build_a2a_response()`，不激活时只返回 text part
- [ ] 响应通过 `response.headers["A2A-Extensions"]` 回显已激活 URI
- [ ] **不存在** `TextContent(text=json.dumps({..., "mcp_ui_resource": ...}))` 这样的 JSON-in-text 写法

### 1.3 CF-Agent 代码

打开 `packages/codeflicker-agent/src/codeflicker_agent/main.py`：

- [ ] 定义了常量 `MCP_UI_EXTENSION_URI = "https://stargate.example.com/ext/mcp-ui-resource/v1"`
- [ ] `_call_sg_agent()` 使用 `httpx` 直接发 POST 请求（不再用 `A2AClient`）
- [ ] 请求 `headers` 中包含 `A2A-Extensions: ...` Header
- [ ] 解析逻辑遍历 `parts[]`，通过 `"text" in p` / `"data" in p` 路由，而非 `json.loads(text)`
- [ ] 存在 `if not parts: parts.append({"kind": "text", "text": "（无响应内容）"})` 兜底

### 1.4 ARCHITECTURE.md

打开 `ARCHITECTURE.md`：

- [ ] 5.3 节的响应 JSON 示例中 `parts` 数组包含双 part（一个 `text`，一个 `data`）
- [ ] `data` part 有 `mediaType: "application/json"` 和 `metadata.extension`
- [ ] 5.5 节步骤 ② 的 A2A 请求示例中有 `A2A-Extensions` Header
- [ ] 5.5 节步骤 ③ 的响应示例是双 part 格式
- [ ] 存在 `### 5.7` 节，包含治理规范映射表
- [ ] **不存在** `JSON-in-text hack` 字样或旧格式的嵌套 JSON 示例

---

## 二、接口测试（终端）

### 2.1 AgentCard 端点

```bash
curl -s http://localhost:3011/.well-known/agent-card.json | python3 -m json.tool
```

预期：输出 JSON 中 `capabilities.extensions` 数组包含：
```json
{
  "uri": "https://stargate.example.com/ext/mcp-ui-resource/v1",
  "description": "A2A 响应携带 MCP-UI 可渲染卡片资源",
  "required": false
}
```

- [ ] extensions 数组存在且非空
- [ ] uri 值正确
- [ ] required 为 false

---

### 2.2 不带 Header 的降级响应

```bash
curl -si -X POST http://localhost:3011/message \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"manual-01","method":"message/send","params":{"message":{"role":"user","parts":[{"text":"{\"text\":\"查询快手员工趋势\",\"mode\":\"endpoint\"}"}]}}}'
```

预期：
- [ ] 响应 HTTP Header **没有** `A2A-Extensions` 行
- [ ] 响应 body 的 `result.message.parts` **只有一个** `{"text": "..."}` 元素
- [ ] parts 中**没有** `data` 字段

---

### 2.3 带 Header 的双 part 响应（endpoint 模式）

```bash
curl -si -X POST http://localhost:3011/message \
  -H "Content-Type: application/json" \
  -H "A2A-Extensions: https://stargate.example.com/ext/mcp-ui-resource/v1" \
  -d '{"jsonrpc":"2.0","id":"manual-02","method":"message/send","params":{"message":{"role":"user","parts":[{"text":"{\"text\":\"查询快手员工趋势\",\"mode\":\"endpoint\"}"}]}}}'
```

预期 Header：
- [ ] 响应 Header 包含 `A2A-Extensions: https://stargate.example.com/ext/mcp-ui-resource/v1`

预期 Body：
- [ ] `parts` 有 2 个元素
- [ ] 第 1 个元素：`{"text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}`
- [ ] 第 2 个元素：`data.kind == "mcp_ui_resource"`
- [ ] 第 2 个元素：`data.resourceUri` 以 `ui://stargate/card/` 开头（endpoint 模式用 cardInstanceId）
- [ ] 第 2 个元素：`data.toolResult.data` 是包含 5 条年份数据的数组
- [ ] 第 2 个元素：`mediaType == "application/json"`
- [ ] 第 2 个元素：`metadata.extension == "https://stargate.example.com/ext/mcp-ui-resource/v1"`

---

### 2.4 带 Header 的双 part 响应（mcp 模式）

```bash
curl -si -X POST http://localhost:3011/message \
  -H "Content-Type: application/json" \
  -H "A2A-Extensions: https://stargate.example.com/ext/mcp-ui-resource/v1" \
  -d '{"jsonrpc":"2.0","id":"manual-03","method":"message/send","params":{"message":{"role":"user","parts":[{"text":"{\"text\":\"查询快手员工趋势\",\"mode\":\"mcp\"}"}]}}}'
```

预期：
- [ ] 同 2.3，但 `data.resourceUri` 为 `ui://stargate/employee-trend`（固定路径，非 cardInstanceId）

---

### 2.5 CF-Agent /chat 端到端

```bash
curl -s -X POST http://localhost:3002/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"查询快手历年员工人数趋势"}' | python3 -m json.tool
```

预期：
- [ ] `parts` 数组有 2 个元素
- [ ] 第 1 个：`kind == "text"`，text 是可读的中文描述
- [ ] 第 2 个：`kind == "mcp_ui_resource"`
- [ ] 第 2 个：`resourceUri` 以 `ui://` 开头
- [ ] 第 2 个：`toolResult.data` 包含员工趋势数据数组
- [ ] 第 2 个：**不存在** `text` 字段（确认不是 JSON-in-text）

---

### 2.6 CF-Agent /chat 降级验证（知道原理即可，不需要改代码）

> 说明：CF-Agent 发给 SG-Agent 的请求携带了 `A2A-Extensions` Header，如果 SG-Agent 返回的响应中没有 `data` part（例如 SG-Agent 未升级），CF-Agent 应该只返回 text part。这个场景在当前代码中通过 `if not parts` 兜底覆盖。

阅读 `_call_sg_agent()` 代码，确认：
- [ ] `for p in raw_parts` 循环中，没有 `data` 的 part 会被忽略（不会报错）
- [ ] `if not parts:` 兜底能正确处理全空情况

---

## 三、浏览器端到端验收

打开 `http://localhost:3000`。

### 3.1 基础对话渲染

1. 在输入框输入：`查询快手历年员工人数趋势`，点击发送
2. 等待响应（约 2-3 秒）

- [ ] 对话框出现一条文字气泡（Agent 文本描述）
- [ ] 文字气泡下方出现一个图表卡片（iframe 区域）
- [ ] 图表卡片展示折线图，X 轴为年份（2019-2023），Y 轴为人数

### 3.2 卡片交互

- [ ] 点击卡片内"刷新数据"按钮：图表短暂 loading 后重新渲染（数据不变，验证 `tools/call` 链路）
- [ ] 点击卡片内"分析趋势"按钮：对话框新增一轮 Agent 回复（验证 `ui/message` 链路）
- [ ] 点击卡片内年份详情按钮（如"2022 详情"）：卡片内出现该年份的详细信息（验证直接调用 Stargate API 链路）

### 3.3 时序图验证

页面底部时序图应显示完整调用链：

- [ ] `Frontend → CF-Agent: chat`
- [ ] `CF-Agent → CF-LLM: llm-call`
- [ ] `CF-Agent → SG-Agent: A2A Task`
- [ ] `SG-Agent → SG-LLM: llm-call`
- [ ] `SG-Agent → ResourceCenter: http`（endpoint 模式）或 `SG-Agent → MCP-Server: mcp-tool-call`（mcp 模式）
- [ ] `SG-Agent → BusinessAPI: http`
- [ ] `SG-Agent → CF-Agent: A2A Response`（detail 中包含 `mcp_ui_resource`）

### 3.4 MCP 模式切换

点击页面右上角 "MCP Server" 按钮切换模式，重新发送相同消息：

- [ ] 卡片正常渲染（功能与 endpoint 模式一致）
- [ ] 时序图出现 `SG-Agent → MCP-Server` 节点

---

## 四、验收结论

| 类别 | 检查项数 | 通过 | 失败 |
|---|---|---|---|
| 文件检查 | 21 | | |
| 接口测试 | 22 | | |
| 浏览器验收 | 12 | | |
| **合计** | **55** | | |

> 所有 55 项通过，本次改造验收完成。有任何失败项，对照 `docs/plans/2026-04-13-a2a-extension-spec-compliance.md` 中对应 Task 的步骤排查。
