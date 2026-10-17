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
vi.mock('../settings/Analytics', () => ({
  default: () => <div data-testid="analytics" />,
}));
vi.mock('../settings/Logs', () => ({
  default: () => <div data-testid="logs" />,
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
});
