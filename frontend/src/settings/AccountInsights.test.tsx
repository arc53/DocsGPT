import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const seen = vi.hoisted(() => ({ props: [] as Record<string, unknown>[] }));
vi.mock('./insights/ConversationInsights', () => ({
  InsightsSection: (props: Record<string, unknown>) => {
    seen.props.push(props);
    return <div data-testid="insights">{props.actions as React.ReactNode}</div>;
  },
}));

import AccountInsights from './AccountInsights';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('Settings Insights', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    seen.props = [];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  // The account's insights, moved out of Analytics: the whole page, with the
  // window select where Analytics has its own.
  it("shows the account's insights as the page, with a time window", async () => {
    await act(async () =>
      root.render(
        <MemoryRouter>
          <AccountInsights />
        </MemoryRouter>,
      ),
    );
    expect(seen.props.at(-1)).toMatchObject({
      filterOption: 'last_30_days',
      standalone: true,
    });
    expect(seen.props.at(-1)?.agentId).toBeUndefined();
    expect(
      container.querySelector(
        '[data-testid="insights"] [data-slot="select-trigger"]',
      ),
    ).not.toBeNull();
  });
});
