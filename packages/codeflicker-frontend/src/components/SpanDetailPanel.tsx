import React from 'react';
import type { EventLogEntry } from '../types';

interface SpanPair {
  request: EventLogEntry;
  response?: EventLogEntry;
}

interface Props {
  pair: SpanPair | null;
  onClose: () => void;
}

function calcDuration(req: EventLogEntry, resp?: EventLogEntry): string {
  if (!resp) return '-';
  const parse = (t: string) => {
    const [hms, ms = '0'] = t.split('.');
    const [h, m, s] = hms.split(':').map(Number);
    return (h * 3600 + m * 60 + s) * 1000 + Number(ms);
  };
  const diff = parse(resp.time) - parse(req.time);
  return diff >= 0 ? `${diff}ms` : '-';
}

function tryFormatJson(raw: string): string {
  const idx = raw.indexOf('\n');
  if (idx === -1) return raw;
  const jsonPart = raw.slice(idx + 1);
  try {
    return raw.slice(0, idx) + '\n' + JSON.stringify(JSON.parse(jsonPart), null, 2);
  } catch {
    return raw;
  }
}

export const SpanDetailPanel: React.FC<Props> = ({ pair, onClose }) => {
  if (!pair) return null;
  const { request, response } = pair;
  const duration = calcDuration(request, response);

  return (
    <div style={{
      width: 320,
      flexShrink: 0,
      borderLeft: '1px solid #e2e8f0',
      background: '#f8fafc',
      display: 'flex',
      flexDirection: 'column',
      fontSize: 11,
      fontFamily: 'monospace',
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '8px 12px',
        borderBottom: '1px solid #e2e8f0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: '#fff',
      }}>
        <span style={{ fontWeight: 600, color: '#1e293b' }}>Span 详情</span>
        <button
          onClick={onClose}
          style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: 14, color: '#94a3b8' }}
        >✕</button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px' }}>
        <Row label="span_id" value={request.span_id ?? '-'} />
        <Row label="耗时" value={duration} highlight />

        <Section title="去程 (Request)">
          <Row label="时间" value={request.time} />
          <Row label="路径" value={`${request.source} → ${request.target}`} />
          <Row label="类型" value={request.type} />
          {request.detail && <Pre label="params" value={tryFormatJson(request.detail)} />}
        </Section>

        {response && (
          <Section title="回程 (Response)">
            <Row label="时间" value={response.time} />
            <Row label="路径" value={`${response.source} → ${response.target}`} />
            {response.detail && <Pre label="result" value={tryFormatJson(response.detail)} />}
          </Section>
        )}
        {!response && (
          <div style={{ color: '#f59e0b', marginTop: 8 }}>等待回程...</div>
        )}
      </div>
    </div>
  );
};

const Row: React.FC<{ label: string; value: string; highlight?: boolean }> = ({ label, value, highlight }) => (
  <div style={{ display: 'flex', gap: 6, marginBottom: 4 }}>
    <span style={{ color: '#64748b', minWidth: 52 }}>{label}:</span>
    <span style={{ color: highlight ? '#2563eb' : '#1e293b', wordBreak: 'break-all' }}>{value}</span>
  </div>
);

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div style={{ marginTop: 12 }}>
    <div style={{ color: '#92400e', fontWeight: 600, marginBottom: 4 }}>{title}</div>
    {children}
  </div>
);

const Pre: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div style={{ marginTop: 4 }}>
    <div style={{ color: '#64748b' }}>{label}:</div>
    <pre style={{
      margin: '2px 0 0',
      padding: '4px 6px',
      background: '#f1f5f9',
      border: '1px solid #e2e8f0',
      borderRadius: 3,
      fontSize: 10,
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-all',
      maxHeight: 160,
      overflowY: 'auto',
    }}>{value}</pre>
  </div>
);
