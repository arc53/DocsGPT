import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('react-redux', () => ({ useSelector: () => 'token' }));
const agentRead = vi.hoisted(() => ({ ok: true, calls: 0 }));
const TOPICS = vi.hoisted(() => [
  { label: 'topic:Setup', name: 'Setup', overlap: false },
  { label: 'tag:a1b2c3d4', name: 'Pricing', overlap: true },
]);
const topicsRead = vi.hoisted(() => ({ calls: [] as unknown[][] }));
vi.mock('../api/services/userService', () => ({
  default: {
    getAgentTopics: (...args: unknown[]) => {
      topicsRead.calls.push(args);
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, topics: TOPICS }),
      });
    },
    getAgent: () =>
      Promise.resolve({
        ok: (agentRead.calls++, agentRead.ok),
        json: () =>
          Promise.resolve({
            id: 'a1',
            name: 'Carrier FAQ',
            last_used_at: null,
            config: {
              analytics: {
                enabled: true,
                topics: [
                  {
                    id: 'a1b2c3d4',
                    name: 'Pricing',
                    description: 'Prices',
                    overlap: true,
                  },
                  {
                    id: 'e5f6a7b8',
                    name: 'Setup',
                    description: '',
                    overlap: false,
                  },
                ],
                hidden_folders: [],
                digest: false,
              },
            },
          }),
      }),
  },
}));
const seen = vi.hoisted(() => ({ logs: [] as unknown[] }));
vi.mock('../settings/Analytics', () => ({
  default: () => <div data-testid="analytics" />,
}));
vi.mock('../settings/Logs', () => ({
  default: (props: { analytics?: unknown }) => {
    seen.logs.push(props.analytics);
    return <div data-testid="logs" />;
  },
}));
vi.mock('./components/GuardrailEvents', () => ({ default: () => null }));
vi.mock('../navigation/SectionPageHeader', () => ({
  CurrentSectionHeader: () => <h1>Logs</h1>,
}));
vi.mock('../navigation/SectionPills', () => ({ default: () => null }));

import AgentLogs from './AgentLogs';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('AgentLogs', () => {
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

  // A3: the same toolbar as Overview and Schedules, the agent in its byline.
  it('names the agent in the shared agent toolbar', async () => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/agents/manage/logs/a1']}>
          <Routes>
            <Route
              path="/agents/manage/logs/:agentId"
              element={<AgentLogs />}
            />
          </Routes>
        </MemoryRouter>,
      );
    });
    const toolbar = container.querySelector('[data-slot="page-toolbar"]')!;
    expect(toolbar.textContent).toContain('Carrier FAQ');
    expect(toolbar.textContent).toContain('agents.logs.noUsageHistory');
    expect(toolbar.querySelector('[data-slot="separator"]')).not.toBeNull();
    // The agent's ⋯ (Access details, Share, Delete) is Overview's alone; the
    // Monitoring pages and Schedules keep to their own actions.
    expect(
      toolbar.querySelector(
        'button[aria-label="agents.form.buttons.moreActions"]',
      ),
    ).toBeNull();
  });

  // Logs filters by the agent's labels and tags, and is the `#logs` target
  // of a drill-down from its Insights.
  it("hands the agent's analytics to Logs", async () => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/agents/manage/logs/a1']}>
          <Routes>
            <Route
              path="/agents/manage/logs/:agentId"
              element={<AgentLogs />}
            />
          </Routes>
        </MemoryRouter>,
      );
    });
    // Its topics as the server lists them: folders and own, each with its filter.
    expect(seen.logs.at(-1)).toEqual({ enabled: true, topics: TOPICS });
    expect(topicsRead.calls.at(-1)).toEqual(['a1', 'token']);
    expect(
      container.querySelector('#logs [data-testid="logs"]'),
    ).not.toBeNull();
  });

  // The usage charts are the agent's Analytics page now.
  it('leaves the usage charts to Analytics', async () => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/agents/manage/logs/a1']}>
          <Routes>
            <Route
              path="/agents/manage/logs/:agentId"
              element={<AgentLogs />}
            />
          </Routes>
        </MemoryRouter>,
      );
    });
    expect(container.querySelector('[data-testid="analytics"]')).toBeNull();
    expect(container.querySelector('[data-testid="logs"]')).not.toBeNull();
  });

  // IN-17: the drill-down target is a named section, the peer of Guardrail
  // activity, with copy about this agent.
  it('names the log list in a Logs section that the #logs links land on', async () => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/agents/manage/logs/a1']}>
          <Routes>
            <Route
              path="/agents/manage/logs/:agentId"
              element={<AgentLogs />}
            />
          </Routes>
        </MemoryRouter>,
      );
    });
    const section = container.querySelector('section#logs')!;
    expect(section).not.toBeNull();
    const heading = section.querySelector('[data-slot="section-header"] h2');
    expect(heading?.textContent).toBe('agents.pageHeader.tabs.logs');
    expect(section.textContent).toContain('agents.logs.description');
    expect(section.querySelector('[data-testid="logs"]')).not.toBeNull();
  });

  // DESIGN › Load errors: an agent that fails to load says so, with Retry,
  // in place of what it fills (the toolbar's byline); its guardrail
  // activity and logs need only its id, so they stay.
  it('says the agent failed to load, keeps its logs, and reads it again on Retry', async () => {
    agentRead.ok = false;
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/agents/manage/logs/a1']}>
          <Routes>
            <Route
              path="/agents/manage/logs/:agentId"
              element={<AgentLogs />}
            />
          </Routes>
        </MemoryRouter>,
      );
    });
    const alert = container.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain('agents.loadError');
    expect(container.querySelector('[data-testid="logs"]')).not.toBeNull();
    expect(container.querySelector('section#logs')).not.toBeNull();
    agentRead.ok = true;
    await act(async () => alert.querySelector('button')!.click());
    await act(async () => undefined);
    expect(agentRead.calls).toBe(2);
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('[data-testid="logs"]')).not.toBeNull();
  });
});
