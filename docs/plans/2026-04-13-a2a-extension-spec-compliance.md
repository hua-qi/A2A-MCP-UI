# A2A 扩展规范合规改造 Implementation Plan

**Goal:** 将 `mcp_ui_resource` 从 JSON-in-text hack 改造为符合 A2A Extension 规范的标准 data part，并补齐 AgentCard 声明、Header 协商和扩展规范文档。

**Architecture:** SG-Agent 的 Flask handler 绕过 python_a2a 库的单 content 限制，直接手工构造 JSON-RPC 双 part 响应；CF-Agent 发请求时携带 `A2A-Extensions` Header，解析时改为按 part 字段类型路由；新建 `ext-mcp-ui-resource/spec.md` 作为扩展 URI 所指向的规范锚点。

**Tech Stack:** Python 3.11、python_a2a 0.5.10、Flask（A2A Server 层）、FastAPI（REST API 层）

---

### Task 1：新建扩展规范文档

**背景：** A2A 治理规范要求扩展规范托管在其 URI 对应的地址。本文件是后续所有改动的语义锚点，先建立它，其他任务才有明确的 URI 可引用。

**Files:**
- Create: `ext-mcp-ui-resource/spec.md`

---

**Step 1: 创建目录并写入规范文档**

```bash
mkdir -p /Users/lianzimeng/working/A2A-mcpUI/ext-mcp-ui-resource
```

然后创建 `ext-mcp-ui-resource/spec.md`，内容如下：

```markdown
# MCP-UI Resource Extension for A2A

**Extension URI:** `https://stargate.example.com/ext/mcp-ui-resource/v1`
**Type:** Profile Extension
**Status:** Draft
**Version:** v1

## 概述

本扩展允许 A2A Agent 在响应的 `parts[]` 中携带一个 MCP-UI 可渲染卡片资源，
客户端通过 `resourceUri` 调用 MCP `resources/read` 协议拉取卡片 HTML 并渲染。

## AgentExtension.params

本扩展在 AgentCard 中无需 `params` 配置。

## 激活方式

客户端在 HTTP 请求中携带 Header：

```
A2A-Extensions: https://stargate.example.com/ext/mcp-ui-resource/v1
```

Agent 激活后，在响应 Header 中回显：

```
A2A-Extensions: https://stargate.example.com/ext/mcp-ui-resource/v1
```

## data part schema

当扩展激活时，Agent 响应的 `parts[]` 中会包含一个 `data` part：

```json
{
  "data": {
    "kind": "mcp_ui_resource",
    "resourceUri": "ui://stargate/card/{cardInstanceId}",
    "toolName": "query_employee_trend",
    "toolResult": {
      "content": [{ "type": "text", "text": "..." }],
      "data": [...],
      "token": "..."
    },
    "uiMetadata": {
      "preferred-frame-size": { "width": 560, "height": 420 }
    }
  },
  "mediaType": "application/json",
  "metadata": {
    "extension": "https://stargate.example.com/ext/mcp-ui-resource/v1"
  }
}
```

### 字段说明

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `kind` | 是 | string | 固定值 `"mcp_ui_resource"` |
| `resourceUri` | 是 | string | MCP-UI `ui://` URI，客户端通过此 URI 调用 `resources/read` 拉取卡片 HTML |
| `toolName` | 否 | string | 对应的 MCP 工具名 |
| `toolResult` | 否 | object | 工具执行结果，作为卡片的初始渲染数据，由 `AppRenderer` 注入卡片 iframe |
| `uiMetadata.preferred-frame-size` | 否 | object | 建议渲染尺寸 `{ width: number, height: number }` |

## 降级行为

若客户端未发送 `A2A-Extensions` Header，Agent 仅返回 `text` part，不包含 `data` part。
客户端应将此情况视为正常响应，退化为纯文本展示。

## 与 MCP-UI 协议的关系

`resourceUri` 遵循 MCP-UI `ui://` URI 规范（`ui://<host>/<path>`）。
客户端拿到 `resourceUri` 后，通过标准 MCP `resources/read` 协议拉取
`mimeType: text/html;profile=mcp-app` 的 HTML 资源并交由 `AppRenderer` 渲染。

## 依赖

无其他 A2A 扩展依赖。

## Breaking Change 策略

