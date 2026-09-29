import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts?.action ? `${opts.tool}: ${opts.action}` : key,
  }),
}));

const getUserTools = vi.fn();
const getAgent = vi.fn();
const getWorkflow = vi.fn();
const updateAgent = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    getUserTools: (...args: unknown[]) => getUserTools(...args),
    getAgent: (...args: unknown[]) => getAgent(...args),
    getWorkflow: (...args: unknown[]) => getWorkflow(...args),
    updateAgent: (...args: unknown[]) => updateAgent(...args),
  },
}));

import actionToastReducer, {
  selectActionToast,
} from '../notifications/actionToastSlice';
import { prefSlice } from '../preferences/preferenceSlice';
import ApiWriteAllowlist from './ApiWriteAllowlist';
import type { Agent, ResourceState } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const TOOLS = {
  tools: [
    {
      id: 'tg',
      displayName: 'Telegram',
      connection_id: 'c1',
      owner_credential_writes: ['telegram_send_message'],
      actions: [
        { name: 'telegram_send_message', access: 'write', active: true },
        { name: 'telegram_read', access: 'read', active: true },
      ],
    },
    {
      id: 'memory',
      displayName: 'Memory',
      connection_id: null,
      owner_credential_writes: [],
      actions: [{ name: 'memory_write', access: 'write', active: true }],
    },
    {
      id: 'crm',
      displayName: 'CRM API',
      connection_id: null,
      owner_credential_writes: ['create_lead'],
      actions: [],
    },
  ],
};

// What the agent read says each tool may write on stored credentials: the
// owner's own tools, one an editor sponsored that the owner can't see, and
// one that stopped.
const state = (over: Partial<ResourceState>): ResourceState => ({
  key: `tool:${over.id}`,
  type: 'tool',
  id: 'x',
  name: 'Tool',
  state: 'active',
  reason: null,
  owner_credential_writes: [],
  ...over,
});

const STATES: ResourceState[] = [
  state({
    id: 'tg',
    name: 'Telegram',
    owner_credential_writes: ['telegram_send_message'],
  }),
  state({ id: 'memory', name: 'Memory' }),
  state({
    id: 'crm',
    name: 'CRM API',
    owner_credential_writes: ['create_lead'],
  }),
  state({
    id: 'bob-jira',
    name: 'Bob Jira',
    runs_as: { user_id: 'bob', label: 'bob@example.com' },
    owner_credential_writes: ['create_issue'],
  }),
  state({
    id: 'gone',
    name: 'Gone',
    state: 'stopped',
    reason: 'deleted',
    owner_credential_writes: ['delete_all'],
  }),
];

const readAgent = (tools: string[], extra: Partial<Agent> = {}) => ({
  ok: true,
  json: async () => ({
    id: 'agent-1',
    agent_type: 'classic',
    tools,
    resource_states: STATES.filter((s) => tools.includes(s.id)),
    ...extra,
  }),
});

const agent = (overrides: Partial<Agent> = {}): Agent =>
  ({
    id: 'agent-1',
    tools: ['tg', 'memory'],
    config: { guardrails: { controls: [] } },
    ...overrides,
  }) as unknown as Agent;

