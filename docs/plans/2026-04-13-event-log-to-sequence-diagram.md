# 日志面板改造为底部时序图 Implementation Plan

**Goal:** 将右侧 420px 的文本日志面板替换为底部可拖动的 ECharts 时序图，实时动态展示服务节点间的调用关系。

**Architecture:** 删除 `EventLog.tsx`，新增 `SequenceDiagram.tsx`（ECharts custom series 绘制时序图）和 `ResizableDivider.tsx`（可拖动分隔条）。`App.tsx` 布局从左右分栏改为上下分栏，数据来源不变（`useEventLog` hook）。

**Tech Stack:** React 18, TypeScript, ECharts 5（需新增到 codeflicker-frontend），Vite

---

## 背景知识

### 现有代码结构

```
packages/codeflicker-frontend/src/
├── App.tsx                    # 主布局，当前左右分栏
├── types.ts                   # EventLogEntry 类型定义
├── hooks/useEventLog.ts       # SSE 订阅，返回 entries: EventLogEntry[]
└── components/
    ├── EventLog.tsx            # 待删除的右侧日志面板
    ├── ChatMessage.tsx
    └── CardMessage.tsx
```

### EventLogEntry 类型（来自 types.ts）

```typescript
interface EventLogEntry {
  time: string;    // "HH:MM:SS"
  source: string;  // "Frontend" | "CF-Agent" | "LLM" | "SG-Agent" | ...
  target: string;
  type: string;    // "chat" | "llm-call" | "A2A Task" | ...
  detail: string;
}
```

### 参与者节点固定顺序

```
Frontend → CF-Agent → LLM → SG-Agent → MCP-Server → ResourceCenter → BusinessAPI
```

---

## Task 1: 安装 ECharts 依赖

**Files:**
- Modify: `packages/codeflicker-frontend/package.json`

### Step 1: 安装 ECharts 到 codeflicker-frontend 包

在 `packages/codeflicker-frontend` 目录下运行：

```bash
cd packages/codeflicker-frontend && pnpm add echarts
```

### Step 2: 确认安装成功

`packages/codeflicker-frontend/package.json` 的 `dependencies` 中应出现：

```json
"echarts": "^5.x.x"
```

---

## Task 2: 新增 ResizableDivider 组件

**Files:**
- Create: `packages/codeflicker-frontend/src/components/ResizableDivider.tsx`

### Step 1: 创建组件文件

```typescript
import React, { useCallback } from 'react';

interface Props {
  onResize: (delta: number) => void;
}

export const ResizableDivider: React.FC<Props> = ({ onResize }) => {
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      const startY = e.clientY;

      const handleMouseMove = (ev: MouseEvent) => {
        onResize(startY - ev.clientY);
      };

      const handleMouseUp = () => {
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
      };

      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
    },
    [onResize]
  );

  return (
    <div
      onMouseDown={handleMouseDown}
      style={{
        height: 6,
        background: '#e0e0e0',
        cursor: 'row-resize',
        flexShrink: 0,
        borderTop: '1px solid #ccc',
        borderBottom: '1px solid #ccc',
      }}
    />
  );
};
```

**逻辑说明：**
- `onResize(delta)` 传入正值表示向上拖动（扩大时序图），负值表示向下拖动（缩小时序图）
- `startY - ev.clientY`：鼠标向上移动时 `ev.clientY` 变小，delta 为正，时序图应变高

---

## Task 3: 新增 SequenceDiagram 组件

**Files:**
- Create: `packages/codeflicker-frontend/src/components/SequenceDiagram.tsx`

### Step 1: 创建组件文件

该组件接收 `entries`，用 ECharts `custom series` 绘制标准时序图。

