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