- 新增可选字段：不需要升级 URI
- 修改已有字段语义 / 删除字段 / 新增必填字段：必须升级到 `/v2`
- Agent 不允许自动降级到旧版本
```

---

**Step 2: 验证文件已创建**

```bash
ls /Users/lianzimeng/working/A2A-mcpUI/ext-mcp-ui-resource/
```

期望输出：`spec.md`

---

### Task 2：SG-Agent — 改造 Flask A2A 响应为标准双 part 结构

**背景：**
- 文件：`packages/stargate-agent/src/stargate_agent/main.py`
- 当前的 `StargateA2AServer.handle_message()` 返回 `Message(TextContent(text=json.dumps(...))))`，把 `mcp_ui_resource` 嵌在 text 字符串里（JSON-in-text hack）。
- python_a2a 的 `A2AServer.setup_routes()` 在 Flask 里注册了 `/message` 路由，调用 `handle_message()` 后把返回值序列化为 JSON-RPC 响应。
- 改造思路：不再让 `handle_message()` 返回 `Message` 对象，改为在 `_start_a2a_flask()` 里手工注册 `/message` 路由，直接 `return jsonify(...)` 构造双 part 响应，同时在响应 Header 里回显 `A2A-Extensions`。

**Files:**
- Modify: `packages/stargate-agent/src/stargate_agent/main.py`

---

**Step 1: 在文件顶部 import 区补充 Flask 相关导入**

在 `main.py` 第 1 行的 import 块里，确认已有：

```python
from flask import Flask
```

目前该 import 在 `_start_a2a_flask()` 函数内部，需要将其提升到文件顶部（与其他 import 同级）。在文件顶部 `import` 区末尾添加：

```python
from flask import Flask, request as flask_request, jsonify as flask_jsonify
```

---

**Step 2: 新增常量**

在文件顶部常量区（`A2A_PORT = 3011` 这一行之后）新增：

```python
MCP_UI_EXTENSION_URI = "https://stargate.example.com/ext/mcp-ui-resource/v1"
```

---

**Step 3: 新增 `_build_a2a_response()` 辅助函数**

在 `StargateA2AServer` 类定义之前，新增以下函数。它把业务数据组装成符合 A2A 规范的 JSON-RPC 响应 dict：

```python
def _build_a2a_response(request_id, text: str, resource_uri: str, tool_name: str, tool_result: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "message": {
                "role": "agent",
                "messageId": str(uuid.uuid4()),
                "parts": [
                    {"text": text},
                    {
                        "data": {
                            "kind": "mcp_ui_resource",
                            "resourceUri": resource_uri,
                            "toolName": tool_name,
                            "toolResult": tool_result,
                            "uiMetadata": {
                                "preferred-frame-size": {"width": 560, "height": 420}
                            },
                        },
                        "mediaType": "application/json",
                        "metadata": {"extension": MCP_UI_EXTENSION_URI},
                    },
                ],
            }
        },
    }
