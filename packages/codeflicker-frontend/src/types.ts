export interface TextPart {
  kind: 'text';
  text: string;
}

export interface McpUiResourcePart {
  kind: 'mcp_ui_resource';
  resourceUri: string;
  toolName?: string;
  toolResult?: {
    content?: Array<{ type: string; text: string }>;
    data?: Array<{ year: number; count: number }>;
    token?: string;
  };
  uiMetadata?: { 'preferred-frame-size'?: { width: number; height: number } };
}

export type MessagePart = TextPart | McpUiResourcePart;

export interface ChatMessage {
  id: string;
  role: 'user' | 'agent';
  parts: MessagePart[];
}

export interface EventLogEntry {
  time: string;
  source: string;
  target: string;
  type: string;
  detail: string;
  span_id?: string;
  direction?: 'request' | 'response';
}
