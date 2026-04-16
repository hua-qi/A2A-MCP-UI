import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 3000,
    proxy: {
      '/chat-stream': 'http://localhost:3002',
      '/resource-proxy': 'http://localhost:3002',
      '/mode': 'http://localhost:3002',
      '/a2a-tool-call': 'http://localhost:3002',
      '/events': {
        target: 'http://localhost:3001',
        changeOrigin: true,
        ws: false,
      },
    },
  },
});
