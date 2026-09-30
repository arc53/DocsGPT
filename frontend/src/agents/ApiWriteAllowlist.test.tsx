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
      b.textContent?.includes(`${K}.choose`),
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
  const choice = (id: string, value: 'off' | 'always' | 'customize') =>
    group(id).querySelector<HTMLButtonElement>(`[data-permission="${value}"]`)!;
  const customize = async (id: string) => {
    if (choice(id, 'customize').getAttribute('data-state') !== 'on')
      await act(async () => choice(id, 'customize').click());
  };
  const rowNames = (id: string) =>
    Array.from(group(id).querySelectorAll('li p:first-child')).map(
      (p) => p.textContent,
    );
  const rowSelect = (id: string, label: string) =>
    Array.from(group(id).querySelectorAll<HTMLElement>('li'))
      .find((li) => li.querySelector('p')?.textContent === label)!
      .querySelector<HTMLElement>('[data-slot="select-trigger"]')!;
  const pick = async (trigger: HTMLElement, text: string) => {
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', {
          bubbles: true,
          button: 0,
          pointerType: 'mouse',
        }),
      );
    });
    const option = Array.from(
      document.body.querySelectorAll<HTMLElement>('[role="option"]'),
    ).find((o) => o.textContent === text)!;
    await act(async () => option.click());
  };
  const P = 'settings.connectors.permission';
  // "Telegram · 0 of 2 allowed"
  const titled = (name: string, allowed: number, total: number) =>
    `${name} · ${K}.summaryCount(allowed=${allowed},formatted=${total})`;
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

  it('heads the group with its title and summary, the disclosure below', async () => {
    await render(agent());
    const heading = container.querySelector('h3')!;
    expect(heading.textContent).toBe(`${K}.title`);
    expect(heading.closest('button')).toBeNull();
    const header = heading.closest('[data-slot="section-header"]')!;
    expect(header.textContent).toContain(`${K}.summaryNone`);
    expect(
      header.compareDocumentPosition(disclosure()) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('opens straight away when asked to', async () => {
    await render(agent(), { defaultOpen: true });
    expect(disclosure().getAttribute('aria-expanded')).toBe('true');
    expect(groupTitles()).toEqual([titled('Telegram', 0, 2)]);
  });

  it('offers Allow / Off / Customize in the connector words and order', async () => {
    await render(agent(), { defaultOpen: true });
    expect(
      Array.from(group('tg').querySelectorAll('[data-permission]')).map(
        (b) => b.textContent,
      ),
    ).toEqual([`${P}.always`, `${P}.off`, `${P}.customize`]);
    // The count is in the title; no per-tool line under it.
    expect(
      group('tg').querySelector('[data-slot="section-header"] p'),
    ).toBeNull();
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
    expect(groupTitles()).toEqual([titled('Telegram', 0, 2)]);
    expect(container.textContent).not.toContain('Telegram send message');
    await customize('tg');
    expect(rowNames('tg')).toEqual([
      'Telegram send message',
      'Telegram pin message',
    ]);
    expect(group('tg').textContent).toContain('Sends a message.');
    expect(rowSelect('tg', 'Telegram send message').textContent).toBe(
      `${P}.off`,
    );
  });

  it("allows all of a tool's changes at once, without dropping the rest of the config", async () => {
    updateAgent.mockResolvedValue({ ok: true });
    const onConfigChange = await render(agent());
    await expand();
    await act(async () => choice('tg', 'always').click());
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
    expect(choice('tg', 'always').getAttribute('data-state')).toBe('on');
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
    await act(async () => choice('tg', 'always').click());
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

  it("names each tool's choice for screen readers", async () => {
    await render(agent({ tools: ['tg', 'crm'] }), { defaultOpen: true });
    for (const [id, name] of [
      ['tg', 'Telegram'],
      ['crm', 'CRM API'],
    ])
      expect(
        group(id)
          .querySelector('[role="radiogroup"], [role="group"]')
          ?.getAttribute('aria-label'),
      ).toBe(`${K}.toolLabel(tool=${name})`);
  });

  it('allows one action under Customize, leaving the tool choice mixed', async () => {
    updateAgent.mockResolvedValue({ ok: true });
    await render(agent());
    await expand();
    await customize('tg');
    await pick(rowSelect('tg', 'Telegram pin message'), `${P}.always`);
    expect(savedConfig().api_write_allowlist).toEqual([
      'tg:telegram_pin_message',
    ]);
    expect(rowSelect('tg', 'Telegram pin message').textContent).toBe(
      `${P}.always`,
    );
    expect(choice('tg', 'off').getAttribute('data-state')).toBe('off');
    expect(choice('tg', 'always').getAttribute('data-state')).toBe('off');
    expect(choice('tg', 'customize').getAttribute('data-state')).toBe('on');
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
    await act(async () => choice('tg', 'always').click());
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
    await act(async () => choice('tg', 'always').click());
    expect(choice('tg', 'off').getAttribute('data-state')).toBe('on');
    expect(summary()).toBe(`${K}.summaryNone`);
    expect(selectActionToast(store.getState())?.variant).toBe('destructive');
  });

  it('lists writes on stored credentials of tools without a connection', async () => {
    await render(agent({ tools: ['crm'] }), { defaultOpen: true });
    expect(groupTitles()).toEqual([titled('CRM API', 0, 1)]);
    await customize('crm');
    expect(rowNames('crm')).toEqual(['Create lead']);
  });

  it("lists a sponsor's tool the owner can't see, but not a stopped one", async () => {
    await render(agent({ tools: ['bob-jira', 'gone'] }), {
      defaultOpen: true,
    });
    expect(groupTitles()).toEqual([titled('Bob Jira', 0, 1)]);
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
    expect(groupTitles()).toEqual([titled('Node Slack', 0, 1)]);
  });

  it('renders nothing for an agent without connected tools', async () => {
    await render(agent({ tools: ['memory'] }));
    expect(container.textContent).toBe('');
  });
});
