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
      getMessageAnalytics: empty,
      getTokenAnalytics: empty,
      getFeedbackAnalytics: empty,
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
          <Analytics agentId={agentId} />
        </MemoryRouter>,
      ),
    );
    await act(async () => undefined);
  };

  const feedbackRow = () =>
    Array.from(container.querySelectorAll('h3'))
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

  it("leaves an agent's insights to its own page", async () => {
    vi.mocked(userService.getConversationInsights).mockClear();
    insights.body = examples.insights;
    await render('a1');
    expect(userService.getConversationInsights).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="insights"]')).toBeNull();
  });
});
