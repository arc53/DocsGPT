import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import examples from '../settings/insights/fixtures/apiExamples.json';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('react-redux', () => ({ useSelector: () => 'token' }));
const insights = vi.hoisted(() => ({ body: {} as object }));
vi.mock('../api/services/userService', () => ({
  default: {
    getAgent: () =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            id: 'a1',
            name: 'Carrier FAQ',
            last_used_at: null,
          }),
      }),
    getConversationInsights: () =>
      Promise.resolve({ ok: true, json: () => Promise.resolve(insights.body) }),
  },
}));
const seen = vi.hoisted(() => ({ props: [] as Record<string, unknown>[] }));
vi.mock('../settings/insights/ConversationInsights', () => ({
  default: (props: Record<string, unknown>) => {
    seen.props.push(props);
    return <div data-testid="insights" />;
  },
}));
vi.mock('../navigation/SectionPageHeader', () => ({
  CurrentSectionHeader: () => <h1>Insights</h1>,
}));

import AgentInsights from './AgentInsights';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('AgentInsights', () => {
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

  const render = async () => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/agents/manage/insights/a1']}>
          <Routes>
            <Route
              path="/agents/manage/insights/:agentId"
              element={<AgentInsights />}
            />
            <Route
              path="/agents/manage/logs/:agentId"
              element={<p data-testid="logs">logs</p>}
            />
          </Routes>
        </MemoryRouter>,
      );
    });
    await act(async () => undefined);
  };

  it("names the agent, puts the window in the toolbar, and shows the agent's insights as the page", async () => {
    insights.body = examples.insights;
    await render();
    const toolbar = container.querySelector('[data-slot="page-toolbar"]')!;
    expect(toolbar.textContent).toContain('Carrier FAQ');
    expect(
      toolbar.querySelector('[data-slot="select-trigger"]'),
    ).not.toBeNull();
    expect(seen.props.at(-1)).toMatchObject({
      state: 'ready',
      agentId: 'a1',
      agent: { id: 'a1' },
      filterOption: 'last_30_days',
      standalone: true,
    });
  });

  // FX-5: a deep link (the weekly notification's) while the server has
  // insights off goes to the agent's Logs, not a blank page.
  it("sends a deep link to the agent's Logs while the server has insights off", async () => {
    insights.body = { ...examples.insights, available: false, enabled: false };
    await render();
    expect(container.querySelector('[data-testid="logs"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="insights"]')).toBeNull();
  });
});
