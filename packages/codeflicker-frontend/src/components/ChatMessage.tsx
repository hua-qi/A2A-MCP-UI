import React from 'react';
import type { ChatMessage as ChatMessageType } from '../types';
import { CardMessage } from './CardMessage';

interface Props {
  message: ChatMessageType;
  onCardMessage?: (text: string) => void;
  onLayout?: () => void;
}

export const ChatMessage: React.FC<Props> = ({ message, onCardMessage, onLayout }) => (
  <div style={{ marginBottom: 12, display: 'flex', flexDirection: message.role === 'user' ? 'row-reverse' : 'row', gap: 8 }}>
    <div style={{ maxWidth: '80%' }}>
      {message.parts.map((part, i) => {
        if (part.kind === 'text') {
          return (
            <div key={i} style={{
              background: message.role === 'user' ? '#0084ff' : '#f0f0f0',
              color: message.role === 'user' ? '#fff' : '#333',
              padding: '8px 12px',
              borderRadius: 12,
              marginBottom: 4,
            }}>
              {part.text}
            </div>
          );
        }
        if (part.kind === 'mcp_ui_resource') {
          return (
            <CardMessage
              key={i}
              resourceUri={part.resourceUri}
              toolName={part.toolName}
              toolResult={part.toolResult}
              uiMetadata={part.uiMetadata}
              onMessage={onCardMessage}
              onLayout={onLayout}
            />
          );
        }
        return null;
      })}
    </div>
  </div>
);
