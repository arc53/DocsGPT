import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => {
      if (!options) return key;
      const values = Object.entries(options)
        .filter(([name]) => name !== 'interpolation')
        .map(([name, value]) => `${name}=${value}`)
        .join(',');
      return `${key}(${values})`;
    },
    i18n: { language: 'en' },
  }),
}));

vi.mock('../api/services/payerService', () => ({
  default: { getQuota: vi.fn() },
}));

import payerService, {
  type QuotaBucket,
  type QuotaResponse,
} from '../api/services/payerService';
import UsageNotice, { useUsageStop } from './UsageNotice';
import reducer, { connectUsage, createUsageListener } from './usageSlice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const getQuota = vi.mocked(payerService.getQuota);
const RESET = '2026-12-01T00:00:00+00:00';

const bucket = (name: string, used: number, limit = 100): QuotaBucket => ({
  bucket: name,
  tokens: { limit: null, used: 0 },
  cost: { limit, used },
  resets_at: RESET,
});

const quota = (over: Partial<QuotaResponse> = {}): QuotaResponse => ({
  period: 'month',
  buckets: [bucket('all', 10)],
  notice: null,
  parts: null,
  paused: null,
  ...over,
});

let container: HTMLDivElement;
let root: Root;
let listener: ReturnType<typeof createUsageListener>;

beforeEach(() => {
  getQuota.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  listener?.clearListeners();
  connectUsage(null);
});

function Stop({ scope }: { scope: 'direct' | 'agent' }) {
  return <span data-testid="stop">{String(useUsageStop(scope))}</span>;
}

const render = async (
  answer: QuotaResponse,
  scope: 'direct' | 'agent' = 'direct',
) => {
  getQuota.mockResolvedValue(answer);
  listener = createUsageListener();
  const store = configureStore({
    reducer: {
      usage: reducer,
      preference: (state: { token: string | null } = { token: 'tok' }) => state,
    },
    middleware: (getDefault) => getDefault().concat(listener.middleware),
  });
  await act(async () => {
    root.render(
      <Provider store={store}>
        <MemoryRouter>
          <UsageNotice scope={scope} />
          <Stop scope={scope} />
        </MemoryRouter>
      </Provider>,
    );
  });
  return container;
};

const stop = () => container.querySelector('[data-testid="stop"]')?.textContent;

describe('UsageNotice', () => {
  it('loads the quota and shows nothing under 80%', async () => {
    await render(quota());
    expect(getQuota).toHaveBeenCalledWith('tok');
    expect(container.textContent).toBe('false');
  });

  it('shows the near line with the reset date in the reader’s language', async () => {
    await render(quota({ buckets: [bucket('all', 82)] }));
    const line = container.querySelector('[data-testid="usage-near"]');
    expect(line?.textContent).toBe(
      'payer.notice.near.month(percent=82,month=November,date=1 Dec)',
    );
    expect(line?.getAttribute('role')).toBe('status');
    expect(stop()).toBe('false');
  });

  it('shows the stop with what else paused, and stops sending', async () => {
    await render(
      quota({
        buckets: [bucket('all', 100)],
        paused: {
          schedules: 2,
          published: [
            {
              agent_id: 'a1',
              name: 'Tender helper',
              access: ['api_key', 'public_link'],
            },
          ],
        },
      }),
    );
    const card = container.querySelector('[data-testid="usage-reached"]');
    const text = card?.textContent ?? '';
    expect(text).toContain('payer.notice.reached.title.month(month=November)');
    expect(text).toContain('payer.notice.reached.covers.all');
    expect(text).toContain('payer.notice.resets.date(date=1 Dec)');
    expect(text).toContain('payer.notice.reached.schedules(count=2)');
    expect(text).toContain(
      // The publisher pays only for link visitors who aren't signed in, so the link stops only for them.
      'payer.notice.reached.published(name=Tender helper,access=payer.common.access.apiKey and payer.notice.reached.publicLinkSignedOut)',
    );
    const link = card?.querySelector('a');
    expect(link?.getAttribute('href')).toBe('/settings/analytics');
    expect(stop()).toBe('true');
  });

  it('leaves out paused lines when nothing else stopped', async () => {
    await render(quota({ buckets: [bucket('all', 120)] }));
    const text =
      container.querySelector('[data-testid="usage-reached"]')?.textContent ??
      '';
    expect(text).not.toContain('reached.schedules');
    expect(text).not.toContain('reached.published');
  });

  it('does not stop a chat without an agent for a used-up agent allowance', async () => {
    const answer = quota({
      buckets: [bucket('all', 10), bucket('agent', 100)],
    });
    await render(answer, 'direct');
    expect(container.querySelector('[data-testid="usage-reached"]')).toBe(null);
    expect(stop()).toBe('false');
    // A fresh page for the other chat.
    act(() => root.unmount());
    root = createRoot(container);
    await render(answer, 'agent');
    expect(
      container.querySelector('[data-testid="usage-reached"]')?.textContent,
    ).toContain('payer.notice.reached.covers.agent');
    expect(stop()).toBe('true');
  });
});
