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
        <MemoryRouter>
          <AccountInsights />
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

  it('draws nothing while the server has insights off', async () => {
    insights.body = { ...examples.insights, available: false, enabled: false };
    await render();
    expect(container.querySelector('[data-slot="page-toolbar"]')).toBeNull();
    expect(container.querySelector('[data-testid="insights"]')).toBeNull();
  });
});
