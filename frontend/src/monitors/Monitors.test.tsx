import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

const service = vi.hoisted(() => ({ list: vi.fn(), act: vi.fn() }));
vi.mock('@/api/services/monitorsService', () => ({ default: service }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) =>
      values?.interval ? `${key}:${values.interval}` : key,
  }),
}));

import { TooltipProvider } from '@/components/ui/tooltip';

import Monitors from './Monitors';
import reducer from './monitorsSlice';
import { sampleMonitor } from './testing';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const makeStore = () =>
  configureStore({
    reducer: { monitors: reducer, preference: () => ({ token: 'tok' }) },
  });

describe('Monitors page', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    service.list.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async () => {
    await act(async () => {
      root.render(
        <Provider store={makeStore()}>
          <TooltipProvider>
            <MemoryRouter>
              <Monitors />
            </MemoryRouter>
          </TooltipProvider>
        </Provider>,
      );
    });
    await act(async () => {
      await Promise.resolve();
    });
  };

  it('lists what is watched, how often, wakes left, live ones first', async () => {
    service.list.mockResolvedValue([
      sampleMonitor({
        monitor_id: 'done',
        description: 'Old one',
        status: 'completed',
      }),
      sampleMonitor({
        monitor_id: 'hook',
        description: 'CI finished',
        source_type: 'webhook',
        interval: null,
        target: null,
        status: 'paused',
        paused_reason: 'paused by the user',
      }),
      sampleMonitor(),
    ]);
    await render();
    expect(service.list).toHaveBeenCalledWith('tok');
    const rows = Array.from(container.querySelectorAll('tbody tr'));
    expect(rows.map((r) => r.getAttribute('data-status'))).toEqual([
      'paused',
      'active',
      'completed',
    ]);
    const text = container.textContent ?? '';
    expect(text).toContain('ACMEB below $90');
    expect(text).toContain('monitors.every:15m');
    expect(text).toContain('monitors.onEvent');
    expect(text).toContain('monitors.source.webhook');
    expect(text).toContain('https://shop.example.com');
    expect(text).toContain('1 / 1');
    expect(text).toContain('monitors.pausedBecause');
  });

  it('says why a monitor ended, and shows a problem only when there is one', async () => {
    service.list.mockResolvedValue([
      sampleMonitor({
        monitor_id: 'decided',
        status: 'completed',
        paused_reason: 'decided',
        last_error: null,
      }),
      sampleMonitor({
        monitor_id: 'odd',
        status: 'cancelled',
        paused_reason: 'something new',
        last_error: null,
      }),
      sampleMonitor({ monitor_id: 'broken', last_error: 'HTTP 404' }),
    ]);
    await render();
    const lines = Array.from(
      container.querySelectorAll('tbody [data-testid="monitor-status-line"]'),
    ).map((p) => p.textContent);
    expect(lines).toEqual([
      'monitors.finished.decided',
      'monitors.endedBecause',
    ]);
    const errors = container.querySelectorAll(
      'tbody [data-testid="monitor-last-error"]',
    );
    expect(errors).toHaveLength(1);
  });

  it("shows the expiry in the reader's locale with its time zone", async () => {
    service.list.mockResolvedValue([
      sampleMonitor({ expires_at: '2026-10-20T09:44:00Z' }),
    ]);
    await render();
    const expected = new Intl.DateTimeFormat(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      timeZoneName: 'short',
    }).format(new Date('2026-10-20T09:44:00Z'));
    expect(container.querySelector('tbody')?.textContent).toContain(expected);
  });

  it('shows the empty state', async () => {
    service.list.mockResolvedValue([]);
    await render();
    expect(container.textContent).toContain('monitors.empty');
  });

  it('shows a retry when loading fails', async () => {
    service.list.mockRejectedValue(new Error('down'));
    await render();
    expect(container.textContent).toContain('monitors.loadError');
    service.list.mockResolvedValue([sampleMonitor()]);
    const retry = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    );
    await act(async () => retry?.click());
    expect(service.list).toHaveBeenCalledTimes(2);
  });
});
