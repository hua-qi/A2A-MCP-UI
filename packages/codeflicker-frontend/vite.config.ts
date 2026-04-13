import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/chat': 'http://localhost:3002',
      '/resource-proxy': 'http://localhost:3002',
      '/mode': 'http://localhost:3002',
      '/tool-call': 'http://localhost:3002',
      '/tool-result': 'http://localhost:3002',
    },
  },
});