```typescript
import React, { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import type { EventLogEntry } from '../types';

interface Props {
  entries: EventLogEntry[];
}

const ALL_PARTICIPANTS = [
  'Frontend',
  'CF-Agent',
  'LLM',
  'SG-Agent',
  'MCP-Server',
  'ResourceCenter',
  'BusinessAPI',
];

const HEADER_HEIGHT = 40;
const ROW_HEIGHT = 36;
const LIFELINE_COLOR = '#bbb';
const ARROW_COLOR = '#4a9eff';
const LABEL_COLOR = '#f9c74f';
const BG_COLOR = '#1a1a2e';
const NODE_BG = '#2a2a4a';
const NODE_TEXT = '#e0e0e0';

export const SequenceDiagram: React.FC<Props> = ({ entries }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    chartRef.current = echarts.init(containerRef.current, null, { renderer: 'svg' });
    return () => {
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    const usedParticipants = ALL_PARTICIPANTS.filter((p) =>
      entries.some((e) => e.source === p || e.target === p)
    );

    if (usedParticipants.length === 0) {
      chart.setOption({
        backgroundColor: BG_COLOR,
        graphic: [
          {
            type: 'text',
            left: 'center',
            top: 'middle',
            style: { text: '等待数据流...', fill: '#555', fontSize: 13 },
          },
        ],
        series: [],
      });
      return;
    }

    const colCount = usedParticipants.length;
    const rowCount = entries.length;
    const totalHeight = HEADER_HEIGHT + rowCount * ROW_HEIGHT + 20;

    const participantIndex = (name: string) => usedParticipants.indexOf(name);

    const graphicElements: echarts.GraphicComponentOption[] = [];

    usedParticipants.forEach((name, i) => {
      const xPct = ((i + 0.5) / colCount) * 100;

      graphicElements.push({
        type: 'rect',
        left: `${xPct}%`,
        top: 4,
        shape: { x: -44, y: 0, width: 88, height: 24 },
        style: { fill: NODE_BG, stroke: '#4a9eff', lineWidth: 1 },
        z: 10,
      } as any);

      graphicElements.push({
        type: 'text',
        left: `${xPct}%`,
        top: 10,
        style: { text: name, fill: NODE_TEXT, fontSize: 11, textAlign: 'center' },
        z: 11,
      } as any);

      graphicElements.push({
        type: 'line',
        left: `${xPct}%`,
        top: 0,
        shape: { x1: 0, y1: HEADER_HEIGHT, x2: 0, y2: totalHeight },
        style: { stroke: LIFELINE_COLOR, lineWidth: 1, lineDash: [4, 4] },
        z: 1,
      } as any);
    });

    entries.forEach((entry, rowIdx) => {
      const srcIdx = participantIndex(entry.source);
      const tgtIdx = participantIndex(entry.target);
      if (srcIdx === -1 || tgtIdx === -1) return;

      const y = HEADER_HEIGHT + rowIdx * ROW_HEIGHT + ROW_HEIGHT / 2;
      const srcXPct = ((srcIdx + 0.5) / colCount) * 100;
      const tgtXPct = ((tgtIdx + 0.5) / colCount) * 100;
      const midXPct = (srcXPct + tgtXPct) / 2;
      const goRight = tgtIdx >= srcIdx;

      graphicElements.push({
        type: 'line',
        left: 0,
        top: 0,
        shape: {
          x1: `${srcXPct}%`,
          y1: y,
          x2: `${tgtXPct}%`,
          y2: y,
          percent: 1,
        },
        style: { stroke: ARROW_COLOR, lineWidth: 1.5 },
        z: 5,
      } as any);

      const arrowSize = 7;
      const arrowDir = goRight ? 1 : -1;
      graphicElements.push({
        type: 'polygon',
        left: `${tgtXPct}%`,
        top: y,
        shape: {
          points: [
            [0, 0],
            [-arrowDir * arrowSize, -arrowSize / 2],
            [-arrowDir * arrowSize, arrowSize / 2],
          ],
        },
        style: { fill: ARROW_COLOR },
        z: 6,
      } as any);

      graphicElements.push({
        type: 'text',
        left: `${midXPct}%`,
        top: y - 14,
        style: {
          text: entry.type,
          fill: LABEL_COLOR,
          fontSize: 10,
          textAlign: 'center',
        },
        z: 7,
      } as any);
    });

    chart.setOption(
      {
        backgroundColor: BG_COLOR,
        graphic: graphicElements,
        series: [],
        tooltip: { show: false },
        xAxis: { show: false },
        yAxis: { show: false },
        grid: { show: false },
      },
      { replaceMerge: ['graphic'] }
    );
  }, [entries]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !containerRef.current) return;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  return (
    <div style={{ width: '100%', height: '100%', background: BG_COLOR, position: 'relative' }}>
      <div
        style={{
          position: 'absolute',
          top: 6,
          left: 8,
          fontSize: 11,
          color: '#555',
          fontFamily: 'monospace',
          zIndex: 20,
          pointerEvents: 'none',
        }}
      >
        时序图
      </div>
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
    </div>
  );
};
```

