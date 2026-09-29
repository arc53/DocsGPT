import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts?.count !== undefined ? `${key}:${opts.count}` : key,
  }),
}));

const connectors = vi.hoisted(() => ({
  setToolPermissions: vi.fn(),
  setToolParameters: vi.fn(),
}));
vi.mock('../api/services/connectorsService', () => ({ default: connectors }));

import actionToastReducer from '../notifications/actionToastSlice';
import ToolPermissions from './ToolPermissions';
import type { ActionParameter, ConnectionTool } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const action = (
  name: string,
  access: 'read' | 'write',
  permission: 'always' | 'ask' | 'off',
  parameters: ActionParameter[] = [],
) => ({ name, access, permission, description: `Does ${name}.`, parameters });

const param = (
  name: string,
  fixed: boolean,
  value: ActionParameter['value'] = null,
): ActionParameter => ({
  name,
  description: `The ${name}.`,
  type: 'string',
  required: false,
  fixed,
  value,
});

const tool = (actions: ReturnType<typeof action>[]): ConnectionTool =>
  ({
    id: 'tool-1',
    name: 'mcp_tool',
    display_name: 'Linear',
    status: true,
    credential_mode: 'owner',
    actions,
  }) as ConnectionTool;

const MANY_READS = Array.from({ length: 8 }, (_, i) =>
  action(`get_issue_${i}`, 'read', 'always'),
);

describe('ToolPermissions', () => {
  let container: HTMLDivElement;
  let root: Root;
  const store = () =>
    configureStore({
      reducer: {
        actionToast: actionToastReducer,
        preference: (state = { token: null }) => state,
      },
    });

  beforeEach(() => {
    connectors.setToolPermissions.mockReset();
    connectors.setToolPermissions.mockImplementation(async () => ({
      success: true,
      tool: tool([]),
    }));
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (value: ConnectionTool) => {
    const s = store();
    await act(async () => {
      root.render(
        <Provider store={s}>
          <ToolPermissions connectionId="conn-1" tool={value} />
        </Provider>,
      );
    });
  };

  const group = (access: 'read' | 'write') =>
    container.querySelector<HTMLElement>(`[data-access="${access}"]`)!;
  const choice = (access: 'read' | 'write', permission: string) =>
    group(access).querySelector<HTMLButtonElement>(
      `[data-permission="${permission}"]`,
    )!;

  it('sets every read at once', async () => {
    await render(tool([...MANY_READS, action('create_issue', 'write', 'ask')]));
    await act(async () => choice('read', 'ask').click());
    expect(connectors.setToolPermissions).toHaveBeenCalledWith(
      'conn-1',
      'tool-1',
      Object.fromEntries(MANY_READS.map((a) => [a.name, 'ask'])),
      null,
    );
    expect(choice('read', 'ask').getAttribute('data-state')).toBe('on');
    // Writes are untouched.
    expect(choice('write', 'ask').getAttribute('data-state')).toBe('on');
  });

  it('shows no group choice when its actions differ', async () => {
    await render(
      tool([action('a', 'write', 'ask'), action('b', 'write', 'always')]),
    );
    for (const permission of ['always', 'ask', 'off'])
      expect(choice('write', permission).getAttribute('data-state')).toBe(
        'off',
      );
  });

  it('keeps a long list folded, then lists actions in words with what they do', async () => {
    await render(tool(MANY_READS));
    expect(container.textContent).not.toContain('Get issue 0');
    const customize = Array.from(container.querySelectorAll('button')).find(
      (b) =>
        b.textContent?.startsWith('settings.connectors.permission.customize'),
    )!;
    await act(async () => customize.click());
    expect(container.textContent).toContain('Get issue 0');
    expect(container.textContent).toContain('Does get_issue_0.');
  });

  it('follows the tool when its actions change', async () => {
    await render(tool([action('old_one', 'read', 'always')]));
    await render(tool([action('new_one', 'read', 'always')]));
    expect(container.textContent).toContain('New one');
    expect(container.textContent).not.toContain('Old one');
  });

  const button = (text: string) =>
    Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === text,
    )!;
  const typeInto = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!;
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  };

  it('marks an action that has fixed values', async () => {
    await render(
      tool([
        action('telegram_send_message', 'write', 'ask', [
          param('text', false),
          param('chat_id', true, '-100'),
        ]),
      ]),
    );
    expect(container.textContent).toContain(
      'settings.connectors.parameters.fixedCount:1',
    );
  });

  it('fixes a parameter to a value the AI cannot change', async () => {
    const send = action('telegram_send_message', 'write', 'ask', [
      param('text', false),
      param('chat_id', false),
    ]);
    connectors.setToolParameters.mockResolvedValue({
      success: true,
      tool: tool([
        {
          ...send,
          parameters: [param('text', false), param('chat_id', true, '-100')],
        },
      ]),
    });
    await render(tool([send]));
    await act(async () =>
      button('settings.connectors.parameters.show').click(),
    );
    const row = container.querySelector<HTMLElement>(
      '[data-parameter="chat_id"]',
    )!;
    await act(async () =>
      row.querySelector<HTMLButtonElement>('[data-mode="fixed"]')!.click(),
    );
    const input = row.querySelector<HTMLInputElement>('input')!;
    await act(async () => typeInto(input, '-100'));
    await act(async () =>
      button('settings.connectors.parameters.save').click(),
    );
    expect(connectors.setToolParameters).toHaveBeenCalledWith(
      'conn-1',
      'tool-1',
      'telegram_send_message',
      { chat_id: '-100' },
      null,
    );
    expect(container.textContent).toContain(
      'settings.connectors.parameters.fixedCount:1',
    );
  });

  it('lets the AI decide a fixed parameter again', async () => {
    connectors.setToolParameters.mockResolvedValue({
      success: true,
      tool: tool([]),
    });
    await render(
      tool([
        action('telegram_send_message', 'write', 'ask', [
          param('chat_id', true, '-100'),
        ]),
      ]),
    );
    await act(async () =>
      button('settings.connectors.parameters.show').click(),
    );
    const row = container.querySelector<HTMLElement>(
      '[data-parameter="chat_id"]',
    )!;
    expect(row.querySelector<HTMLInputElement>('input')!.value).toBe('-100');
    await act(async () =>
      row.querySelector<HTMLButtonElement>('[data-mode="ai"]')!.click(),
    );
    expect(connectors.setToolParameters).toHaveBeenCalledWith(
      'conn-1',
      'tool-1',
      'telegram_send_message',
      { chat_id: null },
      null,
    );
  });

  it('shows a chat the account sets as set there, not as a choice', async () => {
    await render(
      tool([
        action('telegram_send_message', 'write', 'ask', [
          { ...param('chat_id', true, '-100'), set_by: 'account' },
        ]),
      ]),
    );
    await act(async () =>
      button('settings.connectors.parameters.show').click(),
    );
    const row = container.querySelector<HTMLElement>(
      '[data-parameter="chat_id"]',
    )!;
    expect(row.textContent).toContain(
      'settings.connectors.parameters.fromAccount',
    );
    expect(row.querySelector('[data-mode]')).toBeNull();
  });

  it('says what Ask first means outside chat', async () => {
    await render(tool([action('create_issue', 'write', 'ask')]));
    expect(container.textContent).toContain(
      'settings.connectors.permission.hint',
    );
  });
});
