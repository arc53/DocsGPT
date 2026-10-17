import { describe, expect, it, vi } from 'vitest';

import { installChunkReload, isChunkLoadError } from './chunkReload';

describe('isChunkLoadError', () => {
  it('recognises each browser message for a missing lazy chunk', () => {
    // Chrome
    expect(
      isChunkLoadError(
        new TypeError(
          'Failed to fetch dynamically imported module: https://x/assets/a-1.js',
        ),
      ),
    ).toBe(true);
    // Safari, when the server answers the old chunk URL with index.html
    expect(
      isChunkLoadError(
        new TypeError("'text/html' is not a valid JavaScript MIME type."),
      ),
    ).toBe(true);
    expect(
      isChunkLoadError(new TypeError('Importing a module script failed.')),
    ).toBe(true);
    // Firefox
    expect(
      isChunkLoadError(
        new TypeError('error loading dynamically imported module'),
      ),
    ).toBe(true);
  });

  it('leaves other errors alone', () => {
    expect(isChunkLoadError(new Error('render exploded'))).toBe(false);
    expect(isChunkLoadError(new TypeError('x is undefined'))).toBe(false);
    expect(isChunkLoadError(null)).toBe(false);
    expect(isChunkLoadError('Failed to fetch')).toBe(false);
  });
});

describe('installChunkReload', () => {
  const setup = () => {
    const target = new EventTarget();
    const reload = vi.fn();
    const win = Object.assign(target, { location: { reload } });
    const store = new Map<string, string>();
    const storage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
    };
    installChunkReload(win, storage);
    const fire = () => {
      const event = new Event('vite:preloadError', { cancelable: true });
      win.dispatchEvent(event);
      return event;
    };
    return { reload, fire, storage };
  };

  it('reloads once when a chunk fails to load', () => {
    const { reload, fire } = setup();
    fire();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('never cancels the event, so the original chunk error still throws', () => {
    // preventDefault() makes Vite resolve the import to undefined, which
    // React.lazy turns into a different, unrecognisable error until the
    // reload lands.
    const { fire } = setup();
    expect(fire().defaultPrevented).toBe(false);
  });

  it('lets the error surface on a second failure within a minute', () => {
    const { reload, fire } = setup();
    fire();
    const again = fire();
    expect(again.defaultPrevented).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('reloads again once the minute has passed', () => {
    const { reload, fire, storage } = setup();
    storage.setItem('docsgpt:chunk-reload-at', String(Date.now() - 61_000));
    fire();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('does not reload without working storage', () => {
    const target = new EventTarget();
    const reload = vi.fn();
    installChunkReload(Object.assign(target, { location: { reload } }), {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
    });
    const event = new Event('vite:preloadError', { cancelable: true });
    target.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });
});
