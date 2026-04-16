import React, { useState, useRef } from 'react';
import { AppRenderer } from '@mcp-ui/client';
import type { McpUiResourcePart } from '../types';

interface Props {
  resourceUri: string;
  toolName?: string;
  toolResult?: McpUiResourcePart['toolResult'];
  uiMetadata?: McpUiResourcePart['uiMetadata'];
  onMessage?: (text: string) => void;
  onLayout?: () => void;
}

export const CardMessage: React.FC<Props> = ({
  resourceUri,
  toolName,
  toolResult,
  uiMetadata,
  onMessage,
  onLayout,
}) => {
  const { width = 560, height: preferredHeight } = uiMetadata?.['preferred-frame-size'] ?? {};
  const sandboxUrl = new URL('/sandbox_proxy.html', window.location.href);
  const [iframeHeight, setIframeHeight] = useState<number | undefined>(preferredHeight);
  const rendererRef = useRef<any>(null);

  const handleCallTool = async (params: { name: string; arguments?: Record<string, unknown> }) => {
    const res = await fetch('/a2a-tool-call', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ toolName: params.name, arguments: params.arguments ?? {} }),
    });
    const data = await res.json();
    return data.toolResult ?? {};
  };

  return (
    <div style={{
      border: (iframeHeight && iframeHeight > 0) ? '1px solid #e0e0e0' : 'none',
      borderRadius: 8,
      overflow: 'hidden',
      width,
      height: iframeHeight ?? 0,
      transition: 'height 0.2s ease',
    }}>
      <AppRenderer
        ref={rendererRef}
        toolName={toolName as string}
        toolResult={toolResult as any}
        sandbox={{ url: sandboxUrl }}
        toolResourceUri={resourceUri}
        onReadResource={async ({ uri }, extra) => {
          const source = extra && Object.keys(extra).length > 0 ? 'app' : 'host';
          const res = await fetch(`/resource-proxy?uri=${encodeURIComponent(uri)}&source=${source}`);
          return res.json();
        }}
        onCallTool={handleCallTool as any}
        onSizeChanged={({ height }) => {
          if (height !== undefined) {
            setIframeHeight(height);
            onLayout?.();
          }
        }}
        onMessage={async (params) => {
          const textBlock = params.content.find((c: any) => c.type === 'text');
          if (textBlock && onMessage) {
            onMessage((textBlock as any).text);
          }
          return {};
        }}
        onError={(e) => console.error('[AppRenderer]', e)}
      />
    </div>
  );
};
