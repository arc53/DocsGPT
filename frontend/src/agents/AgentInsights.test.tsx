import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('react-redux', () => ({ useSelector: () => 'token' }));
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
  },
}));
const seen = vi.hoisted(() => ({ props: [] as Record<string, unknown>[] }));
vi.mock('../settings/insights/ConversationInsights', () => ({
  InsightsSection: (props: Record<string, unknown>) => {
    seen.props.push(props);
    return <div data-testid="insights" />;
  },
}));
vi.mock('../navigation/SectionPageHeader', () => ({
  CurrentSectionHeader: () => <h1>Conversation insights</h1>,
}));

import AgentInsights from './AgentInsights';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('AgentInsights', () => {
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

  it("names the agent, puts the window in the toolbar, and shows the agent's insights as the page", async () => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/agents/manage/insights/a1']}>
          <Routes>
            <Route
              path="/agents/manage/insights/:agentId"
              element={<AgentInsights />}
            />
          </Routes>
        </MemoryRouter>,
      );
    });
    const toolbar = container.querySelector('[data-slot="page-toolbar"]')!;
    expect(toolbar.textContent).toContain('Carrier FAQ');
    expect(
      toolbar.querySelector('[data-slot="select-trigger"]'),
    ).not.toBeNull();
    expect(seen.props.at(-1)).toMatchObject({
      agentId: 'a1',
      agent: { id: 'a1' },
      filterOption: 'last_30_days',
      standalone: true,
    });
  });
});
