import { defineConfig } from 'vitest/config';
import { loadEnv, type ProxyOptions } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const target = loadEnv(mode, '.', 'AUDIOMASK_').AUDIOMASK_BACKEND_URL || 'http://127.0.0.1:8000';
  const apiProxy: ProxyOptions = {
    target,
    configure(proxy) {
      proxy.on('proxyReq', (upstream, request, response) => {
        if (!request.url?.startsWith('/api/quality/')) return;
        const disconnect = () => {
          if (!response.writableFinished) upstream.destroy();
        };
        if (response.destroyed) disconnect();
        else response.once('close', disconnect);
      });
    },
  };
  return {
    plugins: [react()],
    server: { proxy: { '/api': apiProxy } },
    preview: { proxy: { '/api': apiProxy } },
    test: {
      include: ['src/**/*.test.{ts,tsx}'],
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      clearMocks: true,
    },
  };
});
