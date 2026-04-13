# 日志面板改造为底部时序图

**Date:** 2026-04-13

## Context

当前应用在右侧有一个宽 420px 的日志面板（`EventLog.tsx`），以终端样式展示各服务节点之间的数据流转记录（`Frontend → CF-Agent → LLM → SG-Agent` 等）。该面板虽然功能完整，但可读性和演示效果较弱。

需求是将右侧日志面板优化为底部的时序图，以更直观的方式展示系统间的调用关系，主要用于演示展示场景。

## Discussion

### 主要目标

确认主要目标为**演示展示**，需要清晰展示各服务节点之间的调用顺序和时序关系，同时支持显示调用详情（`detail` 字段）。

### 时序图风格

选择**标准时序图**风格（类似 UML Sequence Diagram），每个服务有独立生命线，消息用水平箭头连接。

### 更新方式

选择**实时动态渲染**：每来一条新日志，立即在时序图上添加一条消息箭头。

### 方案探索

探索了三种方案：

| 方案 | 技术 | 优点 | 缺点 |
|------|------|------|------|
| A | 纯 CSS/SVG 手写 | 零依赖，完全可控 | 开发成本高，需手动处理箭头定位 |
| B | Mermaid.js | 标准 UML 外观，开发简单 | 全量重绘有闪烁，需新增依赖，hover 详情不支持 |
| C | ECharts（自定义系列）| 复用现有依赖，增量更新，原生 tooltip/事件 | 自定义系列有学习曲线 |

重点对比了三种方案对"调用详情"的支持能力：
- Mermaid 不支持 hover 交互，详情展示能力最弱
- SVG 和 ECharts 均可支持，但 ECharts tooltip/事件系统内置
- **最终选择方案 C（ECharts）**，因其复用现有依赖且演示效果最佳

### 布局与交互

- 底部面板需要**可拖动分隔线**，支持用户调整时序图高度（默认 240px，最小 120px，最大 50vh）
- **删除原有右侧日志面板**，不保留日志/时序图切换功能

## Approach

将应用布局从"左右分栏"改为"上下分栏"：
- 上方：聊天区（flex: 1）+ 输入框
- 中间：可拖动水平分隔条
- 下方：ECharts 时序图面板（默认高度 240px）

删除 `EventLog.tsx` 组件，新增 `SequenceDiagram.tsx` 和 `ResizableDivider.tsx`，数据来源不变（`useEventLog` hook 提供的 `entries`）。

## Architecture

### 布局结构

```
┌───────────────────────────────────────────┐
│  聊天区 (flex: 1, 可滚动)                 │
├───────────────────────────────────────────┤
│  输入框                                   │
├═══════════════════════════════════════════╡ ← 可拖动分隔条
│  时序图面板 (默认 240px, 可拖动调整高度)   │
│  [Frontend] [CF-Agent] [LLM] [SG-Agent]  │
│      │           │      │       │         │
│      ├──chat─────▶      │       │         │
│      │           ├──llm─▶       │         │
│      │           │      ├──A2A──▶         │
└───────────────────────────────────────────┘
```

### 改动文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/App.tsx` | 修改 | 布局改为纵向 flex，移除 EventLog，底部加入分隔线 + 时序图 |
| `src/components/EventLog.tsx` | 删除 | 不再需要 |
| `src/components/SequenceDiagram.tsx` | 新增 | ECharts 时序图主组件 |
| `src/components/ResizableDivider.tsx` | 新增 | 可拖动水平分隔条 |

### 数据流

```
useEventLog(urls)
    → entries: EventLogEntry[]
    → SequenceDiagram props
        → ECharts custom series
            → 参与者节点（X 轴，固定顺序动态出现）
            → 消息箭头（按序列编号，Y 轴从上到下）
            → Tooltip 展示 time / source / target / type / detail
```

### SequenceDiagram 组件设计

**参与者节点（X 轴）：**
- 固定顺序：`Frontend → CF-Agent → LLM → SG-Agent → MCP-Server → ResourceCenter → BusinessAPI`
- 从 entries 中动态提取出现过的节点，按上述顺序排列
- 每个节点绘制矩形标签 + 垂直虚线（生命线）

**消息箭头（Y 轴）：**
- Y 轴为消息序号，从上到下表示时间顺序
- 每条 entry 绘制从 source 到 target 的水平线 + 箭头
- 箭头中部显示 `type` 标签
- 使用 ECharts `custom series` 自定义绘制

**Tooltip 内容：**
```
[10:30:46] CF-Agent → LLM
type: llm-call
detail: intent detection
```

**增量更新策略：**
- 每次 entries 变化时调用 `echartsInstance.setOption`，不重建实例
- 当消息条数超出可视区域时，Y 轴自动滚动到最新消息

### ResizableDivider 组件设计

- 高度 6px 的可拖动水平分隔条
- 监听 `mousedown` → `mousemove` → `mouseup` 事件
- 拖动时动态更新 `App.tsx` 中的 `diagramHeight` state
- 限制：最小高度 120px，最大高度 `window.innerHeight * 0.5`
