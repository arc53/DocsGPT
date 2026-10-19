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

describe('Analytics with conversation insights', () => {
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

  const render = async () => {
    await act(async () =>
      root.render(
        <MemoryRouter>
          <Analytics agentId="a1" />
        </MemoryRouter>,
      ),
    );
    await act(async () => undefined);
  };

  const feedbackRow = () =>
    Array.from(container.querySelectorAll('h3'))
      .find((h) => h.textContent === 'settings.analytics.userFeedback')!
      .closest('[data-slot="card"]')!.parentElement!;

  it('asks once for the window, and puts implicit feedback beside the thumbs', async () => {
    insights.body = examples.insights;
    await render();
    expect(userService.getConversationInsights).toHaveBeenCalledWith(
      { api_key_id: 'a1', filter_option: 'last_30_days' },
      'token',
    );
    expect(feedbackRow().className).toContain('xl:flex-row');
    expect(
      feedbackRow().querySelector('[data-testid="implicit-feedback"]'),
    ).not.toBeNull();
    expect(container.querySelector('[data-testid="insights"]')).not.toBeNull();
  });

  it('keeps the thumbs full width, and shows no section, while the server has it off', async () => {
    insights.body = { ...examples.insights, available: false, enabled: false };
    await render();
    expect(feedbackRow().className).not.toContain('xl:flex-row');
    expect(
      container.querySelector('[data-testid="implicit-feedback"]'),
    ).toBeNull();
    expect(container.querySelector('[data-testid="insights"]')).toBeNull();
  });
});
