import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: { environment: 'happy-dom', include: ['tests/**/*.test.{ts,tsx}'] },
});
