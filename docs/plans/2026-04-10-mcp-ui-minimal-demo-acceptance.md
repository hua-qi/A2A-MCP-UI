# MCP-UI 最小验证 Demo 验收文档

**验收目标：** 确认端到端链路"用户输入 → CF-Agent → A2A → SG-Agent → MCP-UI → 模块联邦卡片渲染"完整跑通，所有服务行为符合设计预期。

**前提条件：** 已按实施计划完成全部 Task 1–7，所有服务正在运行。

---

## 验收前检查清单

在开始验收前，逐项确认：

- [ ] `http://localhost:3003/health` 返回 `{"ok":true}`
- [ ] `http://localhost:3004/remoteEntry.js` 返回 200
- [ ] `http://localhost:3001/health` 返回 `{"ok":true}`
- [ ] `http://localhost:3002/health` 返回 `{"ok":true}`
- [ ] `http://localhost:3000` 可以在浏览器正常打开，显示聊天界面

全部通过后再执行下方验收用例。

---

## AC-01：资源中心接口

**验收命令：**

```bash
curl http://localhost:3003/api/components/EmployeeChart
```

**通过标准：**

```json
{
  "componentName": "EmployeeChart",
  "remoteEntryUrl": "http://localhost:3004/remoteEntry.js"
}
```

字段完全匹配，HTTP 状态码 200。

---

## AC-02：SG-Agent token 换取

**验收命令：**

```bash
curl -X POST http://localhost:3001/api/token/exchange
```

**通过标准：**

响应包含 `token` 字段，值为非空字符串：

```json
{"token": "mock-stargate-token-12345"}
```

---

## AC-03：SG-Agent 员工详情接口（鉴权验证）

**3a - 携带 token，应成功：**

```bash
curl -H "Authorization: Bearer mock-stargate-token-12345" \
  http://localhost:3001/api/employee/detail/2022
```

通过标准：

```json
{"year": 2022, "count": 22000, "note": "峰值"}
```

**3b - 不携带 token，应拒绝：**

```bash
curl http://localhost:3001/api/employee/detail/2022
```

通过标准：HTTP 状态码 `401`。

---

## AC-04：CF-Agent 意图识别（非数据查询）

**验收命令：**

```bash
curl -X POST http://localhost:3002/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"你好"}'
```

**通过标准：**

- HTTP 200
- `parts` 数组中含一个 `kind: "text"` 的元素
- 不含任何 `kind: "mcp_ui_resource"` 元素

---

## AC-05：CF-Agent 意图识别（数据查询）+ A2A 调用链路

**验收命令：**

```bash
curl -X POST http://localhost:3002/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"帮我查一下快手历年员工人数趋势"}'
```

**通过标准：**

HTTP 200，响应体结构如下（`cardInstanceId` 为动态 UUID）：

```json
{
  "parts": [
    {
      "kind": "text",
      "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"
    },
    {
      "kind": "mcp_ui_resource",
      "resourceUri": "ui://stargate/card/<uuid>",
      "uiMetadata": {
        "preferred-frame-size": {"width": 560, "height": 420}
      }
    }
  ]
}
```

逐项检查：

- [ ] `parts` 包含恰好 2 个元素
- [ ] 第一个元素 `kind === "text"`，`text` 非空
- [ ] 第二个元素 `kind === "mcp_ui_resource"`
- [ ] `resourceUri` 格式为 `ui://stargate/card/<uuid>`

---

## AC-06：resource-proxy + MCP resources/read 链路

取 AC-05 响应中的 `resourceUri`，替换下方 `<uri>`：

**验收命令：**

```bash
URI="ui://stargate/card/<从AC-05拿到的uuid>"
curl "http://localhost:3002/resource-proxy?uri=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$URI")"
```

**通过标准：**

```json
{
  "componentName": "EmployeeChart",
  "remoteEntryUrl": "http://localhost:3004/remoteEntry.js",
  "props": {
    "data": [
      {"year": 2019, "count": 7000},
      {"year": 2020, "count": 10000},
      {"year": 2021, "count": 16000},
      {"year": 2022, "count": 22000},
      {"year": 2023, "count": 18000}
    ]
  }
}
```

逐项检查：

- [ ] `componentName === "EmployeeChart"`
- [ ] `remoteEntryUrl` 指向 3004 端口
- [ ] `props.data` 包含 5 条年份记录

