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
const updateAgent = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    getUserTools: (...args: unknown[]) => getUserTools(...args),
    updateAgent: (...args: unknown[]) => updateAgent(...args),
  },
}));

import actionToastReducer, {
  selectActionToast,
} from '../notifications/actionToastSlice';
import { prefSlice } from '../preferences/preferenceSlice';
import ApiWriteAllowlist from './ApiWriteAllowlist';
import type { Agent } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const TOOLS = {
  tools: [
    {
      id: 'tg',
      displayName: 'Telegram',
      connection_id: 'c1',
      actions: [
        { name: 'telegram_send_message', access: 'write', active: true },
        { name: 'telegram_read', access: 'read', active: true },
      ],
    },
    {
      id: 'memory',
      displayName: 'Memory',
      connection_id: null,
      actions: [{ name: 'memory_write', access: 'write', active: true }],
    },
  ],
};

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
    updateAgent.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    a: Agent,
    onConfigChange = vi.fn(),
    getSavedConfig?: () => Agent['config'],
  ) => {
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

  it('lists only write actions on connected accounts, unchecked by default', async () => {
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

  it('renders nothing for an agent without connected tools', async () => {
    await render(agent({ tools: ['memory'] }));
    expect(container.textContent).toBe('');
  });
});
