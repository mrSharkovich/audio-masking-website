import { defineConfig } from 'vitest/config';
import { loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const target = loadEnv(mode, '.', 'AUDIOMASK_').AUDIOMASK_BACKEND_URL || 'http://127.0.0.1:8000';
  return {
    plugins: [react()],
    server: { proxy: { '/api': { target } } },
    preview: { proxy: { '/api': { target } } },
    test: {
      include: ['src/**/*.test.{ts,tsx}'],
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      clearMocks: true,
    },
  };
});
