import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

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
vi.mock('./DocsGaps', () => ({ default: () => null }));
vi.mock('./components/UsageQuota', () => ({ default: () => null }));

const insights = vi.hoisted(() => ({ body: {} as object }));
vi.mock('../api/services/userService', () => {
  const empty = () =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  return {
    default: {
      getMessageAnalytics: vi.fn(empty),
      getFeedbackAnalytics: vi.fn(empty),
      getTokenAnalytics: empty,
      getToolAnalytics: empty,
      getScheduleAnalytics: empty,
      getConversationInsights: vi.fn(() =>
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve(insights.body),
        }),
      ),
    },
  };
});

import userService from '../api/services/userService';
import Analytics from './Analytics';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('Analytics without insights', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    store.state.preference.roles = [];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (agentId?: string) => {
    await act(async () =>
      root.render(
        <MemoryRouter>
          <Analytics agentId={agentId} filterOption="last_7_days" />
        </MemoryRouter>,
      ),
    );
    await act(async () => undefined);
  };

  const feedbackRow = () =>
    Array.from(container.querySelectorAll('h2'))
      .find((h) => h.textContent === 'settings.analytics.userFeedback')!
      .closest('[data-slot="card"]')!.parentElement!;

  // Settings › Insights is its own page now.
  it("leaves the account's insights to their own page", async () => {
    vi.mocked(userService.getConversationInsights).mockClear();
    insights.body = examples.insights;
    await render();
    expect(userService.getConversationInsights).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="insights"]')).toBeNull();
    // The thumbs keep the full width with nothing beside them.
    expect(feedbackRow().className).not.toContain('xl:flex-row');
  });

  // IN-16: the page puts the window select in its toolbar; the charts read
  // the window they are given and draw no select, subtitle or quota.
  it('charts the window it is given, with no select or subtitle of its own', async () => {
    vi.mocked(userService.getMessageAnalytics).mockClear();
    await render('a1');
    expect(userService.getMessageAnalytics).toHaveBeenCalledWith(
      { api_key_id: 'a1', filter_option: 'last_7_days' },
      'token',
    );
    expect(container.textContent).not.toContain('settings.analytics.subtitle');
    expect(container.textContent).not.toContain(
      'settings.analytics.filterOptions',
    );
  });

  it("leaves an agent's insights to its own page", async () => {
    vi.mocked(userService.getConversationInsights).mockClear();
    insights.body = examples.insights;
    await render('a1');
    expect(userService.getConversationInsights).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="insights"]')).toBeNull();
  });

  // IN-8: the fifth tile spans the phone's two columns instead of sitting
  // alone; from md it is one tile again.
  it('lets the fifth stat tile span the phone row', async () => {
    await render('a1');
    const tiles = Array.from(
      container.querySelector('.grid')!.children,
    ) as HTMLElement[];
    expect(tiles).toHaveLength(5);
    expect(tiles[4].className.split(' ')).toEqual(
      expect.arrayContaining(['col-span-2', 'md:col-span-1']),
    );
    expect(tiles[3].className).not.toContain('col-span');
  });
  // FX-7: the shared ChartPanel, one outline level under the page's h1.
  it('titles its five chart panels as sections of the page', async () => {
    await render('a1');
    expect(
      Array.from(container.querySelectorAll('h2')).map((h) => h.textContent),
    ).toEqual([
      'settings.analytics.messages',
      'settings.analytics.tokenUsage',
      'settings.analytics.scheduledRuns',
      'settings.analytics.toolUsage',
      'settings.analytics.userFeedback',
    ]);
    expect(container.querySelector('h3')).toBeNull();
  });

  // DESIGN › Load errors: a failed chart says so, with Retry, instead of an
  // empty chart.
  it('says a chart failed to load and fetches it again on Retry', async () => {
    const feedback = vi.mocked(userService.getFeedbackAnalytics);
    feedback.mockClear();
    feedback.mockImplementationOnce(() =>
      Promise.resolve({
        ok: false,
        json: () => Promise.resolve({}),
      } as Response),
    );
    await render('a1');
    // The loading flags drop 250ms after the answer (useLoaderState).
    const settle = () =>
      act(() => new Promise((resolve) => setTimeout(resolve, 300)));
    await settle();
    const alerts = container.querySelectorAll('[role="alert"]');
    expect(alerts).toHaveLength(1);
    expect(alerts[0].textContent).toContain('settings.analytics.loadError');
    expect(
      alerts[0].closest('[data-slot="card"]')!.querySelector('h2')!.textContent,
    ).toBe('settings.analytics.userFeedback');
    await act(async () => alerts[0].querySelector('button')!.click());
    await settle();
    expect(feedback).toHaveBeenCalledTimes(2);
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('names the token group-by select, lets it grow, and fits its menu', async () => {
    await render('a1');
    const trigger = container.querySelector<HTMLElement>(
      '[data-slot="select-trigger"][aria-label="settings.analytics.groupBy"]',
    )!;
    expect(trigger).not.toBeNull();
    const classes = trigger.className.split(' ');
    expect(classes).toContain('min-w-[110px]');
    expect(classes.some((c) => /^w-\[/.test(c))).toBe(false);
    await act(async () => {
      trigger.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
    const menu = document.querySelector<HTMLElement>(
      '[data-slot="select-content"]',
    )!;
    expect(menu.className.split(' ')).toContain('w-auto');
  });
});
