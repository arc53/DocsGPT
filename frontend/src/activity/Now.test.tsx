import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

const activity = vi.hoisted(() => ({ now: vi.fn(), stopMessage: vi.fn() }));
vi.mock('../api/services/activityService', () => ({ default: activity }));
const schedules = vi.hoisted(() => ({ setPaused: vi.fn() }));
vi.mock('../api/services/schedulesService', () => ({ default: schedules }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // Counts and name lists show as the text the key interpolates.
    t: (key: string, opts?: { formatted?: string; tools?: string }) =>
      [key, opts?.formatted, opts?.tools].filter(Boolean).join(':'),
    i18n: { language: 'en' },
  }),
}));

import { TooltipProvider } from '@/components/ui/tooltip';

import {
  sseEventReceived,
  type SSEEvent,
} from '../notifications/notificationsSlice';
import activityReducer, { loadActivityNow } from './activitySlice';
import Now from './Now';
import type { NowSnapshot } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const SNAPSHOT: NowSnapshot = {
  running: [
    {
      kind: 'chat',
      id: 'm1',
      message_id: 'm1',
      title: 'Nordhaven renewal prep',
      conversation_id: 'c1',
      agent_name: 'Support Assistant',
      status: 'streaming',
      started_at: new Date().toISOString(),
    },
    {
      kind: 'webhook',
      id: 'w1',
      title: 'Customer Renewal Desk',
      agent_id: 'a3',
      agent_name: 'Customer Renewal Desk',
      started_at: new Date().toISOString(),
      workflow: true,
      workflow_progress: {
        done: 2,
        total: 5,
        current: { node_id: 'n3', title: 'Draft renewal email', type: 'agent' },
      },
    },
    {
      kind: 'api',
      id: 'api:a5',
      title: 'Support bot',
      agent_id: 'a5',
      agent_name: 'Support bot',
      count: 3,
      started_at: new Date().toISOString(),
    },
    {
      kind: 'workflow',
      id: 'r1',
      title: 'Triage desk',
      agent_id: 'a4',
      started_at: new Date().toISOString(),
      workflow_progress: {
        done: 1,
        total: null,
        current: { node_id: 'n2', title: 'Classify', type: 'agent' },
      },
    },
    {
      kind: 'ingest',
      id: 's1',
      source_id: 's1',
      title: 'Carrier handbook 2026.pdf',
      operation: 'sync',
      stage: 'embedding',
      progress: 0.28,
      embedded_chunks: 34,
      total_chunks: 120,
    },
    {
      kind: 'ingest',
      id: 's2',
      source_id: 's2',
      title: 'Rate cards Q4',
      operation: 'upload',
      stage: 'reading',
      progress: null,
      started_at: new Date(Date.now() - 95_000).toISOString(),
    },
  ],
  needs_you: [
    {
      kind: 'approval',
      id: 'approval:c2',
      conversation_id: 'c2',
      title: 'Vendor Renewal Decision',
      tools: ['send_email', 'http_request'],
      expires_at: new Date(Date.now() + 20 * 60_000).toISOString(),
    },
    {
      kind: 'schedule_paused',
      id: 'schedule:x1',
      schedule_id: 'x1',
      title: 'Prospect news scan',
      agent_id: 'a1',
      failures: 3,
    },
  ],
  up_next: [
    {
      kind: 'schedule',
      id: 'schedule:x2',
      schedule_id: 'x2',
      name: 'Daily support digest',
      agent_id: 'a2',
      agent_name: 'Support Assistant',
      trigger_type: 'recurring',
      next_run_at: new Date(Date.now() + 3_600_000).toISOString(),
      runs_in_window: 1,
    },
    {
      kind: 'sync',
      id: 'sync:daily',
      frequency: 'daily',
      next_run_at: new Date(Date.now() + 2 * 3_600_000).toISOString(),
      sources: ['Carrier portal', 'Rate cards'],
      blocked: ['Shared drive'],
      runs_in_window: 1,
    },
  ],
  approval_conversations: ['c2'],
  failed_conversations: [],
  stats: { next_24h: 1, failed_24h: 1 },
};

const makeStore = (snapshot: NowSnapshot = SNAPSHOT) => {
  const store = configureStore({
    reducer: {
      activity: activityReducer,
      preference: () => ({ token: 'tok' }),
      connectors: () => ({
        connections: [
          {
            id: 'k1',
            name: 'google_drive',
            display_name: 'Google Drive',
            account_label: 'lena@example.com',
            status: 'reconnect_needed',
          },
        ],
      }),
      monitors: () => ({ order: [], byId: {}, loading: false }),
      schedules: (state = {}) => state,
    },
  });
  store.dispatch(loadActivityNow.fulfilled(snapshot, 'req'));
  return store;
};

