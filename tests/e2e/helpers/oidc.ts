/**
 * Spawn/stop the mock OIDC IdP (scripts/e2e/mock_oidc_idp.py) for oidc specs.
 */

import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const MOCK_OIDC_PORT = Number(process.env.MOCK_OIDC_PORT ?? 7999);
export const MOCK_OIDC_ISSUER = `http://127.0.0.1:${MOCK_OIDC_PORT}`;

/**
 * Start the mock IdP as a child process and wait for `/healthz`. The backend
 * must have been booted with `AUTH_TYPE=oidc` (see scripts/e2e/env.sh for the
 * matching OIDC_* defaults). Returns a `stop()` that SIGTERMs the child.
 */
export async function startMockIdp(): Promise<{ stop: () => void }> {
  const repoRoot = path.resolve(
    fileURLToPath(new URL('../../..', import.meta.url)),
  );
  const python =
    process.env.E2E_PYTHON ?? path.join(repoRoot, '.venv', 'bin', 'python');
  const child = spawn(
    python,
    [path.join(repoRoot, 'scripts', 'e2e', 'mock_oidc_idp.py')],
    {
      env: { ...process.env, MOCK_OIDC_PORT: String(MOCK_OIDC_PORT) },
      // stderr passes through so PKCE/code failures show up in test output.
      stdio: ['ignore', 'ignore', 'inherit'],
    },
  );
  const stop = () => {
    if (!child.killed) child.kill('SIGTERM');
  };

  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${MOCK_OIDC_ISSUER}/healthz`);
      if (res.ok) return { stop };
    } catch {
      // not listening yet
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  stop();
  throw new Error(
    `mock OIDC IdP did not become healthy on ${MOCK_OIDC_ISSUER} within 15s`,
  );
}
