import React, { useState, useRef, useEffect, useCallback } from 'react';
import type { ChatMessage as ChatMessageType, MessagePart } from './types';
import { ChatMessage } from './components/ChatMessage';
import { ResizableDivider } from './components/ResizableDivider';
import { SequenceDiagram } from './components/SequenceDiagram';
import { useEventLog } from './hooks/useEventLog';

let msgIdCounter = 0;
const newId = () => String(++msgIdCounter);

const MIN_DIAGRAM_HEIGHT = 120;
const MAX_DIAGRAM_HEIGHT_RATIO = 0.5;

interface StreamEvent {
  type: 'status' | 'complete' | 'error';
  state?: string;
  message?: string;
  result?: any;
  code?: number;
}

export const App: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [statusText, setStatusText] = useState('');
  const [mode, setMode] = useState<'endpoint' | 'mcp'>('endpoint');
  const [diagramHeight, setDiagramHeight] = useState(240);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const eventEntries = useEventLog(['/events']);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, statusText]);

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
    setStatusText('');

    const userMsg: ChatMessageType = {
      id: newId(),
      role: 'user',
      parts: [{ kind: 'text', text: finalText }],
    };
    setMessages((prev) => [...prev, userMsg]);

    try {
      // Create SSE connection for streaming
      abortControllerRef.current = new AbortController();
      
      const response = await fetch('/chat-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: finalText, mode }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.trim() === '') continue;
          
          // Parse SSE format: event: xxx\ndata: {...}
          if (line.startsWith('data: ')) {
            try {
              const data: StreamEvent = JSON.parse(line.slice(6));
              
              switch (data.type) {
                case 'status':
                  setStatusText(data.message || '');
                  break;
                  
                case 'complete':
                  setStatusText('');
                  const parts = parseResponseParts(data.result);
                  const agentMsg: ChatMessageType = { 
                    id: newId(), 
                    role: 'agent', 
                    parts 
                  };
                  setMessages((prev) => [...prev, agentMsg]);
                  break;
                  
                case 'error':
                  setStatusText('');
                  setMessages((prev) => [...prev, {
                    id: newId(), 
                    role: 'agent',
                    parts: [{ kind: 'text', text: `错误: ${data.message}` }],
                  }]);
                  break;
              }
            } catch (e) {
              console.error('Failed to parse SSE data:', line, e);
            }
          }
        }
      }
    } catch (err) {
      if (err instanceof Error && err.name !== 'AbortError') {
        setMessages((prev) => [...prev, {
          id: newId(), 
          role: 'agent',
          parts: [{ kind: 'text', text: '请求失败，请检查服务是否启动。' }],
        }]);
      }
    } finally {
      setLoading(false);
      setStatusText('');
      abortControllerRef.current = null;
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
    }
  };

  const parseResponseParts = (result: any): MessagePart[] => {
    if (!result) return [{ kind: 'text', text: '无响应数据' }];
    
    const parts: MessagePart[] = [];
    
    if (result.text) {
      parts.push({ kind: 'text', text: result.text });
    }
    
    if (result.mcp_ui_resource) {
      parts.push({
        kind: 'mcp_ui_resource',
        resourceUri: result.mcp_ui_resource.resourceUri,
        toolName: result.mcp_ui_resource.toolName,
        toolResult: result.mcp_ui_resource.toolResult,
        uiMetadata: result.mcp_ui_resource.uiMetadata,
      });
    }
    
    if (parts.length === 0) {
      parts.push({ kind: 'text', text: JSON.stringify(result) });
    }
    
    return parts;
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
          {statusText && (
            <div style={{ color: '#0084ff', padding: '8px 0', fontStyle: 'italic' }}>
              {statusText}
            </div>
          )}
          {loading && !statusText && (
            <div style={{ color: '#888', padding: '8px 0' }}>思考中...</div>
          )}
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
      <div style={{ height: diagramHeight, flexShrink: 0, borderTop: '1px solid #e0e0e0', background: '#f5f5f5' }}>
        <SequenceDiagram entries={eventEntries} />
      </div>
    </div>
  );
};