describe('Now page', () => {
  let container: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    activity.stopMessage.mockReset().mockResolvedValue(undefined);
    activity.now.mockReset().mockResolvedValue(SNAPSHOT);
    schedules.setPaused.mockReset().mockResolvedValue({
      schedule: { id: 'x1', agent_id: 'a1', status: 'active' },
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async (snapshot?: NowSnapshot) => {
    await act(async () => {
      root.render(
        <Provider store={makeStore(snapshot)}>
          <TooltipProvider>
            <MemoryRouter>
              <Now />
            </MemoryRouter>
          </TooltipProvider>
        </Provider>,
      );
    });
  };
  const button = (label: string) =>
    Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === label,
    ) as HTMLButtonElement;

  it('lists what needs the user, connections to reconnect included', async () => {
    await render();
    expect(container.textContent).toContain('activity.now.needsYou');
    expect(container.textContent).toContain('activity.now.approve');
    expect(container.textContent).toContain('activity.now.pausedAfter:3');
    expect(container.textContent).toContain(
      'activity.now.approve:send_email and http_request',
    );
    expect(container.textContent).toContain('activity.now.reconnect');
  });

  it('counts what runs as the sidebar does, a chat just started included', async () => {
    const store = makeStore();
    await act(async () => {
      root.render(
        <Provider store={store}>
          <TooltipProvider>
            <MemoryRouter>
              <Now />
            </MemoryRouter>
          </TooltipProvider>
        </Provider>,
      );
    });
    const heading = (title: string) =>
      Array.from(container.querySelectorAll('h2, h3'))
        .find((h) => h.textContent?.startsWith(title))
        ?.querySelector('[data-slot="count"]')?.textContent;
    const stat = (label: string) =>
      Array.from(container.querySelectorAll('p')).find(
        (p) => p.textContent === label,
      )?.parentElement?.textContent;
    const rows = SNAPSHOT.running.length;
    // The card, the heading and the rows agree: an API row is one.
    expect(stat('activity.now.stats.running')).toContain(String(rows));
    expect(heading('activity.now.runningTitle')).toContain(String(rows));
    await act(async () => {
      store.dispatch(
        sseEventReceived({
          id: 'e',
          type: 'message.started',
          payload: { conversation_id: 'c9' },
        } as SSEEvent),
      );
    });
    expect(stat('activity.now.stats.running')).toContain(String(rows + 1));
  });

  it('links the failed tile to History only when something failed', async () => {
    const link = () =>
      Array.from(container.querySelectorAll('p'))
        .find((p) => p.textContent === 'activity.now.stats.failed')
        ?.parentElement?.querySelector('a');
    await render();
    expect(link()?.getAttribute('href')).toBe('/activity/history');
    expect(link()?.textContent).toBe('activity.now.stats.viewInHistory');
    await render({ ...SNAPSHOT, stats: { next_24h: 1, failed_24h: 0 } });
    expect(link()).toBeNull();
  });

  it('lists running work and what runs next', async () => {
    await render();
    expect(container.textContent).toContain('Nordhaven renewal prep');
    expect(container.textContent).toContain('Carrier handbook 2026.pdf');
    expect(container.textContent).toContain('Daily support digest');
  });

  it('shows the step a workflow run is on', async () => {
    await render();
    const row = (kind: string) =>
      container.querySelector(`li[data-kind="${kind}"]`) as HTMLElement;
    expect(row('webhook').textContent).toContain('activity.now.stepOf');
    expect(row('webhook').textContent).toContain('Draft renewal email');
    expect(row('webhook').querySelector('[role="progressbar"]')).not.toBeNull();
    // A branching workflow has no step count, so no bar.
    expect(row('workflow').textContent).toContain('activity.now.step');
    expect(row('workflow').textContent).toContain('Classify');
    expect(row('workflow').querySelector('[role="progressbar"]')).toBeNull();
  });

  it("sums up an agent's API requests in one row that opens its logs", async () => {
    await render();
    const row = container.querySelector('li[data-kind="api"]') as HTMLElement;
    expect(row.textContent).toContain('Support bot');
    expect(row.textContent).toContain('activity.now.apiRequests:3');
    expect(
      Array.from(row.querySelectorAll('button')).some(
        (b) => b.textContent === 'activity.now.open',
      ),
    ).toBe(true);
    // No Stop: the caller holds the request.
    expect(row.textContent).not.toContain('activity.now.stop');
  });

  it('says what an ingest is doing and how long it has run', async () => {
    await render();
    const [embedding, reading] = Array.from(
      container.querySelectorAll('li[data-kind="ingest"]'),
    ) as HTMLElement[];
    expect(embedding.textContent).toContain('activity.now.operation.sync');
    expect(embedding.textContent).toContain('activity.now.chunks');
    expect(reading.textContent).toContain('activity.now.operation.upload');
    expect(reading.textContent).toContain('activity.now.reading');
    expect(reading.textContent).toContain('1:35');
    expect(reading.querySelector('[role="progressbar"]')).toBeNull();
  });

  it('lists a knowledge sync batch in Up next', async () => {
    await render();
    const row = Array.from(container.querySelectorAll('li')).find((li) =>
      li.textContent?.includes('activity.now.syncBatch.daily'),
    ) as HTMLElement;
    expect(row).toBeDefined();
    expect(row.textContent).toContain('activity.now.syncSources:2');
    expect(row.textContent).toContain('Carrier portal and Rate cards');
    expect(row.textContent).toContain('activity.now.syncBlocked:1');
    expect(row.querySelector('a')?.getAttribute('href')).toBe(
      '/settings/knowledge',
    );
  });

  it('stops a running answer', async () => {
    await render();
    await act(async () => button('activity.now.stop').click());
    expect(activity.stopMessage).toHaveBeenCalledWith('m1', 'tok');
  });

  it('resumes a schedule paused after failures', async () => {
    await render();
    await act(async () => button('agents.schedules.resume').click());
    expect(schedules.setPaused).toHaveBeenCalledWith('x1', 'resume', 'tok');
  });

  it('filters the running list by kind', async () => {
    await render();
    const knowledge = Array.from(
      container.querySelectorAll('[role="radio"]'),
    ).find(
      (b) => b.textContent === 'activity.now.filters.knowledge',
    ) as HTMLElement;
    await act(async () => knowledge.click());
    const kinds = Array.from(container.querySelectorAll('li[data-kind]')).map(
      (li) => li.getAttribute('data-kind'),
    );
    expect(kinds).toEqual(['ingest', 'ingest']);
  });
});