describe('ApiWriteAllowlist', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: ReturnType<typeof makeStore>;
  const makeStore = () =>
    configureStore({
      reducer: {
        preference: prefSlice.reducer,
        actionToast: actionToastReducer,
      },
    });

  beforeEach(() => {
    getUserTools.mockResolvedValue({ json: async () => TOOLS });
    getAgent
      .mockReset()
      .mockImplementation(async () => readAgent(currentTools));
    getWorkflow.mockReset();
    updateAgent.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  let currentTools: string[] = [];
  const render = async (
    a: Agent,
    onConfigChange = vi.fn(),
    getSavedConfig?: () => Agent['config'],
  ) => {
    currentTools = a.tools ?? [];
    store = makeStore();
    await act(async () => {
      root.render(
        <Provider store={store}>
          <ApiWriteAllowlist
            agent={a}
            onConfigChange={onConfigChange}
            getSavedConfig={getSavedConfig}
          />
        </Provider>,
      );
    });
    return onConfigChange;
  };

  it("lists only writes on the owner's credentials, unchecked by default", async () => {
    await render(agent());
    const labels = Array.from(container.querySelectorAll('label')).map(
      (l) => l.textContent,
    );
    expect(labels).toEqual(['Telegram: Telegram send message']);
    expect(
      container
        .querySelector('button[role="checkbox"]')!
        .getAttribute('aria-checked'),
    ).toBe('false');
  });

  it('saves the allowlist without dropping the rest of the config', async () => {
    updateAgent.mockResolvedValue({ ok: true });
    const onConfigChange = await render(agent());
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('button[role="checkbox"]')!
        .click(),
    );
    const form = updateAgent.mock.calls[0][1] as FormData;
    expect(JSON.parse(form.get('config') as string)).toEqual({
      guardrails: { controls: [] },
      api_write_allowlist: ['tg:telegram_send_message'],
    });
    expect(onConfigChange).toHaveBeenCalledWith({
      guardrails: { controls: [] },
      api_write_allowlist: ['tg:telegram_send_message'],
    });
  });

  it('saves on top of the last saved config, not unsaved form edits', async () => {
    updateAgent.mockResolvedValue({ ok: true });
    const saved = { guardrails: { controls: [] } } as unknown as NonNullable<
      Agent['config']
    >;
    const draft = agent({
      config: { guardrails: { controls: [{ id: 'unsaved' }] } },
    } as unknown as Partial<Agent>);
    const onConfigChange = await render(draft, vi.fn(), () => saved);
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('button[role="checkbox"]')!
        .click(),
    );
    const expected = {
      guardrails: { controls: [] },
      api_write_allowlist: ['tg:telegram_send_message'],
    };
    const form = updateAgent.mock.calls[0][1] as FormData;
    expect(JSON.parse(form.get('config') as string)).toEqual(expected);
    expect(onConfigChange).toHaveBeenCalledWith(expected);
  });

  it('puts the choice back and says so when saving fails', async () => {
    updateAgent.mockResolvedValue({ ok: false });
    await render(agent());
    const box = () =>
      container.querySelector<HTMLButtonElement>('button[role="checkbox"]')!;
    await act(async () => box().click());
    expect(box().getAttribute('aria-checked')).toBe('false');
    expect(selectActionToast(store.getState())?.variant).toBe('destructive');
  });

  it('lists writes on stored credentials of tools without a connection', async () => {
    await render(agent({ tools: ['crm'] }));
    const labels = Array.from(container.querySelectorAll('label')).map(
      (l) => l.textContent,
    );
    expect(labels).toEqual(['CRM API: Create lead']);
  });

  it("lists a sponsor's tool the owner can't see, but not a stopped one", async () => {
    await render(agent({ tools: ['bob-jira', 'gone'] }));
    const labels = Array.from(container.querySelectorAll('label')).map(
      (l) => l.textContent,
    );
    expect(labels).toEqual(['Bob Jira: Create issue']);
  });

  it("lists writes of a workflow agent's node tools", async () => {
    getAgent.mockResolvedValue(
      readAgent([], { agent_type: 'workflow', workflow: 'w1' }),
    );
    getWorkflow.mockResolvedValue({
      ok: true,
      json: async () => ({
        data: {
          resource_states: [
            state({
              id: 'node-tool',
              name: 'Node Slack',
              owner_credential_writes: ['post_message'],
            }),
          ],
        },
      }),
    });
    await render(agent({ tools: [] }));
    const labels = Array.from(container.querySelectorAll('label')).map(
      (l) => l.textContent,
    );
    expect(labels).toEqual(['Node Slack: Post message']);
  });

  it('renders nothing for an agent without connected tools', async () => {
    await render(agent({ tools: ['memory'] }));
    expect(container.textContent).toBe('');
  });
});