```

同时在文件顶部添加 `import uuid`（如果还没有的话）。

---

**Step 4: 改造 `_start_a2a_flask()`，手工注册 `/message` 路由**

找到 `_start_a2a_flask()` 函数（当前约第 376 行），将其**整体替换**为：

```python
def _start_a2a_flask():
    flask_app = Flask(__name__)
    agent_card = AgentCard(
        name="stargate-agent",
        description="Stargate A2A Agent with MCP-UI support",
        url=f"http://localhost:{A2A_PORT}",
        version="0.1.0",
    )

    @flask_app.get("/.well-known/agent-card.json")
    def agent_card_route():
        card_dict = {
            "name": agent_card.name,
            "description": agent_card.description,
            "url": agent_card.url,
            "version": agent_card.version,
            "capabilities": {
                "streaming": False,
                "extensions": [
                    {
                        "uri": MCP_UI_EXTENSION_URI,
                        "description": "A2A 响应携带 MCP-UI 可渲染卡片资源",
                        "required": False,
                    }
                ],
            },
        }
        return flask_jsonify(card_dict)

    @flask_app.post("/message")
    def message_route():
        body = flask_request.get_json(force=True)
        request_id = body.get("id")
        activated_extensions = []

        raw_extensions_header = flask_request.headers.get("A2A-Extensions", "")
        requested_uris = [u.strip() for u in raw_extensions_header.split(",") if u.strip()]
        extension_active = MCP_UI_EXTENSION_URI in requested_uris
        if extension_active:
            activated_extensions.append(MCP_UI_EXTENSION_URI)

        params = body.get("params", {})
        message = params.get("message", {})
        parts = message.get("parts", [])
        raw_text = ""
        for p in parts:
            if "text" in p:
                raw_text = p["text"]
                break

        user_text = raw_text
        mode = "endpoint"
        try:
            parsed = json.loads(raw_text)
            user_text = parsed.get("text", raw_text)
            mode = parsed.get("mode", "endpoint")
        except (json.JSONDecodeError, TypeError):
            pass

        sse_logger.emit("SG-Agent", "SG-LLM", "llm-call", f"tool selection (mode={mode})")
        tool_name, tool_args = _run_async(llm.select_tool(user_text))

        if tool_name in ("query_employee_trend", "query_employee_trend_lazy"):
            is_lazy = tool_name == "query_employee_trend_lazy"
            text_msg = "正在为您准备员工趋势数据，请稍候..." if is_lazy else "已为您查询快手历年员工趋势数据，共 5 年记录。"

            if mode == "mcp":
                mcp_result = _run_async(_call_mcp_tool(tool_name))
                resource_uri = mcp_result.get("_meta", {}).get("ui", {}).get(
                    "resourceUri",
                    "ui://stargate/employee-trend-lazy" if is_lazy else "ui://stargate/employee-trend",
                )
                trend_resp = _run_async(_fetch_employee_trend())
                tool_result = {"content": [{"type": "text", "text": text_msg}], "token": trend_resp["token"]}
                if not is_lazy:
                    tool_result["data"] = trend_resp["data"]
            else:
                component_info = _run_async(_fetch_component_info())
                card_component = "EmployeeChartLazy" if is_lazy else component_info["componentName"]
                card_props = {} if is_lazy else {"data": _run_async(_fetch_employee_trend())["data"]}
                card_id = card_cache.put(
                    component_name=card_component,
                    container_name=component_info.get("containerName", component_info["componentName"]),
                    remote_entry_url=component_info["remoteEntryUrl"],
                    props=card_props,
                )
                resource_uri = f"ui://stargate/card/{card_id}"
                trend_resp = _run_async(_fetch_employee_trend())
                tool_result = {"content": [{"type": "text", "text": text_msg}], "token": trend_resp["token"]}
                if not is_lazy:
                    tool_result["data"] = trend_resp["data"]

            sse_logger.emit("SG-Agent", "CF-Agent", "A2A Response", f"mcp_ui_resource {resource_uri}")

            if extension_active:
                resp_body = _build_a2a_response(request_id, text_msg, resource_uri, tool_name, tool_result)
            else:
                resp_body = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "message": {
                            "role": "agent",
                            "messageId": str(uuid.uuid4()),
                            "parts": [{"text": text_msg}],
                        }
                    },
                }

            response = flask_jsonify(resp_body)
            if activated_extensions:
                response.headers["A2A-Extensions"] = ", ".join(activated_extensions)
            return response

        resp_body = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "message": {
                    "role": "agent",
                    "messageId": str(uuid.uuid4()),
                    "parts": [{"text": "抱歉，我目前只支持查询员工趋势数据。"}],
                }
            },
        }
        return flask_jsonify(resp_body)

    flask_app.run(host="0.0.0.0", port=A2A_PORT, debug=False, use_reloader=False)
```

---

**Step 5: 手工验证 SG-Agent 能正常启动**

启动 SG-Agent：

```bash
cd /Users/lianzimeng/working/A2A-mcpUI/packages/stargate-agent
.venv/bin/python -m stargate_agent.main
```

期望：无报错，控制台出现 uvicorn 监听 3001、Flask 监听 3011 的日志。

---

**Step 6: 验证不带 Header 时响应只含 text part（降级行为）**

```bash
curl -s -X POST http://localhost:3011/message \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"t1","method":"message/send","params":{"message":{"role":"user","parts":[{"text":"{\"text\":\"查询快手员工趋势\",\"mode\":\"endpoint\"}"}]}}}'
```

期望：响应 `result.message.parts` 只有一个 `{"text": "..."}` part，无 `data` part，响应 Header 无 `A2A-Extensions`。

---

**Step 7: 验证带 Header 时响应含双 part**

```bash
curl -s -X POST http://localhost:3011/message \
  -H "Content-Type: application/json" \
  -H "A2A-Extensions: https://stargate.example.com/ext/mcp-ui-resource/v1" \
  -d '{"jsonrpc":"2.0","id":"t2","method":"message/send","params":{"message":{"role":"user","parts":[{"text":"{\"text\":\"查询快手员工趋势\",\"mode\":\"endpoint\"}"}]}}}'
