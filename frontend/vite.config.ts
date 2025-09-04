import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    hmr: { overlay: true },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: false,
        secure: false,
        timeout: 30000,
        proxyTimeout: 30000,
        configure: (proxy) => {
          proxy.on('error', (err, _req, _res) => {
            if ((err as any).code !== 'ECONNRESET') {
              console.warn('[proxy error]', err.message);
            }
          });
        }
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  },
  logLevel: 'info'
});
