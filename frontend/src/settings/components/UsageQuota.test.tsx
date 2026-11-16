import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

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

vi.mock('../../api/services/payerService', () => ({
  default: { getQuota: vi.fn() },
}));

import payerService, {
  type QuotaResponse,
} from '../../api/services/payerService';
import reducer from '../../payer/usageSlice';
import UsageQuota from './UsageQuota';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const getQuota = vi.mocked(payerService.getQuota);
const RESET = '2026-12-01T00:00:00+00:00';

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  getQuota.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const render = async (answer: QuotaResponse) => {
  getQuota.mockResolvedValue(answer);
  const store = configureStore({
    reducer: {
      usage: reducer,
      preference: (state: { token: string | null } = { token: 'tok' }) => state,
    },
  });
  await act(async () => {
    root.render(
      <Provider store={store}>
        <UsageQuota />
      </Provider>,
    );
  });
};

const limited = (over: Partial<QuotaResponse> = {}): QuotaResponse => ({
  period: 'month',
  buckets: [
    {
      bucket: 'all',
      tokens: { limit: null, used: 900_000 },
      cost: { limit: 300, used: 164 },
      resets_at: RESET,
    },
  ],
  notice: null,
  parts: [
    { kind: 'chat', tokens: 1000, cost: 48.2 },
    { kind: 'schedule', tokens: 2000, cost: 82.4 },
    { kind: 'published', tokens: 500, cost: 33.4 },
    { kind: 'other', tokens: 10, cost: 0.5 },
  ],
  paused: null,
  ...over,
});

describe('UsageQuota', () => {
  it('reads the quota fresh when the page opens', async () => {
    await render(limited());
    expect(getQuota).toHaveBeenCalledWith('tok');
  });

  it('shows one meter for the allowance, with its parts and Other', async () => {
    await render(limited());
    const text = container.textContent ?? '';
    expect(text).toContain(
      'settings.analytics.quota.titleMonth(month=November)',
    );
    expect(text).toContain('settings.analytics.quota.resetsOn(date=1 Dec)');
    expect(text).toContain('settings.analytics.quota.allowance');
    expect(text).toContain('settings.analytics.quota.scope.all');
    expect(text).toContain(
      'settings.analytics.quota.usedOf(used=$164.00,limit=$300.00)',
    );
    expect(container.querySelectorAll('[role="progressbar"]')).toHaveLength(1);
    const parts = [
      ...container.querySelectorAll('[data-testid="usage-part"]'),
    ].map((row) => row.textContent);
    expect(parts).toEqual([
      expect.stringContaining('$48.20'),
      expect.stringContaining('$82.40'),
      expect.stringContaining('$33.40'),
      expect.stringContaining('$0.50'),
    ]);
    expect(parts[0]).toContain('settings.analytics.quota.parts.chat');
    expect(parts[1]).toContain('settings.analytics.quota.parts.schedule');
    expect(parts[2]).toContain('settings.analytics.quota.parts.published');
    expect(parts[3]).toContain('settings.analytics.quota.parts.other');
  });

  it('leaves Other out when nothing counts toward it', async () => {
    const answer = limited();
    answer.parts![3] = { kind: 'other', tokens: 0, cost: 0 };
    await render(answer);
    expect(
      container.querySelectorAll('[data-testid="usage-part"]'),
    ).toHaveLength(3);
  });

  it('counts in tokens when the limit is in tokens', async () => {
    await render(
      limited({
        buckets: [
          {
            bucket: 'direct',
            tokens: { limit: 2_000_000, used: 1_500_000 },
            cost: { limit: null, used: 3 },
            resets_at: RESET,
          },
        ],
      }),
    );
    const text = container.textContent ?? '';
    expect(text).toContain('settings.analytics.quota.scope.direct');
    expect(text).toContain(
      'settings.analytics.quota.usedOf(used=1,500,000,limit=2,000,000)',
    );
    expect(text).toContain('1,000');
  });

  it('is hidden for an unlimited person', async () => {
    await render(limited({ buckets: [], parts: null }));
    expect(container.innerHTML).toBe('');
  });
});