```

期望：
- 响应 `result.message.parts` 有两个元素：第一个有 `text` 字段，第二个有 `data.kind == "mcp_ui_resource"` 和 `data.resourceUri`
- 响应 Header 含 `A2A-Extensions: https://stargate.example.com/ext/mcp-ui-resource/v1`

---

**Step 8: 验证 AgentCard 端点**

```bash
curl -s http://localhost:3011/.well-known/agent-card.json | python3 -m json.tool
```

期望：JSON 包含 `capabilities.extensions[0].uri == "https://stargate.example.com/ext/mcp-ui-resource/v1"`。

---

### Task 3：CF-Agent — 加 Header + 改造解析逻辑

**背景：**
- 文件：`packages/codeflicker-agent/src/codeflicker_agent/main.py`
- `_call_sg_agent()` 函数（第 53-76 行）需要：① `A2AClient` 初始化时带 Header；② 解析逻辑从 `json.loads(text)` 改为读取原始 JSON-RPC 响应的 `parts[]`。
- python_a2a 的 `A2AClient.send_message()` 返回的 `response_msg` 对象是库解析过的，访问多 part 时需直接读底层原始响应。查看库源码，`A2AClient` 支持 `headers` 参数，但 `send_message` 返回的 `Message` 对象只映射单个 content。因此改为用 `httpx` 直接发请求，绕过库的反序列化，自行解析 `parts[]`。

**Files:**
- Modify: `packages/codeflicker-agent/src/codeflicker_agent/main.py`

---

**Step 1: 新增常量**

在文件顶部常量区（`PORT = ...` 之后）新增：

```python
MCP_UI_EXTENSION_URI = "https://stargate.example.com/ext/mcp-ui-resource/v1"
```

---

**Step 2: 替换 `_call_sg_agent()` 函数**

找到 `_call_sg_agent` 函数（第 53-76 行），**整体替换**为：

```python
def _call_sg_agent(user_text: str, mode: str) -> list:
    payload = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"text": json.dumps({"text": user_text, "mode": mode}, ensure_ascii=False)}],
            }
        },
    }
    import httpx as _httpx
    with _httpx.Client(timeout=30.0) as client:
        resp = client.post(
            SG_AGENT_A2A_URL + "/message",
            json=payload,
            headers={"A2A-Extensions": MCP_UI_EXTENSION_URI},
        )
    resp.raise_for_status()
    body = resp.json()

    raw_parts = body.get("result", {}).get("message", {}).get("parts", [])
    parts = []
    for p in raw_parts:
        if "text" in p:
            parts.append({"kind": "text", "text": p["text"]})
        elif "data" in p:
            d = p["data"]
            if d.get("kind") == "mcp_ui_resource":
                parts.append(d)
    if not parts:
        parts.append({"kind": "text", "text": "（无响应内容）"})
    return parts
```

> 注意：`httpx` 已在文件顶部 import（`import httpx`），`import httpx as _httpx` 只是在函数内避免与顶层 `httpx` 重名，可直接用顶层的 `httpx`。

---

**Step 3: 手工验证 CF-Agent 能正常启动**

启动 CF-Agent（确保 SG-Agent 也在运行）：

```bash
cd /Users/lianzimeng/working/A2A-mcpUI/packages/codeflicker-agent
.venv/bin/python -m codeflicker_agent.main
```

期望：无报错，uvicorn 监听 3002。

---

**Step 4: 端到端验证 `/chat` 接口**

```bash
curl -s -X POST http://localhost:3002/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"查询快手历年员工人数趋势"}'
```

期望：

```json
{
  "parts": [
    { "kind": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。" },
    {
      "kind": "mcp_ui_resource",
      "resourceUri": "ui://stargate/card/...",
      "toolName": "query_employee_trend",
      "toolResult": { "data": [...], "token": "..." },
      "uiMetadata": { "preferred-frame-size": { "width": 560, "height": 420 } }
    }
  ]
}
```

---

**Step 5: 验证降级场景（临时去掉 Header 测试）**

将 `_call_sg_agent` 中的 `headers={"A2A-Extensions": ...}` 暂时改为 `headers={}`，重启 CF-Agent，再次调用 `/chat`。