---

## AC-07：前端完整渲染链路（浏览器手动验证）

打开浏览器，访问 `http://localhost:3000`。

**步骤 1：发送数据查询消息**

在输入框输入以下内容并回车或点击发送：

```
帮我查一下快手历年员工人数趋势
```

**通过标准（按发生顺序）：**

- [ ] 用户消息气泡出现在对话区右侧
- [ ] 输入框进入禁用状态，界面显示"思考中..."
- [ ] 右侧 EventLog 依次出现以下条目（顺序和内容大致匹配即可）：
  - `Frontend → CF-Agent: chat`
  - `CF-Agent → LLM: llm-call: intent detection`
  - `CF-Agent → SG-Agent: A2A Task`
  - `SG-Agent → LLM: llm-call: tool selection`
  - `SG-Agent → ResourceCenter: http`
  - `SG-Agent → CF-Agent: A2A Response: mcp_ui_resource`
  - `Frontend → CF-Agent: resource-proxy`
  - `CF-Agent → SG-Agent: MCP resources/read`
- [ ] 对话区出现 Agent 文本气泡，内容包含"快手"和"员工"
- [ ] 文本气泡下方出现卡片加载区域，短暂显示"加载卡片中..."
- [ ] 卡片渲染完成，显示折线图，标题为"快手员工趋势"
- [ ] 折线图 X 轴包含 2019–2023 共 5 个年份节点
- [ ] 卡片下方显示"分析趋势"按钮和各年份"详情"按钮

---

## AC-08：卡片交互路径 A（直调 SG-Agent API）

在 AC-07 渲染出的卡片中：

**步骤：** 点击"2022 详情"按钮

**通过标准：**

- [ ] 页面弹出 `alert`
- [ ] alert 内容包含 `"year": 2022`、`"count": 22000`、`"note": "峰值"`

---

## AC-09：卡片交互路径 B（postMessage 触发 Agent）

在 AC-07 渲染出的卡片中：

**步骤：** 点击"分析趋势"按钮

**通过标准：**

- [ ] 输入框自动填入包含"分析"或员工数据的文本
- [ ] 或者触发新一轮对话，对话区出现新的 Agent 回复

> 若路径 B 未在实施计划中完整实现（App.tsx 的 postMessage 监听），此条可标记为"待实现"，不阻塞其他验收项。

---

## AC-10：卡片实例缓存过期（非功能性验证）

**验收命令：**

```bash
curl "http://localhost:3001/api/card-instance/00000000-0000-0000-0000-000000000000"
```

**通过标准：** HTTP 状态码 `404`，响应体包含 `"detail"` 字段。

---

## AC-11：SSE 事件流可订阅

**验收命令（在终端保持连接，观察 5 秒后 Ctrl+C）：**

```bash
curl -N http://localhost:3001/events &
curl -N http://localhost:3002/events &

# 触发一次请求
curl -s -X POST http://localhost:3002/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"查询员工趋势"}' > /dev/null

sleep 3
kill %1 %2
```

**通过标准：**

- [ ] 两个 SSE 连接均建立成功，不立即断开
- [ ] 触发请求后，`curl -N http://localhost:3001/events` 和 `http://localhost:3002/events` 均有 `data: {...}` 输出
- [ ] 事件格式为合法 JSON，包含 `time`、`source`、`target`、`type` 字段

---

## 验收结果汇总

| 编号 | 项目 | 结果 | 备注 |
|------|------|------|------|
| AC-01 | 资源中心接口 | | |
| AC-02 | SG-Agent token 换取 | | |
| AC-03a | 员工详情接口（鉴权通过） | | |
| AC-03b | 员工详情接口（鉴权拒绝） | | |
| AC-04 | CF-Agent 非数据查询意图 | | |
| AC-05 | CF-Agent 数据查询 + A2A 链路 | | |
| AC-06 | resource-proxy + MCP resources/read | | |
| AC-07 | 前端完整渲染链路 | | |
| AC-08 | 卡片路径 A（直调 API） | | |
| AC-09 | 卡片路径 B（postMessage） | | |
| AC-10 | 卡片实例缓存过期 | | |
| AC-11 | SSE 事件流可订阅 | | |

**通过定义：** AC-01 至 AC-08、AC-10、AC-11 全部通过；AC-09 通过或标记"待实现"。
