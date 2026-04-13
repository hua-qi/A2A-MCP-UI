import React, { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts';

const notifySize = (el: HTMLElement | null) => {
  if (!el) return;
  const height = Math.ceil(el.getBoundingClientRect().height);
  if (height > 0) {
    window.parent.postMessage(
      { jsonrpc: '2.0', method: 'ui/notifications/size-changed', params: { height } },
      '*'
    );
  }
};

const EmployeeChartLazy: React.FC = () => {
  const chartRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<{ year: number; count: number }[]>([]);

  useEffect(() => {
    window.parent.postMessage({
      jsonrpc: '2.0',
      id: 1,
      method: 'tools/call',
      params: { name: 'query_employee_trend_lazy', arguments: {} },
    }, '*');
  }, []);

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      const msg = e.data;
      if (!msg || msg.jsonrpc !== '2.0') return;
      if (msg.id === 1 && msg.result) {
        const result = msg.result;
        if (result.data) setData(result.data);
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver(() => notifySize(containerRef.current));
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!chartRef.current || data.length === 0) return;
    const chart = echarts.init(chartRef.current);
    chart.setOption({
      title: { text: '快手员工趋势（懒加载）' },
      xAxis: { type: 'category', data: data.map((d) => String(d.year)) },
      yAxis: { type: 'value' },
      series: [{ type: 'line', data: data.map((d) => d.count), smooth: true }],
    });
    chart.on('finished', () => notifySize(containerRef.current));
    return () => chart.dispose();
  }, [data]);

  if (data.length === 0) {
    return (
      <div ref={containerRef} style={{ padding: 16, color: '#888', minHeight: 48 }}>
        加载中（懒加载）...
      </div>
    );
  }

  return (
    <div ref={containerRef} style={{ padding: 16 }}>
      <div ref={chartRef} style={{ width: 500, height: 300 }} />
    </div>
  );
};

export default EmployeeChartLazy;
