import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  useLoadMore,
  useScrollSentinel,
  type LoadMorePage,
} from './useLoadMore';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// A controllable IntersectionObserver: `reveal()` reports the watched
// sentinel as on screen, `hide()` as off it. Observing a sentinel that is
// currently revealed reports it at once, like the real observer.
let visible = false;
const observers = new Set<FakeObserver>();
class FakeObserver {
  targets = new Set<Element>();
  constructor(private cb: IntersectionObserverCallback) {
    observers.add(this);
  }
  observe(el: Element) {
    this.targets.add(el);
    if (visible) this.fire();
  }
  unobserve(el: Element) {
    this.targets.delete(el);
  }
  disconnect() {
    this.targets.clear();
    observers.delete(this);
  }
  fire() {
    const entries = [...this.targets].map(
      (target) =>
        ({ isIntersecting: visible, target }) as IntersectionObserverEntry,
    );
    if (entries.length)
      this.cb(entries, this as unknown as IntersectionObserver);
  }
}
const reveal = async () => {
  visible = true;
  await act(async () => observers.forEach((o) => o.fire()));
};
const hide = () => {
  visible = false;
};
// On screen for one observer callback, then scrolled away again.
const revealOnce = async () => {
  await act(async () => {
    visible = true;
    observers.forEach((o) => o.fire());
    visible = false;
  });
};

const flush = async () => {
  for (let i = 0; i < 5; i += 1) await act(async () => Promise.resolve());
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  visible = false;
  observers.clear();
  vi.stubGlobal('IntersectionObserver', FakeObserver);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

describe('useScrollSentinel', () => {
  it('calls onReach when the sentinel comes into view, only while enabled', async () => {
    const onReach = vi.fn();
    function Probe({ enabled }: { enabled: boolean }) {
      const ref = useScrollSentinel(onReach, enabled);
      return <div ref={ref} />;
    }
    await act(async () => root.render(<Probe enabled={false} />));
    await reveal();
    expect(onReach).not.toHaveBeenCalled();
    hide();
    await act(async () => root.render(<Probe enabled />));
    await reveal();
    expect(onReach).toHaveBeenCalledTimes(1);
  });
});

describe('useLoadMore', () => {
  type Row = { id: number };
  let state: ReturnType<typeof useLoadMore<Row, number>>;
  const pages: Record<string, Row[][]> = {};
  const load = vi.fn(
    async (
      offset: number | null,
      key: string,
    ): Promise<LoadMorePage<Row, number>> => {
      const all = pages[key].flat();
      const start = offset ?? 0;
      const items = all.slice(start, start + 3);
      return { items, next: start + 3 < all.length ? start + 3 : null };
    },
  );

  function Probe({ resetKey }: { resetKey: string }) {
    state = useLoadMore<Row, number>({
      load: (cursor) => load(cursor, resetKey),
      resetKey,
    });
    return (
      <>
        {state.items.map((r) => (
          <span key={r.id}>{r.id}</span>
        ))}
        <div ref={state.sentinelRef} />
      </>
    );
  }

  const rows = (from: number, n: number) =>
    Array.from({ length: n }, (_, i) => ({ id: from + i }));

  beforeEach(() => {
    load.mockClear();
    pages.a = [rows(0, 7)];
    pages.b = [rows(100, 2)];
  });

  it('loads the first page, then the next when the end comes into view', async () => {
    await act(async () => root.render(<Probe resetKey="a" />));
    await flush();
    expect(state.items.map((r) => r.id)).toEqual([0, 1, 2]);
    expect(state.done).toBe(false);
    await revealOnce();
    await flush();
    expect(state.items.map((r) => r.id)).toEqual([0, 1, 2, 3, 4, 5]);
  });

  // A short first page leaves the sentinel on screen, so loading continues
  // until the box is full or the list ends, without another scroll.
  it('keeps loading while the sentinel stays in view, and stops at the end', async () => {
    visible = true;
    await act(async () => root.render(<Probe resetKey="a" />));
    await flush();
    expect(state.items).toHaveLength(7);
    expect(state.done).toBe(true);
    expect(load).toHaveBeenCalledTimes(3);
  });

  it('a new resetKey starts over and drops a late page from the old one', async () => {
    let release!: () => void;
    await act(async () => root.render(<Probe resetKey="a" />));
    await flush();
    load.mockImplementationOnce(
      (offset, key) =>
        new Promise((resolve) => {
          release = () =>
            resolve({
              items: pages[key].flat().slice(offset ?? 0, 3),
              next: null,
            });
        }),
    );
    await revealOnce();
    await act(async () => root.render(<Probe resetKey="b" />));
    await flush();
    await act(async () => release());
    await flush();
    expect(state.items.map((r) => r.id)).toEqual([100, 101]);
    expect(state.done).toBe(true);
  });

  it('keeps the loaded rows on a failed page, and retry resumes', async () => {
    await act(async () => root.render(<Probe resetKey="a" />));
    await flush();
    load.mockRejectedValueOnce(new Error('boom'));
    await revealOnce();
    await flush();
    expect(state.error).toBe(true);
    expect(state.items).toHaveLength(3);
    await act(async () => state.retry());
    await flush();
    expect(state.error).toBe(false);
    expect(state.items).toHaveLength(6);
  });
});