**核心逻辑说明：**
- `usedParticipants`：从 `ALL_PARTICIPANTS` 固定列表中过滤出本次 entries 实际出现的节点，保持顺序
- 节点位置用百分比计算（`(i + 0.5) / colCount * 100%`），自动适应容器宽度
- 每条 entry 绘制：水平线 + 箭头三角形 + 中部 type 标签
- `replaceMerge: ['graphic']` 确保每次更新时替换全部图形元素，不累加

---

## Task 4: 修改 App.tsx 布局

**Files:**
- Modify: `packages/codeflicker-frontend/src/App.tsx`

### Step 1: 替换整个 App.tsx

将原来的左右分栏布局改为上下分栏，加入 `diagramHeight` state 和可拖动分隔线。

```typescript
import React, { useState, useRef, useEffect, useCallback } from 'react';
import type { ChatMessage as ChatMessageType, MessagePart } from './types';
import { ChatMessage } from './components/ChatMessage';
import { SequenceDiagram } from './components/SequenceDiagram';
import { ResizableDivider } from './components/ResizableDivider';
import { useEventLog } from './hooks/useEventLog';

let msgIdCounter = 0;
const newId = () => String(++msgIdCounter);

const MIN_DIAGRAM_HEIGHT = 120;
const MAX_DIAGRAM_HEIGHT_RATIO = 0.5;

export const App: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<'endpoint' | 'mcp'>('endpoint');
  const [diagramHeight, setDiagramHeight] = useState(240);
  const bottomRef = useRef<HTMLDivElement>(null);

  const eventEntries = useEventLog([
    'http://localhost:3002/events',
    'http://localhost:3001/events',
  ]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    fetch('/mode').then((r) => r.json()).then((d) => {
      if (d.mode === 'endpoint' || d.mode === 'mcp') setMode(d.mode);
    }).catch(() => {});
  }, []);

  const switchMode = async (newMode: 'endpoint' | 'mcp') => {
    await fetch('/mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: newMode }),
    });
    setMode(newMode);
  };

  const handleResize = useCallback((delta: number) => {
    setDiagramHeight((prev) => {
      const maxH = window.innerHeight * MAX_DIAGRAM_HEIGHT_RATIO;
      return Math.min(maxH, Math.max(MIN_DIAGRAM_HEIGHT, prev + delta));
    });
  }, []);

  const sendMessage = async (text?: string) => {
    const finalText = (text ?? input).trim();
    if (!finalText || loading) return;
    setInput('');
    setLoading(true);

    const userMsg: ChatMessageType = {
      id: newId(),
      role: 'user',
      parts: [{ kind: 'text', text: finalText }],
    };
    setMessages((prev) => [...prev, userMsg]);

    try {
      const res = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: finalText }),
      });
      const data = await res.json();
      const parts: MessagePart[] = (data.parts ?? []).map((p: any) => {
        if (p.kind === 'text') return { kind: 'text' as const, text: p.text };
        if (p.kind === 'mcp_ui_resource') return {
          kind: 'mcp_ui_resource' as const,
          resourceUri: p.resourceUri,
          toolName: p.toolName,
          toolResult: p.toolResult,
          uiMetadata: p.uiMetadata,
        };
        return { kind: 'text' as const, text: JSON.stringify(p) };
      });
      const agentMsg: ChatMessageType = { id: newId(), role: 'agent', parts };
      setMessages((prev) => [...prev, agentMsg]);
    } catch {
      setMessages((prev) => [...prev, {
        id: newId(), role: 'agent',
        parts: [{ kind: 'text', text: '请求失败，请检查服务是否启动。' }],
      }]);
    } finally {
      setLoading(false);
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', fontFamily: 'system-ui, sans-serif' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid #e0e0e0', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
          <span style={{ fontWeight: 600 }}>CodeFlicker x MCP-UI Demo</span>
          <div style={{ display: 'flex', gap: 4, marginLeft: 'auto' }}>
            <button
              onClick={() => switchMode('endpoint')}
              style={{
                padding: '4px 12px', borderRadius: 6, border: '1px solid #ccc', cursor: 'pointer',
                background: mode === 'endpoint' ? '#0084ff' : '#fff',
                color: mode === 'endpoint' ? '#fff' : '#333',
                fontSize: 13,
              }}
            >
              Endpoint
            </button>
            <button
              onClick={() => switchMode('mcp')}
              style={{
                padding: '4px 12px', borderRadius: 6, border: '1px solid #ccc', cursor: 'pointer',
                background: mode === 'mcp' ? '#0084ff' : '#fff',
                color: mode === 'mcp' ? '#fff' : '#333',
                fontSize: 13,
              }}
            >
              MCP Server
            </button>
          </div>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          {messages.map((m) => (
            <ChatMessage
              key={m.id}
              message={m}
              onCardMessage={(text) => sendMessage(text)}
              onLayout={() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' })}
            />
          ))}
          {loading && <div style={{ color: '#888', padding: '8px 0' }}>思考中...</div>}
          <div ref={bottomRef} />
        </div>
        <div style={{ padding: 12, borderTop: '1px solid #e0e0e0', display: 'flex', gap: 8, flexShrink: 0 }}>
          <input
            style={{ flex: 1, padding: '8px 12px', borderRadius: 8, border: '1px solid #ccc', fontSize: 14 }}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
            placeholder="输入消息，例如：查询快手历年员工人数趋势"
            disabled={loading}
          />
          <button
            style={{ padding: '8px 16px', borderRadius: 8, background: '#0084ff', color: '#fff', border: 'none', cursor: 'pointer' }}
            onClick={() => sendMessage()}
            disabled={loading}
          >
            发送
          </button>
        </div>
      </div>
      <ResizableDivider onResize={handleResize} />
      <div style={{ height: diagramHeight, flexShrink: 0 }}>
        <SequenceDiagram entries={eventEntries} />
      </div>
    </div>
  );
};
```

