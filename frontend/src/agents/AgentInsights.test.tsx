import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import examples from '../settings/insights/fixtures/apiExamples.json';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('react-redux', () => ({ useSelector: () => 'token' }));
const insights = vi.hoisted(() => ({ body: {} as object }));
const record = vi.hoisted(() => ({
  actions: undefined as string[] | undefined,
  calls: { agent: 0, insights: 0 },
  ok: true,
}));
vi.mock('../api/services/userService', () => ({
  default: {
    getAgent: () => {
      record.calls.agent += 1;
      return Promise.resolve({
        ok: record.ok,
        json: () =>
          Promise.resolve({
            id: 'a1',
            name: 'Carrier FAQ',
            agent_type: 'classic',
            last_used_at: null,
            allowed_actions: record.actions,
          }),
      });
    },
    getConversationInsights: () => {
      record.calls.insights += 1;
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(insights.body),
      });
    },
  },
}));
const sheet = vi.hoisted(() => ({ props: [] as Record<string, unknown>[] }));
vi.mock('./components/InsightsSettingsSheet', () => ({
  default: (props: Record<string, unknown>) => {
    sheet.props.push(props);
    return props.open ? <div data-testid="insights-sheet" /> : null;
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
    sheet.props = [];
    record.actions = undefined;
    record.calls = { agent: 0, insights: 0 };
    record.ok = true;
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

  const settingsButton = () =>
    Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-slot="page-toolbar"] button',
      ),
    ).find(
      (b) => b.textContent === 'settings.analytics.insights.settings.button',
    );

  // IN-6 + IN-21: the settings open in a panel on the page they change.
  it('gives an editor a Settings button after the window that opens the settings panel', async () => {
    insights.body = examples.insights;
    record.actions = ['view', 'edit'];
    await render();
    const toolbar = container.querySelector('[data-slot="page-toolbar"]')!;
    const trigger = toolbar.querySelector('[data-slot="select-trigger"]')!;
    const button = settingsButton()!;
    expect(
      trigger.compareDocumentPosition(button) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      container.querySelector('[data-testid="insights-sheet"]'),
    ).toBeNull();
    await act(async () => button.click());
    expect(
      container.querySelector('[data-testid="insights-sheet"]'),
    ).not.toBeNull();
    expect(sheet.props.at(-1)).toMatchObject({
      open: true,
      startEnabled: false,
      agent: { id: 'a1' },
    });
  });

  it("opens the panel switched on from the off state's Turn on", async () => {
    insights.body = { ...examples.insights, enabled: false };
    record.actions = ['view', 'edit'];
    await render();
    const onTurnOn = seen.props.at(-1)!.onTurnOn as () => void;
    await act(async () => onTurnOn());
    expect(sheet.props.at(-1)).toMatchObject({
      open: true,
      startEnabled: true,
    });
  });

  it('refreshes the agent and its insights after a save', async () => {
    insights.body = examples.insights;
    record.actions = ['view', 'edit'];
    await render();
    await act(async () => settingsButton()!.click());
    const before = { ...record.calls };
    const onSaved = sheet.props.at(-1)!.onSaved as (config: object) => void;
    await act(async () => onSaved({ analytics: { enabled: false } }));
    await act(async () => undefined);
    expect(record.calls.insights).toBe(before.insights + 1);
    expect(record.calls.agent).toBe(before.agent + 1);
  });

  it('gives a viewer no Settings button and no Turn on', async () => {
    insights.body = { ...examples.insights, enabled: false };
    record.actions = ['view'];
    await render();
    expect(settingsButton()).toBeUndefined();
    expect(seen.props.at(-1)!.onTurnOn).toBeUndefined();
  });

  // DESIGN › Load errors.
  it('says the agent failed to load and reads it again on Retry', async () => {
    insights.body = examples.insights;
    record.ok = false;
    await render();
    const alert = container.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain('agents.loadError');
    expect(container.querySelector('[data-testid="insights"]')).toBeNull();
    record.ok = true;
    await act(async () => alert.querySelector('button')!.click());
    await act(async () => undefined);
    expect(record.calls.agent).toBe(2);
    expect(container.querySelector('[data-testid="insights"]')).not.toBeNull();
  });
});
