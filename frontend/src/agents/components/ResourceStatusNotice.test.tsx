import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import type { Agent, ResourceSponsor, ResourceState } from '../types';
import ResourceStatusNotice, {
  unnamedResourceLabel,
} from './ResourceStatusNotice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const baseAgent: Agent = {
  name: 'A',
  description: 'd',
  image: '',
  source: '',
  chunks: '6',
  retriever: '',
  prompt_id: 'default',
  tools: [],
  agent_type: 'classic',
  status: 'published',
};

const editorAgent: Agent = {
  ...baseAgent,
  access: 'editor',
  allowed_actions: ['edit'],
};

const sponsor = (over: Partial<ResourceSponsor>): ResourceSponsor => ({
  type: 'tool',
  id: 't1',
  user_id: 'bob',
  label: 'bob@example.com',
  active: true,
  ...over,
});

const stoppedItem = (over: Partial<ResourceState>): ResourceState => ({
  key: 'tool:t1',
  type: 'tool',
  id: 't1',
  state: 'stopped',
  reason: 'deleted',
  ...over,
});

describe('ResourceStatusNotice', () => {
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

  const handlers = () => ({
    onTakeOver: vi.fn(),
    onUndoTakeover: vi.fn(),
    onRemove: vi.fn(),
    onReconnect: vi.fn(),
  });

  const render = async (
    agent: Agent,
    stopped: ResourceState[] = [],
    takeovers: string[] = [],
  ) => {
    const spies = handlers();
    await act(async () => {
      root.render(
        <ResourceStatusNotice
          agent={agent}
          stopped={stopped}
          resolveName={(item) => item.name || `name-${item.id}`}
          takeovers={takeovers}
          {...spies}
        />,
      );
    });
    return spies;
  };

  const buttons = () => Array.from(container.querySelectorAll('button'));
  const buttonWith = (text: string) =>
    buttons().filter((b) => b.textContent?.includes(text));
  const alerts = () =>
    Array.from(container.querySelectorAll('[data-slot="alert"]'));

  it('renders nothing when everything runs', async () => {
    await render(baseAgent);
    expect(container.innerHTML).toBe('');
  });

  // The sponsor confirmation asks before anything runs with an editor's
  // access, and the pickers say who added what: the notice is only the
  // stopped warning.
  it('shows no attach note or who added what, only stopped items', async () => {
    await render({
      ...editorAgent,
      shared: true,
      resource_sponsors: [sponsor({ id: 't1' })],
    });
    expect(container.innerHTML).toBe('');

    await render(
      { ...editorAgent, resource_sponsors: [sponsor({ id: 't1' })] },
      [stoppedItem({ key: 'source:s1', type: 'source', id: 's1' })],
    );
    expect(alerts()).toHaveLength(1);
    const [stopped] = alerts();
    expect(stopped.getAttribute('data-variant')).toBe('warning');
    expect(stopped.textContent).toContain('agents.form.resourceStates.title');
    expect(stopped.textContent).not.toContain('agents.form.sponsors');
    expect(stopped.querySelectorAll('li')).toHaveLength(1);
  });

  it('names people by email or a short id, the reader as you', async () => {
    const LONG_SUB = '0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0';
    await i18n.use(initReactI18next).init({
      lng: 'jp',
      resources: {
        jp: {
          translation: {
            agents: {
              form: {
                resourceStates: {
                  reason: {
                    sponsorCannotEditAgent: 'agent:{{name}}:{{person}}',
                    sponsorCannotEditItemYou: 'itemYou:{{name}}',
                  },
                  ask: { signInAgain: 'ask:{{person}}' },
                },
              },
            },
          },
        },
      },
    });
    try {
      await act(async () => {
        root.render(
          <ResourceStatusNotice
            agent={baseAgent}
            readerId="me"
            resolveName={(item) => item.name || `name-${item.id}`}
            stopped={[
              stoppedItem({
                reason: 'sponsor_cannot_edit_agent',
                sponsor: { user_id: LONG_SUB, label: LONG_SUB },
              }),
              stoppedItem({
                key: 'tool:t2',
                id: 't2',
                reason: 'sponsor_cannot_edit_resource',
                sponsor: { user_id: 'me', label: 'me@example.com' },
              }),
              stoppedItem({
                key: 'tool:t3',
                id: 't3',
                reason: 'connection_needs_reconnect',
                contact: { user_id: 'bob', label: 'bob@example.com' },
              }),
            ]}
          />,
        );
      });
      const [agentRow, itemRow, askRow] = Array.from(
        container.querySelectorAll('li'),
      );
      expect(agentRow.textContent).toContain(
        'agent:name-t1:0f1e2d3c-4b5…c3d2e1f0',
      );
      expect(itemRow.textContent).toContain('itemYou:name-t2');
      expect(askRow.textContent).toContain('ask:bob@example.com');
    } finally {
      await i18n.changeLanguage('en');
    }
  });

  it('drops the service from the reason when the tool is named after it', async () => {
    const linear = { id: 'c1', connector_key: 'mcp:linear', name: 'Linear' };
    await render(baseAgent, [
      stoppedItem({
        name: 'Linear',
        reason: 'connection_needs_reconnect',
        connection: linear,
      }),
      stoppedItem({
        key: 'tool:t2',
        id: 't2',
        name: 'Create issue',
        reason: 'connection_needs_reconnect',
        connection: linear,
      }),
      stoppedItem({
        key: 'tool:t3',
        id: 't3',
        name: 'Ops',
        reason: 'connection_removed',
        connection: null,
      }),
      stoppedItem({
        key: 'tool:t4',
        id: 't4',
        name: 'linear',
        reason: 'connector_disabled',
        connection: linear,
      }),
    ]);
    const [same, other, none, disabled] = Array.from(
      container.querySelectorAll('li'),
    ).map((li) => li.textContent ?? '');
    expect(same).toContain('reason.connectionNeedsReconnectNoService');
    expect(other).toMatch(/reason\.connectionNeedsReconnect(?!NoService)/);
    expect(none).toContain('reason.connectionRemovedNoService');
    expect(disabled).toContain('reason.connectorDisabledNoService');
  });

  it.each([
    ['deleted', 'reason.deleted'],
    ['sponsor_cannot_edit_agent', 'reason.sponsorCannotEditAgent'],
    ['sponsor_cannot_edit_resource', 'reason.sponsorCannotEditItem'],
    ['connection_needs_reconnect', 'reason.connectionNeedsReconnect'],
    ['connection_removed', 'reason.connectionRemoved'],
    ['connector_disabled', 'reason.connectorDisabled'],
  ] as const)('says why an item stopped: %s', async (reason, key) => {
    await render(baseAgent, [stoppedItem({ reason })]);
    expect(container.textContent).toContain(
      `agents.form.resourceStates.${key}`,
    );
  });

  it('says someone else for a sponsor the reader does not know', async () => {
    await render(
      {
        ...editorAgent,
        resource_sponsors: [
          sponsor({ id: 't1', user_id: null, label: null }),
          sponsor({ id: 't2', user_id: null, label: null }),
        ],
      },
      [
        stoppedItem({
          reason: 'sponsor_cannot_edit_resource',
          sponsor: { user_id: null, label: null },
        }),
        stoppedItem({
          key: 'tool:t3',
          id: 't3',
          reason: 'sponsor_cannot_edit_agent',
          sponsor: { user_id: 'bob', label: 'bob@example.com' },
        }),
      ],
    );
    const text = container.textContent ?? '';
    expect(text).toContain(
      'agents.form.resourceStates.reason.sponsorCannotEditItemOther',
    );
    // A sponsor the reader knows is named.
    expect(text).toMatch(/reason\.sponsorCannotEditAgent(?!Other)/);
  });

  it('tells the owner they lost access, and an editor that the owner did', async () => {
    const item = stoppedItem({ reason: 'owner_lost_access' });
    await render(baseAgent, [item]);
    expect(container.textContent).toContain('reason.ownerLostAccessYou');
    await render(editorAgent, [item]);
    expect(container.textContent).not.toContain('reason.ownerLostAccessYou');
    expect(container.textContent).toContain('reason.ownerLostAccess');
  });

  it('says whom to ask when the reader cannot fix it', async () => {
    await render(baseAgent, [
      stoppedItem({
        key: 'source:s1',
        type: 'source',
        id: 's1',
        reason: 'owner_lost_access',
        contact: { user_id: 'carol', label: 'carol@example.com' },
      }),
      stoppedItem({ key: 'tool:t2', id: 't2', reason: 'connector_disabled' }),
      stoppedItem({ key: 'tool:t3', id: 't3', reason: 'deleted' }),
    ]);
    const [shareAgain, admin, deleted] = Array.from(
      container.querySelectorAll('li'),
    );
    expect(shareAgain.textContent).toContain(
      'agents.form.resourceStates.ask.shareAgain',
    );
    expect(admin.textContent).toContain('agents.form.resourceStates.ask.admin');
    expect(deleted.textContent).not.toContain('agents.form.resourceStates.ask');
  });

  it("asks the item's owner without naming them when the reader may not know them", async () => {
    await render(editorAgent, [
      stoppedItem({
        reason: 'owner_lost_access',
        contact: null,
        contact_role: 'resource_owner',
      }),
      stoppedItem({
        key: 'tool:t2',
        id: 't2',
        reason: 'connection_needs_reconnect',
        contact: null,
        contact_role: 'resource_owner',
      }),
      stoppedItem({
        key: 'tool:t3',
        id: 't3',
        reason: 'connection_removed',
        contact: null,
        contact_role: 'resource_owner',
      }),
    ]);
    const [lost, reconnect, removed] = Array.from(
      container.querySelectorAll('li'),
    );
    expect(lost.textContent).toContain(
      'agents.form.resourceStates.ask.shareAgainOwner',
    );
    expect(reconnect.textContent).toContain(
      'agents.form.resourceStates.ask.signInAgainOwner',
    );
    expect(removed.textContent).toContain(
      'agents.form.resourceStates.ask.connectAgainOwner',
    );
  });

  it('names a nameless item by its kind and a short id', () => {
    const t = ((key: string, options?: Record<string, string>) =>
      `${key}|${options?.id}`) as never;
    expect(
      unnamedResourceLabel(t, {
        type: 'source',
        id: '0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0',
      }),
    ).toBe('agents.form.resourceStates.unnamed.source|0f1e2d3c');
  });

  it('notes that a stopped prompt falls back to the default', async () => {
    await render(baseAgent, [
      stoppedItem({ key: 'prompt:p1', type: 'prompt', id: 'p1' }),
    ]);
    expect(container.textContent).toContain(
      'agents.form.resourceStates.promptFallback',
    );
  });

  it('offers Reconnect only when the reader owns the connection', async () => {
    const connection = { id: 'c1', connector_key: 'telegram', name: 'Tg' };
    const spies = await render(baseAgent, [
      stoppedItem({
        reason: 'connection_needs_reconnect',
        connection,
        can_reconnect: true,
      }),
      stoppedItem({
        key: 'tool:t2',
        id: 't2',
        reason: 'connection_needs_reconnect',
        connection,
        can_reconnect: false,
        contact: { user_id: 'bob', label: 'bob@example.com' },
      }),
    ]);
    const reconnect = buttonWith('settings.connectors.status.reconnect');
    expect(reconnect).toHaveLength(1);
    await act(async () => reconnect[0].click());
    expect(spies.onReconnect).toHaveBeenCalledWith(
      expect.objectContaining({ key: 'tool:t1' }),
    );
    expect(container.textContent).toContain(
      'agents.form.resourceStates.ask.signInAgain',
    );
  });

  it('offers a take-over only for items the reader may confirm', async () => {
    const spies = await render(editorAgent, [
      stoppedItem({ reason: 'sponsor_cannot_edit_agent', can_confirm: true }),
      stoppedItem({
        key: 'tool:t2',
        id: 't2',
        reason: 'sponsor_cannot_edit_agent',
        can_confirm: false,
      }),
    ]);
    const takeOver = buttonWith('agents.form.sponsors.takeOver');
    expect(takeOver).toHaveLength(1);
    // A short label that fits a phone; the item is in the accessible name.
    expect(takeOver[0].textContent).toBe('agents.form.sponsors.takeOver');
    expect(takeOver[0].getAttribute('aria-label')).toBe(
      'agents.form.sponsors.takeOverLabel',
    );
    await act(async () => takeOver[0].click());
    expect(spies.onTakeOver).toHaveBeenCalledWith(
      expect.objectContaining({ key: 'tool:t1' }),
    );
  });

  it('shows a pending take-over with an undo', async () => {
    const spies = await render(
      editorAgent,
      [stoppedItem({ reason: 'owner_lost_access', can_confirm: true })],
      ['tool:t1'],
    );
    expect(container.textContent).toContain(
      'agents.form.sponsors.takeOverPending',
    );
    await act(async () =>
      buttonWith('agents.form.sponsors.undoTakeOver')[0].click(),
    );
    expect(spies.onUndoTakeover).toHaveBeenCalledWith('tool:t1');
  });

  it('removes an item', async () => {
    const spies = await render(baseAgent, [stoppedItem({})]);
    const [remove] = buttonWith('agents.form.resourceStates.remove');
    expect(remove.getAttribute('aria-label')).toBe(
      'agents.form.resourceStates.removeLabel',
    );
    await act(async () => remove.click());
    expect(spies.onRemove).toHaveBeenCalledWith(
      expect.objectContaining({ key: 'tool:t1' }),
    );
  });

  it('closes from inside the warning and caps the list in its own scroller', async () => {
    const onClose = vi.fn();
    await act(async () => {
      root.render(
        <ResourceStatusNotice
          agent={baseAgent}
          stopped={[stoppedItem({})]}
          resolveName={(item) => item.id}
          onClose={onClose}
        />,
      );
    });
    const [alert] = alerts();
    const close = alert.querySelector<HTMLButtonElement>(
      '[aria-label="agents.close"]',
    );
    expect(close).not.toBeNull();
    const list = alert.querySelector('ul')!;
    expect(list.parentElement!.className).toContain('overflow-y-auto');
    expect(list.parentElement!.className).toContain('scrollbar-overlay');
    await act(async () => close!.click());
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('has no close button in the form', async () => {
    await render(baseAgent, [stoppedItem({})]);
    expect(container.querySelector('[aria-label="agents.close"]')).toBeNull();
  });
});