**关键变更说明：**
- 最外层 `div` 改为 `flexDirection: 'column'`
- 上半部分包裹在 `flex: 1` + `overflow: 'hidden'` 的容器中，防止撑破布局
- 删除了 `import { EventLog }` 和右侧 420px 的 `<div>`
- 底部依次插入 `<ResizableDivider>` 和固定高度的 `<SequenceDiagram>`

---

## Task 5: 删除 EventLog.tsx

**Files:**
- Delete: `packages/codeflicker-frontend/src/components/EventLog.tsx`

### Step 1: 删除文件

```bash
rm packages/codeflicker-frontend/src/components/EventLog.tsx
```

---

## Task 6: 类型检查与构建验证

### Step 1: 在 codeflicker-frontend 包中运行类型检查

```bash
cd packages/codeflicker-frontend && npx tsc --noEmit
```

预期输出：无错误

**常见错误及处理：**
- `Cannot find module 'echarts'`：确认 Task 1 安装步骤已完成
- `Property '_seq' does not exist`：`useEventLog` 返回的是 `EventLogEntry[]`，`SequenceDiagram` 只使用 `EventLogEntry` 的字段，无需修改

### Step 2: 运行开发服务器验证

```bash
cd packages/codeflicker-frontend && pnpm dev
```

打开 `http://localhost:3000`，验证：
1. 页面不再显示右侧日志面板
2. 底部显示深色背景的时序图区域，显示"等待数据流..."
3. 可以拖动分隔条上下调整时序图高度
4. 发送一条消息后，时序图上出现参与者节点和消息箭头

---

## Task 7: 为 SequenceDiagram 补充 Hover Tooltip

ECharts 的 `graphic` 组件不支持内置 `tooltip`，需要自行实现：在每条箭头线上绑定 ECharts `graphic` 的 `onmouseover` / `onmouseout` 回调，配合叠加在容器上的绝对定位 `div` 显示详情。

**Files:**
- Modify: `packages/codeflicker-frontend/src/components/SequenceDiagram.tsx`

### Step 1: 在组件 state 中增加 tooltip 状态

