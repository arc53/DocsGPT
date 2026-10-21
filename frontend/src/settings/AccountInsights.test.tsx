import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import examples from './insights/fixtures/apiExamples.json';

const store = vi.hoisted(() => ({
  state: { preference: { token: 'token', roles: [] as string[] } },
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) => selector(store.state),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));
vi.mock('./AnalyticsChart', () => ({ default: () => <div /> }));
const gaps = vi.hoisted(() => ({ mounts: 0 }));
vi.mock('./DocsGaps', async () => {
  const { useEffect } = await import('react');
  return {
    default: function DocsGapsStub() {
      useEffect(() => {
        gaps.mounts += 1;
      }, []);
      return null;
    },
  };
});

const insights = vi.hoisted(() => ({ body: {} as object }));
vi.mock('../api/services/userService', () => ({
  default: {
    getConversationInsights: vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve(insights.body) }),
    ),
  },
}));

import userService from '../api/services/userService';
import AccountInsights from './AccountInsights';
import { INSIGHTS_REFRESH_MS } from './insights/useConversationInsights';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('Settings Insights', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async () => {
    await act(async () =>
      root.render(
        <MemoryRouter initialEntries={['/settings/insights']}>
          <Routes>
            <Route path="/settings/insights" element={<AccountInsights />} />
            <Route
              path="/settings/analytics"
              element={<p data-testid="analytics">analytics</p>}
            />
          </Routes>
        </MemoryRouter>,
      ),
    );
    await act(async () => undefined);
  };

  // IN-16: the account's insights as the page, its description and window
  // in PageToolbar's intro and action slots, as on Settings › Analytics.
  it('puts the description and the window in the page toolbar', async () => {
    insights.body = examples.insights;
    await render();
    expect(userService.getConversationInsights).toHaveBeenCalledWith(
      { api_key_id: undefined, filter_option: 'last_30_days' },
      'token',
    );
    const toolbar = container.querySelector('[data-slot="page-toolbar"]')!;
    expect(toolbar.textContent).toContain(
      'settings.analytics.insights.description',
    );
    expect(
      toolbar.querySelector('[data-slot="select-trigger"]'),
    ).not.toBeNull();
    // Said once: the section under it has no intro of its own.
    const section = container.querySelector('[data-testid="insights"]')!;
    expect(section.textContent).not.toContain(
      'settings.analytics.insights.description',
    );
  });

  // FX-5: a deep link while the server has insights off goes to Analytics.
  it('sends a deep link to Settings › Analytics while the server has insights off', async () => {
    insights.body = { ...examples.insights, available: false, enabled: false };
    await render();
    expect(container.querySelector('[data-slot="page-toolbar"]')).toBeNull();
    expect(container.querySelector('[data-testid="insights"]')).toBeNull();
    expect(container.querySelector('[data-testid="analytics"]')).not.toBeNull();
  });

  // IN-20: the description only above figures.
  it('keeps the window but drops the description when there are no figures', async () => {
    insights.body = {
      ...examples.insights,
      coverage: { ...examples.insights.coverage, turns: 0, labelled_turns: 0 },
    };
    await render();
    const toolbar = container.querySelector('[data-slot="page-toolbar"]')!;
    expect(
      toolbar.querySelector('[data-slot="select-trigger"]'),
    ).not.toBeNull();
    expect(toolbar.textContent).not.toContain(
      'settings.analytics.insights.description',
    );
  });

  // While the sweep is still labelling the window the page asks again on
  // its own; the figures and the docs-gap report stay put meanwhile, so the
  // refresh neither flashes the skeleton nor reloads the report.
  it('refreshes partial figures in place, keeping the docs-gap report mounted', async () => {
    vi.useFakeTimers();
    try {
      const partial = (labelled: number, unlabelled: number) => ({
        ...examples.insights,
        coverage: {
          ...examples.insights.coverage,
          turns: labelled + unlabelled,
          labelled_turns: labelled,
          unlabelled_recent_turns: unlabelled,
        },
      });
      vi.mocked(userService.getConversationInsights).mockClear();
      gaps.mounts = 0;
      insights.body = partial(12, 8);
      await render();
      expect(gaps.mounts).toBe(1);

      insights.body = partial(16, 4);
      const section = () => container.querySelector('[data-testid="insights"]');
      const before = section();
      await act(async () => {
        vi.advanceTimersByTime(INSIGHTS_REFRESH_MS);
      });
      expect(userService.getConversationInsights).toHaveBeenCalledTimes(2);
      expect(section()).toBe(before);
      const toolbar = container.querySelector('[data-slot="page-toolbar"]')!;
      expect(toolbar.textContent).toContain(
        'settings.analytics.insights.coverage',
      );
      expect(gaps.mounts).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
