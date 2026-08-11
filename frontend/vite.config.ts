/// <reference types="vitest" />
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import svgr from 'vite-plugin-svgr';
import path from 'path';

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    plugins: [react(), svgr()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      // Extra dev hosts (e.g. a tailscale name) come from VITE_ALLOWED_HOSTS in
      // an untracked .env.local; machine-specific names stay out of the repo.
      allowedHosts: env.VITE_ALLOWED_HOSTS
        ? env.VITE_ALLOWED_HOSTS.split(',')
            .map((h) => h.trim())
            .filter(Boolean)
        : [],
      // Use polling for file watching when running inside Docker.
      // Native fs events do not propagate from Windows hosts into Linux
      // containers, so Chokidar falls back to polling which works reliably.
      watch: env.DOCKER
        ? { usePolling: true, interval: 300 }
        : undefined,
    },
    test: {
      environment: 'happy-dom',
      globals: true,
      include: ['src/**/*.test.{ts,tsx}'],
      setupFiles: ['./vitest.setup.ts'],
    },
  };
});
