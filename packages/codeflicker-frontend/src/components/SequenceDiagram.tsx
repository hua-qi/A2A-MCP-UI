import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as echarts from 'echarts';
import type { EventLogEntry } from '../types';
import { SpanDetailPanel } from './SpanDetailPanel';

interface Props {
  entries: EventLogEntry[];
}

const TOOLTIP_H_ESTIMATE = 72;
const TOOLTIP_W_ESTIMATE = 280;

interface TooltipState {
  visible: boolean;
  x: number;
  y: number;
  content: string;
  flipUp: boolean;
}

interface HotZone {
  left: number;
  top: number;
  width: number;
  height: number;
  content: string;
  entryIdx: number;
}

const ALL_PARTICIPANTS = [
  'Frontend',
  'CF-Agent',
  'CF-LLM',
  'SG-Agent',
  'SG-LLM',
  'MCP-Server',
  'ResourceCenter',
  'BusinessAPI',
];

const HEADER_HEIGHT = 44;
const ROW_HEIGHT = 28;
const ARROW_SIZE = 6;
const HOT_ZONE_H = 16;
const LIFELINE_COLOR = '#c0cfe0';
const ARROW_COLOR = '#2563eb';
const RESPONSE_COLOR = '#64748b';
const HOVER_COLOR = '#f59e0b';
const LABEL_COLOR = '#92400e';
const BG_COLOR = '#f8fafc';
const NODE_TEXT_COLOR = '#1e293b';

