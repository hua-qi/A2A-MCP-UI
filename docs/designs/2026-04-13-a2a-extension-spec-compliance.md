# A2A 扩展规范合规改造

**Date:** 2026-04-13

## Context

当前项目中，SG-Agent 通过 A2A 协议向 CF-Agent 返回 MCP-UI 卡片资源时，采用了一种非标准的"JSON-in-text"hack：将 `mcp_ui_resource` 和文本消息序列化为同一个 JSON 字符串，塞进 `TextContent.text` 字段返回。这绕过了 A2A 协议对 Part 结构的规范定义，也没有在 AgentCard 中声明该扩展，不符合 A2A Extension 治理规范。

本次优化的动机是：将 `mcp_ui_resource` 作为正式的 A2A 扩展落地，消除 hack，为未来对接其他 Agent 打好基础。

## Discussion

**目标确认**：规范合规（而非单纯消除 hack 或提升可读性）。

**改动范围选择**：探讨了三种方案：
- **方案 A（最小改动）**：用 `metadata` 字段携带扩展数据，仅加 AgentCard 声明。缺点是 `metadata` 语义上是附加信息，不是 A2A 推荐的 data part 方式。
- **方案 B（标准 data part）**：绕过 python_a2a 库的单 content 限制，在 Flask 路由层手工构造 JSON-RPC 多 part 响应。完全符合规范，但需要同时改造 SG-Agent 和 CF-Agent。
- **方案 C（完整改造 + 规范文档）**：在方案 B 基础上，新建扩展规范文档 `ext-mcp-ui-resource/spec.md`，URI 指向该文档，符合 A2A 治理要求中"规范托管在 URI"的规定。

最终选择**方案 C**，一次性完成技术债清理和规范闭环。

**关键约束**：
- python_a2a 0.5.10 的 `Message` 对象内部为单 content，多 part 支持仅在序列化层。因此需在 Flask handler 层手工构造 JSON-RPC 响应，不依赖库的对象模型。
- `required: false`：不支持扩展的客户端仍可调用 SG-Agent，降级为纯文本响应。

## Approach

将 `mcp_ui_resource` 定义为正式 A2A Profile Extension，通过以下四步完整落地：

1. **新建扩展规范文档**（`ext-mcp-ui-resource/spec.md`），作为扩展 URI 所托管的内容锚点。
2. **SG-Agent 改造**：AgentCard 声明 `extensions[]`，`handle_message()` 改为在 Flask 层手工构造符合 A2A 规范的双 part JSON-RPC 响应。
3. **CF-Agent 改造**：`A2AClient` 初始化时携带 `A2A-Extensions` Header，响应解析改为按 part 字段类型路由，并增加无扩展时的降级处理。
4. **文档更新**：`ARCHITECTURE.md` 第五章示例同步为规范结构，新增 5.7 节说明扩展与 A2A 治理规范的映射关系。

**实施顺序**：`spec.md` → SG-Agent 响应结构 → CF-Agent Header + 解析 → AgentCard 声明 → ARCHITECTURE.md。

## Architecture

### 扩展规范文档（`ext-mcp-ui-resource/spec.md`）

核心内容：
- **Extension URI**：`https://stargate.example.com/ext/mcp-ui-resource/v1`
- **类型**：Profile Extension
- **data part schema**：

  | 字段 | 必填 | 说明 |
  |---|---|---|
  | `kind` | 是 | 固定值 `"mcp_ui_resource"` |
  | `resourceUri` | 是 | MCP-UI `ui://` URI |
  | `toolName` | 否 | 对应 MCP 工具名 |
  | `toolResult` | 否 | 工具执行结果，作为卡片初始渲染数据 |
  | `uiMetadata.preferred-frame-size` | 否 | 建议渲染尺寸 `{width, height}` |

- **激活方式**：请求 Header `A2A-Extensions: https://stargate.example.com/ext/mcp-ui-resource/v1`
- **Breaking change 策略**：字段变更升级到 `/v2`，不允许原地修改

---

### SG-Agent 响应结构

**AgentCard 新增声明：**

```python
AgentCard(
    name="stargate-agent",
    extensions=[{
        "uri": "https://stargate.example.com/ext/mcp-ui-resource/v1",
        "description": "A2A 响应携带 MCP-UI 可渲染卡片资源",
        "required": False,
    }]
)
```

**Wire 上的目标响应格式（双 part）：**

```json
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "result": {
    "message": {
      "role": "agent",
      "messageId": "msg-002",
      "parts": [
        { "text": "已为您查询快手历年员工趋势数据，共 5 年记录。" },
        {
          "data": {
            "kind": "mcp_ui_resource",
            "resourceUri": "ui://stargate/card/550e8400-...",
            "toolName": "query_employee_trend",
            "toolResult": { "data": [...], "token": "..." },
            "uiMetadata": { "preferred-frame-size": { "width": 560, "height": 420 } }
          },
          "mediaType": "application/json",
          "metadata": {
            "extension": "https://stargate.example.com/ext/mcp-ui-resource/v1"
          }
        }
      ]
    }
  }
}
```

实现方式：在 Flask handler 层直接 `return jsonify(...)` 手工构造，绕过 python_a2a `Message` 对象的单 content 限制。

---

### CF-Agent 解析改造

**请求侧**：`A2AClient` 初始化时注入 Header：

```python
A2AClient(
    endpoint_url=SG_AGENT_A2A_URL,
    headers={"A2A-Extensions": "https://stargate.example.com/ext/mcp-ui-resource/v1"}
)
```

**响应侧**：解析逻辑从 `json.loads(text)` 暴力提取，改为遍历 `parts[]` 按字段类型路由：

```
parts[] 遍历：
  有 "text" 字段  → { kind: "text", text: ... }
  有 "data" 字段  → 检查 data.kind
      == "mcp_ui_resource"  → 透传为 mcp_ui_resource part
      其他                  → 忽略
```

**降级处理**：响应 Header 中无 `A2A-Extensions`，或 parts 中无 `data` part 时，只返回文本 part，前端退化为纯文本气泡，保证 `required: false` 的语义真正落地。

---

### ARCHITECTURE.md 更新范围

- **5.3 节**：响应示例替换为规范双 part 结构
- **5.5 节**：完整链路举例中步骤 ② 补充 Header，步骤 ③ 响应示例同步
- **新增 5.7 节**：A2A 治理规范映射表

  | A2A 治理要求 | 本项目做法 |
  |---|---|
  | URI 唯一标识 | `https://stargate.example.com/ext/mcp-ui-resource/v1` |
  | 规范托管在 URI | `ext-mcp-ui-resource/spec.md`（生产环境部署到对应域名） |
  | AgentCard 声明 | `capabilities.extensions[]` |
  | 激活协商 | `A2A-Extensions` Header 请求/响应 |
  | Breaking change 换 URI | 字段变更升级到 `/v2` |
  | `required: false` | 不支持扩展的客户端降级为纯文本 |
