import React, { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts';

export interface EmployeeChartProps {
  data?: { year: number; count: number }[];
  token?: string;
  sgAgentBaseUrl?: string;
}

const EmployeeChart: React.FC<EmployeeChartProps> = ({
  data: initialData,
  token: initialToken,
  sgAgentBaseUrl = 'http://localhost:3001',
}) => {
  const chartRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<{ year: number; count: number }[]>(initialData ?? []);
  const [token, setToken] = useState<string>(initialToken ?? '');
  const [detail, setDetail] = useState<{ year: number; count: number; note: string } | null>(null);

  const refreshIdRef = useRef<number | null>(null);

  useEffect(() => {
    const handleMessage = (e: MessageEvent) => {
      const msg = e.data;
      if (!msg || msg.jsonrpc !== '2.0') return;
      if (msg.method === 'ui/notifications/tool-result') {
        const result = msg.params?.result ?? msg.params ?? {};
        if (result.data) setData(result.data);
        if (result.token) setToken(result.token);
      }
      if (refreshIdRef.current !== null && msg.id === refreshIdRef.current && msg.result) {
        const result = msg.result;
        if (result.data) setData(result.data);
        if (result.token) setToken(result.token);
        refreshIdRef.current = null;
      }
    };
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  const notifySize = () => {
    if (!containerRef.current) return;
    const height = Math.ceil(containerRef.current.getBoundingClientRect().height);
    if (height > 0) {
      window.parent.postMessage(
        { jsonrpc: '2.0', method: 'ui/notifications/size-changed', params: { height } },
        '*'
      );
    }
  };

  useEffect(() => {
    if (!chartRef.current || data.length === 0) return;
    const chart = echarts.init(chartRef.current);
    chart.setOption({
      title: { text: '快手员工趋势' },
      xAxis: { type: 'category', data: data.map((d) => String(d.year)) },
      yAxis: { type: 'value' },
      series: [{ type: 'line', data: data.map((d) => d.count), smooth: true }],
    });
    chart.on('finished', notifySize);
    return () => chart.dispose();
  }, [data]);

  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver(notifySize);
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  const handleAnalyze = () => {
    window.parent.postMessage({
      jsonrpc: '2.0',
      id: Date.now(),
      method: 'ui/message',
      params: {
        role: 'user',
        content: [{ type: 'text', text: `分析以下员工趋势数据：${JSON.stringify(data)}` }],
      },
    }, '*');
  };

  const handleRefresh = () => {
    const id = Date.now();
    refreshIdRef.current = id;
    window.parent.postMessage({
      jsonrpc: '2.0',
      id,
      method: 'tools/call',
      params: {
        name: 'query_employee_trend',
        arguments: {},
      },
    }, '*');
  };

  const handleHoverYear = async (year: number) => {
    if (!token) return;
    const res = await fetch(`${sgAgentBaseUrl}/api/employee/detail/${year}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const d = await res.json();
    setDetail(d);
  };

  if (data.length === 0) {
    return (
      <div ref={containerRef} style={{ padding: 16, color: '#888' }}>
        加载中...
      </div>
    );
  }

  return (
    <div ref={containerRef} style={{ padding: 16 }}>
      <div ref={chartRef} style={{ width: 500, height: 300 }} />
      {detail && (
        <div style={{ margin: '8px 0', padding: '8px 12px', background: '#f5f5f5', borderRadius: 6, fontSize: 13 }}>
          <strong>{detail.year} 年</strong>：{detail.count.toLocaleString()} 人 — {detail.note}
          <button onClick={() => setDetail(null)} style={{ marginLeft: 8, cursor: 'pointer', border: 'none', background: 'none', color: '#999' }}>×</button>
        </div>
      )}
      <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button onClick={handleAnalyze}>分析趋势</button>
        <button onClick={handleRefresh}>刷新数据</button>
        {data.map((d) => (
          <button key={d.year} onClick={() => handleHoverYear(d.year)}>
            {d.year} 详情
          </button>
        ))}
      </div>
    </div>
  );
};

export default EmployeeChart;
