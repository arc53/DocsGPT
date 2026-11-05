import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('react-redux', () => ({ useSelector: () => 'token' }));
const agentRead = vi.hoisted(() => ({ ok: true, calls: 0 }));
vi.mock('../api/services/userService', () => ({
  default: {
    getAgent: () =>
      Promise.resolve({
        ok: (agentRead.calls++, agentRead.ok),
        json: () =>
          Promise.resolve({
            id: 'a1',
            name: 'Carrier FAQ',
            last_used_at: null,
          }),
      }),
  },
}));
const seen = vi.hoisted(() => ({ props: [] as Record<string, unknown>[] }));
vi.mock('../settings/Analytics', () => ({
  default: (props: Record<string, unknown>) => {
    seen.props.push(props);
    return <div data-testid="analytics" />;
  },
}));
vi.mock('../navigation/SectionPageHeader', () => ({
  CurrentSectionHeader: () => <h1>Analytics</h1>,
}));

import AgentAnalytics from './AgentAnalytics';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('AgentAnalytics', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    agentRead.ok = true;
    agentRead.calls = 0;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("names the agent in the toolbar and shows the agent's usage charts", async () => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/agents/manage/analytics/a1']}>
          <Routes>
            <Route
              path="/agents/manage/analytics/:agentId"
              element={<AgentAnalytics />}
            />
          </Routes>
        </MemoryRouter>,
      );
    });
    const toolbar = container.querySelector('[data-slot="page-toolbar"]')!;
    expect(toolbar.textContent).toContain('Carrier FAQ');
    expect(toolbar.textContent).toContain('agents.logs.noUsageHistory');
    expect(container.querySelector('[data-testid="analytics"]')).not.toBeNull();
    // IN-16: the window is the toolbar's action, as on Insights.
    expect(
      toolbar.querySelector('[data-slot="select-trigger"]'),
    ).not.toBeNull();
    expect(seen.props.at(-1)).toEqual({
      agentId: 'a1',
      filterOption: 'last_30_days',
    });
    // The agent's own subtitle, first under the rule.
    const subtitle = Array.from(container.querySelectorAll('p')).find(
      (p) => p.textContent === 'agents.analytics.subtitle',
    );
    expect(subtitle).toBeDefined();
    expect(container.textContent).not.toContain('settings.analytics.subtitle');
  });

  // DESIGN › Load errors: the agent's name fails, its usage (which needs
  // only its id) stays.
  it('says the agent failed to load, keeps its usage, and reads it again on Retry', async () => {
    agentRead.ok = false;
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/agents/manage/analytics/a1']}>
          <Routes>
            <Route
              path="/agents/manage/analytics/:agentId"
              element={<AgentAnalytics />}
            />
          </Routes>
        </MemoryRouter>,
      );
    });
    const alert = container.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain('agents.loadError');
    expect(container.querySelector('[data-testid="analytics"]')).not.toBeNull();
    agentRead.ok = true;
    await act(async () => alert.querySelector('button')!.click());
    await act(async () => undefined);
    expect(agentRead.calls).toBe(2);
    expect(container.querySelector('[data-testid="analytics"]')).not.toBeNull();
  });
});
