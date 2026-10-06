/**
 * Recovery from lazy chunks that a deploy replaced while the tab was open.
 *
 * Built chunk names carry a content hash, so after an upgrade an old tab asks
 * for files that no longer exist. Only a fresh index.html, with the new names,
 * can recover: `React.lazy` caches the rejected import, so re-rendering keeps
 * throwing the same error.
 */

const RELOAD_KEY = 'docsgpt:chunk-reload-at';
const RELOAD_GUARD_MS = 60_000;

const CHUNK_ERROR =
  /dynamically imported module|Importing a module script failed|is not a valid JavaScript MIME type|ChunkLoadError/i;

/**
 * Whether an error is a failed lazy-chunk load, in any browser's wording.
 *
 * Args:
 *   error: what was thrown.
 *
 * Returns:
 *   True for Chrome's "Failed to fetch dynamically imported module", Safari's
 *   MIME type and "Importing a module script failed" errors, Firefox's "error
 *   loading dynamically imported module", and webpack-style ChunkLoadError.
 */
export function isChunkLoadError(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false;
  const { name = '', message = '' } = error as Partial<Error>;
  return CHUNK_ERROR.test(`${name} ${message}`);
}

type ReloadWindow = Pick<EventTarget, 'addEventListener'> & {
  location: Pick<Location, 'reload'>;
};

type ReloadStorage = Pick<Storage, 'getItem' | 'setItem'>;

// Reading `window.sessionStorage` throws where site data is blocked, so it is
// looked up per call, inside the handler's try.
const sessionStore: ReloadStorage = {
  getItem: (key) => window.sessionStorage.getItem(key),
  setItem: (key, value) => window.sessionStorage.setItem(key, value),
};

/**
 * Reload the page once when Vite fails to load a lazy chunk.
 *
 * Vite dispatches `vite:preloadError` when a chunk's preload or its dynamic
 * `import()` fails. The handler reloads to pick up the new index.html, unless
 * it already did so in the last minute: then the chunk is genuinely broken
 * and the error surfaces as usual, so a bad deploy can't loop the page.
 *
 * Args:
 *   win: the window to listen on.
 *   storage: where the last reload time is kept; sessionStorage by default.
 *     Without working storage the handler never reloads, so it can't loop.
 */
export function installChunkReload(
  win: ReloadWindow = window,
  storage: ReloadStorage = sessionStore,
): void {
  win.addEventListener('vite:preloadError', (event) => {
    try {
      const last = Number(storage.getItem(RELOAD_KEY) ?? 0);
      if (Date.now() - last < RELOAD_GUARD_MS) return;
      storage.setItem(RELOAD_KEY, String(Date.now()));
    } catch {
      return;
    }
    event.preventDefault();
    win.location.reload();
  });
}