在 `SequenceDiagram.tsx` 顶部，将 `useRef` 导入改为同时导入 `useState`，并新增 tooltip state：

```typescript
import React, { useEffect, useRef, useState } from 'react';
```

在组件函数体内，`chartRef` 声明之后加入：

```typescript
interface TooltipState {
  visible: boolean;
  x: number;
  y: number;
  content: string;
}

const [tooltip, setTooltip] = useState<TooltipState>({ visible: false, x: 0, y: 0, content: '' });
```

### Step 2: 为每条箭头线绑定 mouseover / mouseout 回调

在 `entries.forEach` 中，将绘制水平线的 `graphicElements.push` 替换为带事件回调的版本：

```typescript
graphicElements.push({
  type: 'line',
  left: 0,
  top: 0,
  shape: {
    x1: `${srcXPct}%`,
    y1: y,
    x2: `${tgtXPct}%`,
    y2: y,
  },
  style: { stroke: ARROW_COLOR, lineWidth: 1.5 },
  z: 5,
  onmouseover: (evt: any) => {
    const lines = [`[${entry.time}]  ${entry.source} → ${entry.target}`, `type: ${entry.type}`];
    if (entry.detail) lines.push(`detail: ${entry.detail}`);
    setTooltip({
      visible: true,
      x: evt.offsetX + 12,
      y: evt.offsetY + 12,
      content: lines.join('\n'),
    });
  },
  onmouseout: () => {
    setTooltip((prev) => ({ ...prev, visible: false }));
  },
  cursor: 'pointer',
} as any);
```

> `evt.offsetX` / `evt.offsetY` 是相对于 ECharts 容器的鼠标坐标，直接用于定位绝对定位的 tooltip `div`。

### Step 3: 在返回的 JSX 中加入 tooltip div

将 `return` 中的 `<div ref={containerRef} .../>` 之后加入 tooltip 元素：

```typescript
return (
  <div style={{ width: '100%', height: '100%', background: BG_COLOR, position: 'relative' }}>
    <div
      style={{
        position: 'absolute',
        top: 6,
        left: 8,
        fontSize: 11,
        color: '#555',
        fontFamily: 'monospace',
        zIndex: 20,
        pointerEvents: 'none',
      }}
    >
      时序图
    </div>
    <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
    {tooltip.visible && (
      <div
        style={{
          position: 'absolute',
          left: tooltip.x,
          top: tooltip.y,
          background: '#2a2a4a',
          border: '1px solid #4a9eff',
          borderRadius: 4,
          padding: '6px 10px',
          fontSize: 11,
          fontFamily: 'monospace',
          color: '#e0e0e0',
          whiteSpace: 'pre',
          pointerEvents: 'none',
          zIndex: 100,
          lineHeight: 1.6,
          boxShadow: '0 2px 8px rgba(0,0,0,0.5)',
        }}
      >
        {tooltip.content}
      </div>
    )}
  </div>
);
```

### Step 4: 验证 tooltip 效果

启动开发服务器后，发送一条消息触发数据流，然后将鼠标悬停在时序图的任意箭头线上，应弹出如下格式的 tooltip：

```
[10:30:46]  CF-Agent → LLM
type: llm-call
detail: intent detection
```

鼠标移开后 tooltip 消失。

---

## 验收标准

| 功能 | 验证方式 |
|------|---------|
| 右侧日志面板已移除 | 页面右侧无 420px 黑色终端面板 |
| 底部时序图存在 | 底部有深色背景区域 |
| 等待状态 | 未收到日志时显示"等待数据流..." |
| 节点出现 | 收到第一条日志后，对应的参与者节点和生命线出现 |
| 箭头绘制 | 每条日志对应一条水平箭头，方向正确（source → target）|
| type 标签 | 箭头上方显示对应的 type 值 |
| 分隔线拖动 | 上下拖动分隔线可改变时序图高度 |
| 高度限制 | 时序图高度不低于 120px，不超过窗口高度 50% |
| Hover Tooltip | 鼠标悬停箭头时弹出包含 time/source/target/type/detail 的 tooltip |
| Tooltip 消失 | 鼠标移开箭头后 tooltip 消失 |
| 类型检查通过 | `tsc --noEmit` 无报错 |
