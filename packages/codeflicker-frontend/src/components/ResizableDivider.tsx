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
