# MCP-UI 双路径改造 - 手动验收文档

**Date:** 2026-04-13  
**适用对象：** 用户手动验收  
**关联设计文档：** `docs/designs/2026-04-13-mcp-ui-dual-path-redesign.md`

---

## 准备工作

1. 启动所有服务：`pnpm dev` 【通过✅
2. 打开浏览器访问：`http://localhost:3000`【通过✅
3. 确认右侧 EventLog 面板可见并有心跳日志【未通过❌ 现象：默认没有 Endpoint 的心跳日志

---

## 验收一：mode 开关可用

1. 观察页面顶部是否有 **Endpoint / MCP Server** 切换开关 【通过✅
2. 默认状态应为 **Endpoint** 【通过✅
3. 点击切换到 **MCP Server**，开关状态改变 【通过✅
4. 刷新页面，开关应仍显示 **MCP Server**（状态保持）【未通过❌ 现象：刷新页面后没有选中 MCP Server
5. 切换回 **Endpoint** 【通过✅

**通过标准：** 开关状态可切换，刷新后保持 【未通过❌

---

## 验收二：Endpoint 路径完整链路

**前置：** 确认开关在 **Endpoint** 模式

### 2-1 发送查询消息

在输入框输入：`查询快手历年员工人数趋势`，点击发送。

**观察 EventLog 面板（从上到下应依次出现）：**

- `Frontend → CF-Agent`：chat 【通过✅
- `CF-Agent → LLM`：intent detection
- `CF-Agent → SG-Agent`：A2A Task 【通过✅
- `SG-Agent → ResourceCenter`：GET /api/components/EmployeeChart 【通过✅
- `SG-Agent → CF-Agent`：A2A Response（含 `card/{id}`）【通过✅

**通过标准：** EventLog 出现完整链路事件，无跳过 【通过✅

### 2-2 图表卡片渲染

**观察聊天区域：**

- 出现文字回复 【通过✅
- 出现图表卡片（Employee Chart），显示 2019-2023 年柱形图 【未通过❌ 现象：卡片区域一直渲染加载中...
- 图表有数据（5 根柱形，数值正确）【未通过❌ 现象：卡片区域一直渲染加载中...

**通过标准：** 图表可见，数据正确，无报错 【未通过❌

### 2-3 resource 加载事件

**观察 EventLog：**

- 出现 `Frontend → CF-Agent`：resource-proxy 【通过✅
- 出现 `CF-Agent → SG-Agent`：MCP resources/read【通过✅

**通过标准：** resource 请求经过完整代理链路 【通过✅

---

## 验收三：MCP Server 路径完整链路

**前置：** 将开关切换到 **MCP Server**

### 3-1 发送相同查询消息

输入：`查询快手历年员工人数趋势`，点击发送。

**观察 EventLog：**

- `CF-Agent → SG-Agent`：A2A Task（带 mode=mcp） 【通过✅
- `SG-Agent → stargate-mcp-ui-server`：MCP tools/call（**新出现，与 Endpoint 路径不同**）【通过✅
- `SG-Agent → CF-Agent`：A2A Response（含 `employee-trend`，无动态 id）未通过❌ 现象：仅有 2 parts，无 employee-trend

**通过标准：** EventLog 中出现 stargate-mcp-ui-server 相关事件

### 3-2 图表卡片渲染

**观察：**

- 图表卡片正常显示，数据与 Endpoint 路径相同 【未通过❌ 现象：卡片区域一直渲染加载中...
- 右侧可见 resource URI 为 `ui://stargate/employee-trend`（静态，无动态 id）【通过✅

**通过标准：** 图表正常，功能与 Endpoint 路径一致 未通过❌

---

## 验收四：模式 A - toolResult 数据不内联 HTML

> 验证 resource HTML 是纯 shell，数据通过 toolResult 流入而非内联在 HTML 中

### 4-1 查看 resource 内容（Endpoint 路径）

切换到 **Endpoint** 模式，发送查询消息后，打开浏览器 DevTools → Network，找到 `/resource-proxy` 请求，查看响应体。

**验证：**

- 响应中 `contents[0].text` 是 HTML 【通过✅
- HTML 中**不**包含 `7000`、`10000` 等员工人数数字
- HTML 中包含 `<div id="root">` 空壳 【通过✅

**通过标准：** HTML 不含数据，仅为渲染容器 【通过✅

### 4-2 查看 resource 内容（MCP Server 路径）

切换到 **MCP Server** 模式，重复上述步骤。

**通过标准：** 同 4-1，HTML 为纯 shell 【通过✅

---

## 验收五：场景 A - 首渲即有数据

