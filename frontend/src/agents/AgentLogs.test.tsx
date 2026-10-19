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
            config: {
              analytics: {
                enabled: true,
                topics: { mode: 'auto', items: [] },
                tags: [
                  { id: 'a1b2c3d4', name: 'Pricing', description: 'Prices' },
                ],
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
  });

  // Logs filters by the agent's labels and tags, and is the `#logs` target
  // of a drill-down from its Conversation insights.
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
    expect(seen.logs.at(-1)).toEqual({
      enabled: true,
      tags: [{ id: 'a1b2c3d4', name: 'Pricing', description: 'Prices' }],
    });
    expect(
      container.querySelector('#logs [data-testid="logs"]'),
    ).not.toBeNull();
  });
});
