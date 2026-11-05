import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // The count shows as the formatted text the key interpolates.
    t: (key: string, opts?: { count?: number; formatted?: string }) =>
      opts?.count !== undefined ? `${key}:${opts.formatted}` : key,
  }),
}));

import ActivityNavBadge, { RAIL_STATUS_ID } from './ActivityNavBadge';
import type { NeedsYouItem } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const store = (
  needs: NeedsYouItem[],
  running = 2,
  reconnect: boolean | number = false,
) =>
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
            next_24h: 0,
            failed_24h: 0,
          },
        },
        loading: false,
        error: false,
        live: {},
      }),
      connectors: () => ({
        connections: Array.from({ length: Number(reconnect) }, () => ({
          status: 'reconnect_needed',
        })),
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

  it("counts an agent's API requests as the one row Now lists", () => {
    const s = store([], 1);
    const base = s.getState().activity;
    const withApi = configureStore({
      reducer: {
        activity: () => ({
          ...base,
          now: {
            ...base.now,
            running: [
              ...base.now.running,
              { kind: 'api', id: 'api:a1', title: null, count: 5 },
            ],
          },
        }),
        connectors: () => ({ connections: [] }),
      },
    });
    render(withApi);
    expect(container.textContent).toContain('activity.nav.running:2');
  });

  it('counts each connection to reconnect, as Now does', () => {
    render(store([approval], 0, 3));
    expect(container.textContent).toContain('activity.nav.needsYou:4');
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

  it('gives the rail its counts as a description for the button it sits in', () => {
    // The rail button's aria-label overrides text inside it, so the counts
    // reach a screen reader through aria-describedby.
    act(() =>
      root.render(
        <Provider store={store([approval])}>
          <button aria-label="activity.label" aria-describedby={RAIL_STATUS_ID}>
            <ActivityNavBadge variant="rail" />
          </button>
        </Provider>,
      ),
    );
    const button = container.querySelector('button')!;
    const status = document.getElementById(
      button.getAttribute('aria-describedby')!,
    );
    expect(status?.textContent).toBe(
      'activity.nav.running:2 · activity.nav.needsYou:1',
    );
  });

  it('formats the running count in the app language', () => {
    render(store([], 1234));
    expect(container.textContent).toContain('1,234');
    expect(container.textContent).toContain('activity.nav.running:1,234');
  });

  it('names its counts in a tooltip, not a title', () => {
    render(store([approval]));
    const badge = container.querySelector('[data-slot="tooltip-trigger"]');
    expect(badge).not.toBeNull();
    expect(container.querySelector('[title]')).toBeNull();
  });

  it('renders nothing when there is nothing to say', () => {
    render(store([], 0));
    expect(container.textContent).toBe('');
  });
});