export const SequenceDiagram: React.FC<Props> = ({ entries }) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const [usedParticipants, setUsedParticipants] = useState<string[]>([]);
  const [hotZones, setHotZones] = useState<HotZone[]>([]);
  const [tooltip, setTooltip] = useState<TooltipState>({ visible: false, x: 0, y: 0, content: '', flipUp: false });
  const [hoveredSpanId, setHoveredSpanId] = useState<string | null>(null);
  const [selectedPair, setSelectedPair] = useState<{ request: EventLogEntry; response?: EventLogEntry } | null>(null);
  const [spanMapState, setSpanMapState] = useState<Map<string, { reqIdx?: number; respIdx?: number }>>(new Map());

  useEffect(() => {
    if (!canvasRef.current) return;
    chartRef.current = echarts.init(canvasRef.current, null, { renderer: 'svg' });
    return () => {
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, []);

  const renderChart = useCallback(() => {
    const chart = chartRef.current;
    const canvas = canvasRef.current;
    const scroll = scrollRef.current;
    if (!chart || !canvas || !scroll) return;

    const W = scroll.clientWidth;

    const participants = ALL_PARTICIPANTS.filter((p) =>
      entries.some((e) => e.source === p || e.target === p)
    );

    setUsedParticipants(participants);

    if (participants.length === 0) {
      setHotZones([]);
      chart.setOption(
        {
          backgroundColor: BG_COLOR,
          graphic: [{
            type: 'text',
            left: 'center',
            top: 'middle',
            style: { text: '等待数据流...', fill: '#94a3b8', fontSize: 12, fontFamily: 'monospace' },
          }],
        },
        { replaceMerge: ['graphic'] }
      );
      chart.resize({ width: W, height: scroll.clientHeight });
      return;
    }

    const colCount = participants.length;
    const colW = W / colCount;
    const colX = (i: number) => colW * i + colW / 2;

    const rowCount = entries.length;
    const bodyH = rowCount * ROW_HEIGHT + 16;
    const totalH = Math.max(bodyH, scroll.clientHeight - HEADER_HEIGHT);

    const spanMap = new Map<string, { reqIdx?: number; respIdx?: number }>();
    entries.forEach((e, idx) => {
      if (!e.span_id) return;
      const existing = spanMap.get(e.span_id) ?? {};
      if (e.direction === 'request') existing.reqIdx = idx;
      if (e.direction === 'response') existing.respIdx = idx;
      spanMap.set(e.span_id, existing);
    });
    setSpanMapState(new Map(spanMap));

    const graphicElements: any[] = [];
    const zones: HotZone[] = [];

    participants.forEach((_, i) => {
      const cx = colX(i);
      graphicElements.push({
        type: 'line',
        shape: { x1: cx, y1: 0, x2: cx, y2: totalH },
        style: { stroke: LIFELINE_COLOR, lineWidth: 1, lineDash: [5, 5] },
        z: 1,
      });
    });

    entries.forEach((entry, rowIdx) => {
      const srcIdx = participants.indexOf(entry.source);
      const tgtIdx = participants.indexOf(entry.target);
      if (srcIdx === -1 || tgtIdx === -1) return;

      const y = rowIdx * ROW_HEIGHT + ROW_HEIGHT / 2;
      const x1 = colX(srcIdx);
      const x2 = colX(tgtIdx);
      const mx = (x1 + x2) / 2;
      const goRight = tgtIdx > srcIdx;
      const arrowDir = goRight ? 1 : -1;
      const minX = Math.min(x1, x2);
      const maxX = Math.max(x1, x2);

      const isResponse = entry.direction === 'response';
      const isPairHovered = hoveredSpanId !== null && entry.span_id === hoveredSpanId;
      const lineColor = isPairHovered ? HOVER_COLOR : isResponse ? RESPONSE_COLOR : ARROW_COLOR;
      const lineDash = isResponse ? [4, 3] : undefined;

      graphicElements.push({
        type: 'line',
        shape: { x1, y1: y, x2, y2: y },
        style: {
          stroke: lineColor,
          lineWidth: 1.5,
          ...(lineDash ? { lineDash } : {}),
        },
        z: 5,
      });

      graphicElements.push({
        type: 'polygon',
        shape: {
          points: [
            [x2, y],
            [x2 - arrowDir * ARROW_SIZE, y - ARROW_SIZE / 2],
            [x2 - arrowDir * ARROW_SIZE, y + ARROW_SIZE / 2],
          ],
        },
        style: { fill: lineColor },
        z: 6,
      });

      graphicElements.push({
        type: 'text',
        style: {
          x: mx,
          y: y - 10,
          text: entry.type,
          fill: LABEL_COLOR,
          fontSize: 10,
          fontFamily: 'monospace',
          textAlign: 'center',
          textVerticalAlign: 'bottom',
        },
        z: 7,
      });

      const lines = [`[${entry.time}]  ${entry.source} → ${entry.target}`, `type: ${entry.type}`];
      if (entry.detail) lines.push(`detail: ${entry.detail}`);
      zones.push({
        left: minX,
        top: y - HOT_ZONE_H / 2,
        width: maxX - minX,
        height: HOT_ZONE_H,
        content: lines.join('\n'),
        entryIdx: rowIdx,
      });
    });

    setHotZones(zones);

    chart.setOption(
      {
        backgroundColor: BG_COLOR,
        graphic: graphicElements,
        series: [],
        xAxis: { show: false },
        yAxis: { show: false },
        grid: { show: false },
      },
      { replaceMerge: ['graphic'] }
    );

    chart.resize({ width: W, height: totalH });
  }, [entries, hoveredSpanId]);

  useEffect(() => {
    renderChart();
  }, [renderChart]);

  useEffect(() => {
    const scroll = scrollRef.current;
    if (!scroll) return;
    const observer = new ResizeObserver(() => renderChart());
    observer.observe(scroll);
    return () => observer.disconnect();
  }, [renderChart]);

  const colCount = usedParticipants.length;

  return (
    <div style={{ width: '100%', height: '100%', background: BG_COLOR, position: 'relative', display: 'flex', flexDirection: 'row', overflow: 'hidden' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
        <div
          style={{
            flexShrink: 0,
            height: HEADER_HEIGHT,
            background: BG_COLOR,
            borderBottom: '1px solid #e2e8f0',
            display: 'flex',
            zIndex: 20,
            boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
          }}
        >
          {usedParticipants.map((name) => (
            <div
              key={name}
              style={{
                width: colCount > 0 ? `${100 / colCount}%` : undefined,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <div
                style={{
                  padding: '3px 10px',
                  border: '1px solid #93c5fd',
                  borderRadius: 4,
                  fontSize: 11,
                  fontFamily: 'system-ui, sans-serif',
                  color: NODE_TEXT_COLOR,
                  background: '#ffffff',
                  whiteSpace: 'nowrap',
                }}
              >
                {name}
              </div>
            </div>
          ))}
          {usedParticipants.length === 0 && (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <span style={{ fontSize: 12, color: '#94a3b8', fontFamily: 'monospace' }}>等待数据流...</span>
            </div>
          )}
        </div>

        <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', position: 'relative' }}>
          <div ref={canvasRef} style={{ width: '100%' }} />
          <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
            {hotZones.map((zone, i) => {
              const entry = entries[zone.entryIdx];
              return (
                <div
                  key={i}
                  style={{
                    position: 'absolute',
                    left: zone.left,
                    top: zone.top,
                    width: zone.width,
                    height: zone.height,
                    pointerEvents: 'auto',
                    cursor: entry?.span_id ? 'pointer' : 'default',
                  }}
                  onMouseEnter={(e) => {
                    const rect = scrollRef.current!.getBoundingClientRect();
                    const relX = e.clientX - rect.left;
                    const relY = e.clientY - rect.top;
                    const containerH = rect.height;
                    const flipUp = relY + HEADER_HEIGHT + TOOLTIP_H_ESTIMATE + 14 > containerH + HEADER_HEIGHT;
                    const flipLeft = relX + TOOLTIP_W_ESTIMATE + 14 > rect.width;
                    setTooltip({
                      visible: true,
                      x: flipLeft ? relX - TOOLTIP_W_ESTIMATE - 4 : relX + 14,
                      y: relY,
                      content: zone.content,
                      flipUp,
                    });
                    if (entry?.span_id) setHoveredSpanId(entry.span_id);
                  }}
                  onMouseMove={(e) => {
                    const rect = scrollRef.current!.getBoundingClientRect();
                    const relX = e.clientX - rect.left;
                    const relY = e.clientY - rect.top;
                    const containerH = rect.height;
                    const flipUp = relY + HEADER_HEIGHT + TOOLTIP_H_ESTIMATE + 14 > containerH + HEADER_HEIGHT;
                    const flipLeft = relX + TOOLTIP_W_ESTIMATE + 14 > rect.width;
                    setTooltip((prev) => ({
                      ...prev,
                      x: flipLeft ? relX - TOOLTIP_W_ESTIMATE - 4 : relX + 14,
                      y: relY,
                      flipUp,
                    }));
                  }}
                  onMouseLeave={() => {
                    setTooltip((prev) => ({ ...prev, visible: false }));
                    setHoveredSpanId(null);
                  }}
                  onClick={() => {
                    if (!entry?.span_id) return;
                    const info = spanMapState.get(entry.span_id);
                    const reqEntry = info?.reqIdx !== undefined ? entries[info.reqIdx] : entry;
                    const respEntry = info?.respIdx !== undefined ? entries[info.respIdx] : undefined;
                    setSelectedPair({ request: reqEntry, response: respEntry });
                  }}
                />
              );
            })}
          </div>
        </div>

        {tooltip.visible && (
          <div
            style={{
              position: 'absolute',
              left: tooltip.x,
              top: tooltip.flipUp
                ? tooltip.y + HEADER_HEIGHT - TOOLTIP_H_ESTIMATE - 4
                : tooltip.y + HEADER_HEIGHT + 14,
              background: '#ffffff',
              border: '1px solid #93c5fd',
              borderRadius: 4,
              padding: '6px 10px',
              fontSize: 11,
              fontFamily: 'monospace',
              color: '#1e293b',
              whiteSpace: 'pre',
              pointerEvents: 'none',
              zIndex: 100,
              lineHeight: 1.7,
              boxShadow: '0 4px 12px rgba(0,0,0,0.12)',
            }}
          >
            {tooltip.content}
          </div>
        )}
      </div>

      <SpanDetailPanel
        pair={selectedPair}
        onClose={() => setSelectedPair(null)}
      />
    </div>
  );
};
