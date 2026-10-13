import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { count?: number }) =>
      opts?.count !== undefined ? `${key}:${opts.count}` : key,
  }),
}));

import ActivityNavBadge from './ActivityNavBadge';
import type { NeedsYouItem } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const store = (needs: NeedsYouItem[], running = 2, reconnect = false) =>
  configureStore({
    reducer: {
      activity: () => ({
        now: {
          running: Array.from({ length: running }, (_, i) => ({
            kind: 'schedule',
            id: `r${i}`,
            title: null,
          })),
          needs_you: needs,
          up_next: [],
          approval_conversations: [],
          failed_conversations: [],
          stats: {
            running,
            needs_you: needs.length,
            next_24h: 0,
            failed_24h: 0,
          },
        },
        loading: false,
        error: false,
        live: {},
      }),
      connectors: () => ({
        connections: reconnect ? [{ status: 'reconnect_needed' }] : [],
      }),
    },
  });

const approval: NeedsYouItem = {
  kind: 'approval',
  id: 'a',
  conversation_id: 'c',
  title: null,
  tools: [],
};
const paused: NeedsYouItem = {
  kind: 'schedule_paused',
  id: 's',
  schedule_id: 's',
  title: null,
  failures: 3,
};

describe('ActivityNavBadge', () => {
  let container: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });
  const render = (s: ReturnType<typeof store>) =>
    act(() =>
      root.render(
        <Provider store={s}>
          <ActivityNavBadge />
        </Provider>,
      ),
    );
  const dot = () => container.querySelector('span[aria-hidden].rounded-full');

  it('shows the running count without a dot when nothing needs the user', () => {
    render(store([]));
    expect(container.textContent).toContain('2');
    expect(dot()).toBeNull();
  });

  it('shows an amber dot for an approval or a reconnect', () => {
    render(store([approval]));
    expect(dot()?.className).toContain('bg-warning');
    render(store([], 0, true));
    expect(dot()?.className).toContain('bg-warning');
  });

  it('turns the dot red when something failed', () => {
    render(store([approval, paused]));
    expect(dot()?.className).toContain('bg-destructive');
    expect(container.textContent).toContain('activity.nav.needsYou:2');
  });

  it('adds a chat whose answer started since the snapshot, once', () => {
    const s = store([], 1);
    const base = s.getState().activity;
    const withLive = configureStore({
      reducer: {
        activity: () => ({ ...base, live: { c9: true } }),
        connectors: () => ({ connections: [] }),
      },
    });
    render(withLive);
    expect(container.textContent).toContain('2');
  });

  it('renders nothing when there is nothing to say', () => {
    render(store([], 0));
    expect(container.textContent).toBe('');
  });
});