期望：`parts` 只有一个 `{kind: "text"}` 元素，前端退化为纯文本气泡。

验证完毕后还原 Header。

---

### Task 4：更新 ARCHITECTURE.md

**背景：** 第五章的示例代码仍是旧的 JSON-in-text 结构，需同步为规范双 part 格式，并新增 5.7 节。

**Files:**
- Modify: `ARCHITECTURE.md`

---

**Step 1: 更新 5.3 节响应示例**

找到 `### 5.3 SG-Agent → CF-Agent 响应（endpoint 模式）` 下的 JSON 代码块，将 `parts` 数组替换为双 part 格式：

```json
"parts": [
  { "text": "已为您查询快手历年员工趋势数据，共 5 年记录。" },
  {
    "data": {
      "kind": "mcp_ui_resource",
      "resourceUri": "ui://stargate/card/550e8400-e29b-41d4-a716-446655440000",
      "toolName": "query_employee_trend",
      "toolResult": {
        "content": [{ "type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。" }],
        "data": [
          { "year": 2019, "count": 7000 },
          { "year": 2020, "count": 10000 },
          { "year": 2021, "count": 16000 },
          { "year": 2022, "count": 22000 },
          { "year": 2023, "count": 18000 }
        ],
        "token": "mock-stargate-token-12345"
      },
      "uiMetadata": { "preferred-frame-size": { "width": 560, "height": 420 } }
    },
    "mediaType": "application/json",
    "metadata": { "extension": "https://stargate.example.com/ext/mcp-ui-resource/v1" }
  }
]
```

同时删除原来对"JSON-in-text"的描述说明段落。

---

**Step 2: 更新 5.5 节完整链路中的步骤 ②③**

步骤 ② 的 A2A 请求示例中补充 Header：

```
② CF-Agent → SG-Agent
   POST http://localhost:3011/message
   Header: A2A-Extensions: https://stargate.example.com/ext/mcp-ui-resource/v1
```

步骤 ③ 的 A2A 响应示例同步为双 part 格式（与 5.3 节一致）。

---

**Step 3: 在 5.6 节之后新增 5.7 节**

在文件末尾（`## 六、MCP-UI 与 A2A 的有机结合` 章节之前）插入：

```markdown
### 5.7 扩展规范文档与 A2A 治理规范映射

本项目将 `mcp_ui_resource` 定义为正式 A2A 扩展，规范文档位于：
`ext-mcp-ui-resource/spec.md`

| A2A 治理要求 | 本项目做法 |
|---|---|
| URI 唯一标识 | `https://stargate.example.com/ext/mcp-ui-resource/v1` |
| 规范托管在 URI | `ext-mcp-ui-resource/spec.md`（生产环境应部署到对应域名） |
| AgentCard 声明 | `capabilities.extensions[]` 中声明 uri、description、required |
| 激活协商 | 请求带 `A2A-Extensions` Header，响应回显已激活 URI |
| Breaking change 换 URI | 字段变更升级到 `/v2`，不允许原地修改 |
| `required: false` | 不支持扩展的客户端降级为纯文本，不影响基础调用 |
```

---

**Step 4: 验证文档无明显格式错误**

```bash
grep -n "5\." /Users/lianzimeng/working/A2A-mcpUI/ARCHITECTURE.md | head -20
```

期望：能看到 5.1 到 5.7 各节的标题行。

---

### 验收检查清单

完成全部 4 个 Task 后，逐项确认：

| 检查项 | 验证方式 |
|---|---|
| 扩展规范文档存在 | `ls ext-mcp-ui-resource/spec.md` |
| AgentCard 声明了 extensions | `curl http://localhost:3011/.well-known/agent-card.json` |
| 不带 Header 时响应只有 text part | curl 不带 `A2A-Extensions` Header |
| 带 Header 时响应含双 part + 响应 Header 回显 | curl 带 Header，检查 response header 和 body |
| CF-Agent `/chat` 返回正确的 mcp_ui_resource part | curl POST /chat |
| 前端完整流程可用（渲染卡片） | 启动所有服务，浏览器访问 http://localhost:3000 |
| ARCHITECTURE.md 5.3/5.5 示例已更新 | 检查文件内容 |
| ARCHITECTURE.md 新增了 5.7 节 | `grep "5.7" ARCHITECTURE.md` |