**切换到 MCP Server 模式**，打开 DevTools → Network，清空记录，发送查询消息。

**观察：**

- 图表卡片出现时**立即**有数据（无加载中状态） 【未通过❌ 现象：卡片区域一直渲染加载中...
- Network 面板中 `/chat` 响应的 JSON 里包含 `toolResult.data` 数组

**通过标准：** toolResult 随 /chat 响应一同返回，组件首渲有数据 【未通过❌

---

## 验收六：场景 B - 异步加载

**切换到场景 B 演示模式**（如有专门的演示开关）。【未通过❌ 现象：没有专门的演示开关，建议使用别的问题，触发这个 case

**观察：**

1. 图表卡片先出现 loading 状态（骨架屏或转圈）【未通过❌
2. 约 1-2 秒后数据加载完成，图表渲染【未通过❌
3. EventLog 中出现两段事件：第一段是 /chat，第二段是异步的数据获取【未通过❌

**通过标准：** 明显的两阶段渲染，先 shell 后数据 【未通过❌

---

## 验收七：场景 C - guest UI 内交互重新拉取数据

在已渲染的图表卡片内，触发数据刷新交互（如点击"刷新"按钮或切换筛选条件）。

**观察 EventLog：**

- 出现新的 `tools/call` 事件 【未通过❌ 现象：卡片区域一直渲染加载中...
- `CF-Agent → SG-Agent` 再次被调用 【未通过❌ 现象：卡片区域一直渲染加载中...
- 图表数据更新

**通过标准：** guest UI 内交互触发了完整的 tool call 链路【未通过❌

---

## 验收八：场景 D - guest UI 直调业务接口（Agent 不感知）

在图表卡片内点击某年的柱形，触发详情查看（如点击 2022 年柱形）。

**观察：**

1. 出现该年份的详情信息（如：2022 年，22000 人，峰值） 【未通过❌ 现象：卡片区域一直渲染加载中...
2. **EventLog 中不出现** CF-Agent 相关事件（仅 SG-Agent 有日志）【未通过❌ 现象：卡片区域一直渲染加载中...
3. DevTools → Network 中出现直接调用 `http://localhost:3001/api/employee/detail/2022` 的请求
4. 请求头包含 `Authorization: Bearer mock-stargate-token-12345` 【未通过❌ 现象：卡片区域一直渲染加载中...

**通过标准：** 详情展示正常，CF-Agent EventLog 无记录，直接调业务接口【未通过❌

---

## 验收九：toolName 不硬编码

**切换 Endpoint / MCP Server 两种模式**，分别查看图表卡片。

**验证：**

- 两种模式下图表卡片均正常渲染 【未通过❌ 现象：卡片区域一直渲染加载中...
- 打开 DevTools → React DevTools，查看 `CardMessage` 组件的 `toolName` prop，应与后端返回的 `toolName` 一致 【通过✅
- `toolName` 不是写死的字符串，而是来自 API 响应 【通过✅

**通过标准：** `toolName` 动态传入，非硬编码 【通过✅

---

## 验收十：两条路径切换对比

1. 分别用 **Endpoint** 和 **MCP Server** 两种模式发送相同问题
2. 对比两次 EventLog，观察差异：
   - Endpoint：`SG-Agent → ResourceCenter` 获取组件信息
   - MCP Server：`SG-Agent → stargate-mcp-ui-server` MCP tool call
3. 两次图表渲染结果**功能相同**（数据、交互一致）
4. 两次的 `resourceUri` 格式不同：
   - Endpoint：`ui://stargate/card/{动态id}`
   - MCP Server：`ui://stargate/employee-trend`（静态）

**通过标准：** 链路差异清晰可见，最终效果一致，充分体现两种实现路径的对比 【通过✅

---

## 验收通过标准汇总

| 验收项 | 描述                                  | 通过 |
| ------ | ------------------------------------- | ---- |
| 验收一 | mode 开关可用、状态持久               | ☐    |
| 验收二 | Endpoint 路径完整链路                 | ☐    |
| 验收三 | MCP Server 路径完整链路               | ☐    |
| 验收四 | resource HTML 为纯 shell，无内联数据  | ☐    |
| 验收五 | 场景 A：首渲即有数据                  | ☐    |
| 验收六 | 场景 B：异步加载两阶段渲染            | ☐    |
| 验收七 | 场景 C：guest UI 内交互触发 tool call | ☐    |
| 验收八 | 场景 D：直调业务接口，Agent 不感知    | ☐    |
| 验收九 | toolName 动态传入，非硬编码           | ☐    |
| 验收十 | 两条路径切换对比清晰                  | ☐    |

**全部通过即为验收完成。**
