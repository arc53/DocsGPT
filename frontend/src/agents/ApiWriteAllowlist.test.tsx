import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (!opts) return key;
      const params = Object.entries(opts)
        .filter(([k]) => k !== 'interpolation' && k !== 'count')
        .map(([k, v]) => `${k}=${v}`)
        .join(',');
      return params ? `${key}(${params})` : key;
    },
    i18n: { language: 'en' },
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
import type { Mock } from 'vitest';

import type { Agent, AgentConfig, ResourceState } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const TOOLS = {
  tools: [
    {
      id: 'tg',
      displayName: 'Telegram',
      connection_id: 'c1',
      owner_credential_writes: ['telegram_send_message'],
      actions: [
        {
          name: 'telegram_send_message',
          description: 'Sends a message.',
          access: 'write',
          active: true,
        },
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
    owner_credential_writes: ['telegram_send_message', 'telegram_pin_message'],
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
    {
      onConfigChange = vi.fn<(config: AgentConfig) => void>(),
      getSavedConfig,
      defaultOpen,
    }: {
      onConfigChange?: Mock<(config: AgentConfig) => void>;
      getSavedConfig?: () => Agent['config'];
      defaultOpen?: boolean;
    } = {},
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
            defaultOpen={defaultOpen}
          />
        </Provider>,
      );
    });
    return onConfigChange;
  };

  const K = 'modals.agentDetails.apiWrites';
  const disclosure = () =>
    Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes(`${K}.title`),
    )!;
  const expand = async () => {
    if (disclosure().getAttribute('aria-expanded') === 'false')
      await act(async () => disclosure().click());
  };
  const groups = () =>
    Array.from(container.querySelectorAll<HTMLElement>('[data-tool]'));
  const groupTitles = () =>
    groups().map((g) => g.querySelector('h4')?.textContent);
  const group = (id: string) =>
    container.querySelector<HTMLElement>(`[data-tool="${id}"]`)!;
  const choice = (id: string, value: 'off' | 'all') =>
    group(id).querySelector<HTMLButtonElement>(`[data-choice="${value}"]`)!;
  const customize = async (id: string) => {
    const button = Array.from(group(id).querySelectorAll('button')).find(
      (b) => b.getAttribute('aria-expanded') === 'false',
    );
    if (button) await act(async () => button.click());
  };
  const actionSwitch = (id: string, label: string) => {
    const row = Array.from(
      group(id).querySelectorAll<HTMLElement>('[data-slot="setting-row"]'),
    ).find((r) => r.querySelector('label')?.textContent === label)!;
    return row.querySelector<HTMLButtonElement>('[role="switch"]')!;
  };
  const summary = () =>
    container.querySelector('[data-testid="api-writes-summary"]')?.textContent;
  const savedConfig = () =>
    JSON.parse(
      (updateAgent.mock.calls.at(-1)![1] as FormData).get('config') as string,
    );

  it('starts folded to a summary line, and nothing is allowed by default', async () => {
    await render(agent());
    expect(disclosure().getAttribute('aria-expanded')).toBe('false');
    expect(summary()).toBe(`${K}.summaryNone`);
    expect(groups()).toHaveLength(0);
    await expand();
    expect(disclosure().getAttribute('aria-expanded')).toBe('true');
    expect(choice('tg', 'off').getAttribute('data-state')).toBe('on');
  });

  it('opens straight away when asked to', async () => {
    await render(agent(), { defaultOpen: true });
    expect(disclosure().getAttribute('aria-expanded')).toBe('true');
    expect(groupTitles()).toEqual(['Telegram']);
  });

  it('names the tools that can make changes and counts what is allowed', async () => {
    await render(
      agent({
        tools: ['tg', 'crm', 'memory'],
        config: {
          api_write_allowlist: ['tg:telegram_send_message', 'crm:create_lead'],
        },
      } as Partial<Agent>),
    );
    expect(summary()).toBe(
      `${K}.summaryTools(tools=Telegram and CRM API) · ${K}.summaryCount(allowed=2,formatted=3)`,
    );
  });

  it("groups only writes on the owner's credentials by tool, each action under Customize", async () => {
    await render(agent());
    await expand();
    expect(groupTitles()).toEqual(['Telegram']);
    expect(container.textContent).not.toContain('Telegram send message');
    await customize('tg');
    const labels = Array.from(
      group('tg').querySelectorAll('[data-slot="setting-row"] label'),
    ).map((l) => l.textContent);
    expect(labels).toEqual(['Telegram send message', 'Telegram pin message']);
    expect(group('tg').textContent).toContain('Sends a message.');
    expect(
      actionSwitch('tg', 'Telegram send message').getAttribute('aria-checked'),
    ).toBe('false');
  });

  it("allows all of a tool's changes at once, without dropping the rest of the config", async () => {
    updateAgent.mockResolvedValue({ ok: true });
    const onConfigChange = await render(agent());
    await expand();
    await act(async () => choice('tg', 'all').click());
    const expected = {
      guardrails: { controls: [] },
      api_write_allowlist: [
        'tg:telegram_send_message',
        'tg:telegram_pin_message',
      ],
    };
    expect(updateAgent).toHaveBeenCalledTimes(1);
    expect(savedConfig()).toEqual(expected);
    expect(onConfigChange).toHaveBeenCalledWith(expected);
    expect(choice('tg', 'all').getAttribute('data-state')).toBe('on');
    expect(summary()).toBe(
      `${K}.summaryTools(tools=Telegram) · ${K}.summaryCount(allowed=2,formatted=2)`,
    );
  });

  it('locks the choices while a save is in flight, so saves never overlap', async () => {
    let finish: (value: { ok: boolean }) => void = () => undefined;
    updateAgent.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    await render(agent());
    await expand();
    await act(async () => choice('tg', 'all').click());
    expect(choice('tg', 'off').hasAttribute('disabled')).toBe(true);
    await act(async () => choice('tg', 'off').click());
    expect(updateAgent).toHaveBeenCalledTimes(1);
    await act(async () => finish({ ok: true }));
    expect(choice('tg', 'off').hasAttribute('disabled')).toBe(false);
  });

  it('turns a tool off again, keeping entries of tools no longer listed', async () => {
    updateAgent.mockResolvedValue({ ok: true });
    await render(
      agent({
        config: {
          api_write_allowlist: [
            'tg:telegram_send_message',
            'tg:telegram_pin_message',
            'old:gone_action',
          ],
        },
      } as Partial<Agent>),
    );
    await expand();
    await act(async () => choice('tg', 'off').click());
    expect(savedConfig().api_write_allowlist).toEqual(['old:gone_action']);
  });

  // Every tool has a Customize link; each names its tool to screen readers.
  it('ties each Customize link to its tool', async () => {
    await render(agent({ tools: ['tg', 'crm'] }), { defaultOpen: true });
    for (const [id, name] of [
      ['tg', 'Telegram'],
      ['crm', 'CRM API'],
    ]) {
      const link = Array.from(group(id).querySelectorAll('button')).find(
        (b) => b.getAttribute('aria-expanded') === 'false',
      )!;
      const describedBy = link.getAttribute('aria-describedby');
      expect(describedBy).toBeTruthy();
      expect(document.getElementById(describedBy!)?.textContent).toBe(name);
    }
  });

  it('allows one action under Customize, leaving the tool choice mixed', async () => {
    updateAgent.mockResolvedValue({ ok: true });
    await render(agent());
    await expand();
    await customize('tg');
    await act(async () => actionSwitch('tg', 'Telegram pin message').click());
    expect(savedConfig().api_write_allowlist).toEqual([
      'tg:telegram_pin_message',
    ]);
    expect(
      actionSwitch('tg', 'Telegram pin message').getAttribute('aria-checked'),
    ).toBe('true');
    expect(choice('tg', 'off').getAttribute('data-state')).toBe('off');
    expect(choice('tg', 'all').getAttribute('data-state')).toBe('off');
  });

  it('saves on top of the last saved config, not unsaved form edits', async () => {
    updateAgent.mockResolvedValue({ ok: true });
    const saved = { guardrails: { controls: [] } } as unknown as NonNullable<
      Agent['config']
    >;
    const draft = agent({
      config: { guardrails: { controls: [{ id: 'unsaved' }] } },
    } as unknown as Partial<Agent>);
    const onConfigChange = await render(draft, {
      getSavedConfig: () => saved,
    });
    await expand();
    await act(async () => choice('tg', 'all').click());
    const expected = {
      guardrails: { controls: [] },
      api_write_allowlist: [
        'tg:telegram_send_message',
        'tg:telegram_pin_message',
      ],
    };
    expect(savedConfig()).toEqual(expected);
    expect(onConfigChange).toHaveBeenCalledWith(expected);
  });

  it('puts the choice back and says so when saving fails', async () => {
    updateAgent.mockResolvedValue({ ok: false });
    await render(agent());
    await expand();
    await act(async () => choice('tg', 'all').click());
    expect(choice('tg', 'off').getAttribute('data-state')).toBe('on');
    expect(summary()).toBe(`${K}.summaryNone`);
    expect(selectActionToast(store.getState())?.variant).toBe('destructive');
  });

  it('lists writes on stored credentials of tools without a connection', async () => {
    await render(agent({ tools: ['crm'] }), { defaultOpen: true });
    expect(groupTitles()).toEqual(['CRM API']);
    await customize('crm');
    expect(
      group('crm').querySelector('[data-slot="setting-row"] label')
        ?.textContent,
    ).toBe('Create lead');
  });

  it("lists a sponsor's tool the owner can't see, but not a stopped one", async () => {
    await render(agent({ tools: ['bob-jira', 'gone'] }), {
      defaultOpen: true,
    });
    expect(groupTitles()).toEqual(['Bob Jira']);
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
    await render(agent({ tools: [] }), { defaultOpen: true });
    expect(groupTitles()).toEqual(['Node Slack']);
  });

  it('renders nothing for an agent without connected tools', async () => {
    await render(agent({ tools: ['memory'] }));
    expect(container.textContent).toBe('');
  });
});
