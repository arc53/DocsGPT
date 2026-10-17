import { configureStore } from '@reduxjs/toolkit';
import { act, type ReactNode } from 'react';
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

/** A heading as "title [count]": SectionHeader draws the count in its own span. */
const titleWithCount = (h: Element | null | undefined) =>
  h
    ? `${h.firstChild?.textContent} [${h.querySelector('[data-slot="count"]')?.textContent}]`
    : undefined;

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

  const render = async (
    value: ConnectionTool,
    children?: ReactNode,
    groupHeadingAs?: 'h4' | 'h5' | 'h6',
  ) => {
    const s = store();
    await act(async () => {
      root.render(
        <Provider store={s}>
          <ToolPermissions
            connectionId="conn-1"
            tool={value}
            groupHeadingAs={groupHeadingAs}
          >
            {children}
          </ToolPermissions>
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
  const customize = async (access: 'read' | 'write') =>
    act(async () => choice(access, 'customize').click());
  const rowSelect = (label: string) =>
    Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="select-trigger"]'),
    ).find(
      (el) =>
        el
          .getAttribute('aria-label')
          ?.startsWith('settings.connectors.permission.label') &&
        el.closest('li')?.textContent?.includes(label),
    );

  it('titles each group with its count, not an eyebrow', async () => {
    await render(
      tool([
        action('get_issue', 'read', 'always'),
        action('b', 'write', 'ask'),
      ]),
    );
    const titles = Array.from(container.querySelectorAll('h4')).map(
      titleWithCount,
    );
    expect(titles).toEqual([
      'settings.connectors.capabilityPlain.read [1]',
      'settings.connectors.capabilityPlain.write [1]',
    ]);
    expect(container.querySelector('h4')?.className).not.toContain('uppercase');
    expect(container.textContent).not.toContain(
      'settings.connectors.permission.actionCount',
    );
  });

  it('takes the heading level of the surface it sits in', async () => {
    await render(tool([action('b', 'write', 'ask')]), undefined, 'h6');
    expect(container.querySelector('h4')).toBeNull();
    expect(titleWithCount(container.querySelector('h6'))).toBe(
      'settings.connectors.capabilityPlain.write [1]',
    );
  });

  it('opens the parameters with a toggle named for its action', async () => {
    await render(
      tool([
        action('telegram_send_message', 'write', 'ask', [param('text', false)]),
      ]),
    );
    await customize('write');
    const toggle = button('settings.connectors.parameters.show');
    expect(toggle.getAttribute('aria-label')).toBe(
      'settings.connectors.parameters.showFor',
    );
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    await act(async () => toggle.click());
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(container.querySelector('[data-parameter="text"]')).not.toBeNull();
  });

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

  it('presses Customize and lists each action when they differ', async () => {
    await render(
      tool([
        action('a_one', 'write', 'ask'),
        action('b_one', 'write', 'always'),
      ]),
    );
    for (const permission of ['always', 'ask', 'off'])
      expect(choice('write', permission).getAttribute('data-state')).toBe(
        'off',
      );
    expect(choice('write', 'customize').getAttribute('data-state')).toBe('on');
    expect(rowSelect('A one')?.textContent).toBe(
      'settings.connectors.permission.ask',
    );
    expect(rowSelect('B one')?.textContent).toBe(
      'settings.connectors.permission.always',
    );
  });

  it('folds the actions until Customize, whatever the length', async () => {
    await render(tool([action('get_issue', 'read', 'always')]));
    expect(container.textContent).not.toContain('Get issue');
    expect(choice('read', 'always').getAttribute('data-state')).toBe('on');
    await customize('read');
    expect(choice('read', 'customize').getAttribute('data-state')).toBe('on');
    expect(choice('read', 'always').getAttribute('data-state')).toBe('off');
    expect(container.textContent).toContain('Get issue');
    expect(container.textContent).toContain('Does get_issue.');
    // No separate fold link: the group choice folds them again.
    expect(
      Array.from(container.querySelectorAll('button')).some((b) =>
        b.textContent?.includes('settings.connectors.permission.fold'),
      ),
    ).toBe(false);
    await act(async () => choice('read', 'always').click());
    expect(container.textContent).not.toContain('Get issue');
    // It already was: nothing to save.
    expect(connectors.setToolPermissions).not.toHaveBeenCalled();
  });

  it('keeps the actions open after one row changes', async () => {
    await render(
      tool([
        action('a_one', 'write', 'ask'),
        action('b_one', 'write', 'always'),
      ]),
    );
    const trigger = rowSelect('B one')!;
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', {
          bubbles: true,
          button: 0,
          pointerType: 'mouse',
        }),
      );
    });
    const ask = Array.from(
      document.body.querySelectorAll<HTMLElement>('[role="option"]'),
    ).find((o) => o.textContent === 'settings.connectors.permission.ask')!;
    await act(async () => ask.click());
    expect(connectors.setToolPermissions).toHaveBeenCalledWith(
      'conn-1',
      'tool-1',
      { b_one: 'ask' },
      null,
    );
    // Both agree now, but the rows the user is editing stay.
    expect(choice('write', 'customize').getAttribute('data-state')).toBe('on');
    expect(container.textContent).toContain('B one');
  });

  it('renders what it is given inside its card, above the groups', async () => {
    await render(
      tool([action('create_issue', 'write', 'ask')]),
      <p data-testid="extra">Extra row</p>,
    );
    const extra = container.querySelector('[data-testid="extra"]')!;
    const card = container.querySelector('[data-slot="card"]')!;
    expect(card.contains(extra)).toBe(true);
    expect(
      extra.compareDocumentPosition(group('write')) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('follows the tool when its actions change', async () => {
    await render(tool([action('old_one', 'read', 'always')]));
    await customize('read');
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
    await customize('write');
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
    await customize('write');
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
    await customize('write');
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
    await customize('write');
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

  it('leaves the explanation to the drawer: no footnote in the card', async () => {
    await render(tool([action('create_issue', 'write', 'ask')]));
    expect(container.textContent).not.toContain(
      'settings.connectors.permission.hint',
    );
  });
});
