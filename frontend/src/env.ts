/**
 * Runtime-overridable build settings.
 *
 * Vite inlines `import.meta.env.VITE_*` at build time, which forced the
 * Docker image to run the dev server so `VITE_API_HOST` could change per
 * deployment. The production image serves a static build instead and writes
 * the container's `VITE_*` environment into `window.__DOCSGPT_ENV__` (see
 * frontend/docker/40-runtime-env.sh). That object wins over the build-time
 * value; outside Docker nothing sets it and the build-time value applies.
 */

declare global {
  interface Window {
    __DOCSGPT_ENV__?: Record<string, string | undefined>;
  }
}

export function envVar(name: string): string {
  const runtime =
    typeof window !== 'undefined' ? window.__DOCSGPT_ENV__?.[name] : undefined;
  if (runtime !== undefined && runtime !== '') return runtime;
  const buildTime = (import.meta.env as Record<string, unknown>)[name];
  return typeof buildTime === 'string' ? buildTime : '';
}
