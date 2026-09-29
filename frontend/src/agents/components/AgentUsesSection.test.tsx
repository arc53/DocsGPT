import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) =>
    selector({ preference: { token: 'tok' } }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (!opts) return key;
      const params = Object.entries(opts)
        .filter(([k]) => k !== 'defaultValue' && k !== 'interpolation')
        .map(([k, v]) => `${k}=${v}`)
        .join(',');
      return params ? `${key}(${params})` : key;
    },
    i18n: { language: 'en' },
  }),
}));

const getAgent = vi.fn();
const getWorkflow = vi.fn();
vi.mock('../../api/services/userService', () => ({
  default: {
    getAgent: (...a: unknown[]) => getAgent(...a),
    getWorkflow: (...a: unknown[]) => getWorkflow(...a),
  },
}));

import type { Agent, ResourceState } from '../types';
import AgentUsesSection from './AgentUsesSection';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const K = 'settings.teams.share.uses';

const ok = (body: unknown) => ({ ok: true, json: async () => body });

const item = (over: Partial<ResourceState>): ResourceState => ({
  key: `${over.type ?? 'tool'}:${over.id ?? 't1'}`,
  type: 'tool',
  id: 't1',
  name: 'Item',
  state: 'active',
  reason: null,
  ...over,
});

const agentWith = (
  states: ResourceState[],
  over: Partial<Agent> = {},
): Agent => ({
  id: 'a1',
  name: 'A',
  description: '',
  image: '',
  source: '',
  chunks: '6',
  retriever: '',
  prompt_id: '',
  tools: [],
  agent_type: 'classic',
  status: 'published',
  access: 'owner',
  allowed_actions: ['edit', 'share', 'use'],
  resource_states: states,
  ...over,
});

const flush = async () => {
  for (let i = 0; i < 6; i += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
};

describe('AgentUsesSection', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getAgent.mockReset();
    getWorkflow.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async (
    agent: Agent | null,
    readerId = 'me',
    onOpenAccessDetails?: () => void,
  ) => {
    getAgent.mockResolvedValue(agent ? ok(agent) : { ok: false });
    act(() => {
      root.render(
        <AgentUsesSection
          agentId="a1"
          readerId={readerId}
          onOpenAccessDetails={onOpenAccessDetails}
        />,
      );
    });
    await flush();
  };

  const toggle = () =>
    Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes(`${K}.title`),
    );

  const open = async () => {
    const button = toggle();
    if (button?.getAttribute('aria-expanded') === 'false') {
      act(() => button.click());
      await flush();
    }
  };

  const rowOf = (name: string) =>
    Array.from(container.querySelectorAll('li')).find((li) =>
      li.textContent?.includes(name),
    );

  it('starts collapsed and lists what the agent uses when opened', async () => {
    await render(agentWith([item({ name: 'Docs', type: 'source', id: 's1' })]));
    expect(toggle()?.getAttribute('aria-expanded')).toBe('false');
    expect(rowOf('Docs')).toBeUndefined();
    await open();
    expect(toggle()?.getAttribute('aria-expanded')).toBe('true');
    expect(rowOf('Docs')?.textContent).toContain(`${K}.access.you`);
  });

  it('names whose access each item runs with, for the owner', async () => {
    await render(
      agentWith([
        item({ id: 't1', name: 'Mine' }),
        item({
          id: 't2',
          name: 'Bobs',
          runs_as: { user_id: 'bob', label: 'bob@example.com' },
        }),
        item({
          id: 't3',
          name: 'Slack tool',
          credential_mode: 'member',
          note: 'per_user_account',
          connection: { id: 'c1', connector_key: 'slack', name: 'Slack' },
        }),
        item({
          id: 't4',
          name: 'Notion tool',
          credential_mode: 'owner',
          account: { user_id: 'me', label: 'me@example.com' },
          connection: { id: 'c2', connector_key: 'notion', name: 'Notion' },
        }),
        item({
          id: 't5',
          name: 'Jira tool',
          credential_mode: 'owner',
          account: { user_id: 'carol', label: 'carol@example.com' },
          connection: { id: 'c3', connector_key: 'jira', name: 'Jira' },
        }),
        item({ type: 'prompt', id: 'p1', name: 'Tone' }),
      ]),
    );
    await open();
    expect(rowOf('Mine')?.textContent).toContain(`${K}.access.you`);
    expect(rowOf('Bobs')?.textContent).toContain(
      `${K}.access.person(person=bob@example.com)`,
    );
    // API and widget callers run it as the owner: the owner's account.
    expect(rowOf('Slack tool')?.textContent).toContain(
      `${K}.access.member(service=Slack)`,
    );
    expect(rowOf('Notion tool')?.textContent).toContain(
      `${K}.access.yourAccount(service=Notion)`,
    );
    expect(rowOf('Jira tool')?.textContent).toContain(
      `${K}.access.personAccount(service=Jira,person=carol@example.com)`,
    );
    expect(rowOf('Tone')?.textContent).toContain(`${K}.access.you`);
  });

  it("says the owner's access to an editor, and theirs where they sponsor", async () => {
    await render(
      agentWith(
        [
          item({ id: 't1', name: 'Owners' }),
          item({
            id: 't2',
            name: 'Editors',
            runs_as: { user_id: 'me', label: 'me@example.com' },
          }),
          item({
            id: 't3',
            name: 'Slack tool',
            credential_mode: 'member',
            note: 'per_user_account',
            connection: { id: null, connector_key: 'slack', name: 'Slack' },
          }),
        ],
        { access: 'editor', allowed_actions: ['edit', 'share', 'use'] },
      ),
    );
    await open();
    expect(rowOf('Owners')?.textContent).toContain(`${K}.access.owner`);
    expect(rowOf('Editors')?.textContent).toContain(`${K}.access.you`);
    expect(rowOf('Slack tool')?.textContent).toContain(
      `${K}.access.memberShared(service=Slack)`,
    );
  });

  it('follows who it runs as now, not a sponsor on record', async () => {
    await render(
      agentWith([
        item({
          id: 't1',
          name: 'Once sponsored',
          sponsor: { user_id: 'bob', label: 'bob@example.com' },
          runs_as: null,
        }),
      ]),
    );
    await open();
    expect(rowOf('Once sponsored')?.textContent).toContain(`${K}.access.you`);
    expect(rowOf('Once sponsored')?.textContent).not.toContain('bob');
  });

  it('says someone else for a sponsor the reader does not know', async () => {
    await render(
      agentWith(
        [
          item({
            id: 't1',
            name: 'Runs as a stranger',
            sponsor: { user_id: null, label: null },
            runs_as: { user_id: null, label: null },
          }),
          item({
            id: 't2',
            name: 'Stopped',
            state: 'stopped',
            reason: 'sponsor_cannot_edit_agent',
            sponsor: { user_id: null, label: null },
          }),
        ],
        { access: 'editor', allowed_actions: ['edit', 'share', 'use'] },
      ),
    );
    await open();
    expect(rowOf('Runs as a stranger')?.textContent).toContain(
      `${K}.access.other`,
    );
    expect(rowOf('Stopped')?.textContent).toContain(
      'agents.form.resourceStates.reason.sponsorCannotEditAgentOther',
    );
  });

  it('reads the per_user_account note for a tool each person connects', async () => {
    await render(
      agentWith([
        item({
          id: 't1',
          name: 'Slack tool',
          credential_mode: 'member',
          note: 'per_user_account',
          connection: { id: 'c1', connector_key: 'slack', name: 'Slack' },
        }),
      ]),
    );
    await open();
    expect(rowOf('Slack tool')?.textContent).toContain(
      `${K}.access.member(service=Slack)`,
    );
  });

  it('names whose saved credentials a tool without a connection uses', async () => {
    await render(
      agentWith([
        item({
          id: 't1',
          name: 'My API',
          account: { user_id: 'me', label: 'me@example.com' },
        }),
        item({
          id: 't2',
          name: 'Carols API',
          account: { user_id: 'carol', label: 'carol@example.com' },
        }),
        item({
          id: 't3',
          name: 'Hidden API',
          account: { user_id: null, label: null },
        }),
        item({
          id: 't4',
          name: 'Hidden Jira',
          credential_mode: 'owner',
          account: { user_id: null, label: null },
          connection: { id: null, connector_key: 'jira', name: 'Jira' },
        }),
      ]),
    );
    await open();
    expect(rowOf('My API')?.textContent).toContain(
      `${K}.access.yourCredentials`,
    );
    expect(rowOf('Carols API')?.textContent).toContain(
      `${K}.access.personCredentials(person=carol@example.com)`,
    );
    expect(rowOf('Hidden API')?.textContent).toContain(
      `${K}.access.otherCredentials`,
    );
    expect(rowOf('Hidden Jira')?.textContent).toContain(
      `${K}.access.otherAccount(service=Jira)`,
    );
  });

  it('opens by itself and marks a stopped item with why it stopped', async () => {
    await render(
      agentWith([
        item({ id: 't1', name: 'Gone', state: 'stopped', reason: 'deleted' }),
        item({ id: 't2', name: 'Fine' }),
      ]),
    );
    expect(toggle()?.getAttribute('aria-expanded')).toBe('true');
    const gone = rowOf('Gone');
    expect(gone?.textContent).toContain(`${K}.stopped`);
    expect(gone?.textContent).toContain(
      'agents.form.resourceStates.reason.deleted(name=Gone',
    );
    expect(gone?.textContent).not.toContain(`${K}.access.you`);
    expect(rowOf('Fine')?.textContent).not.toContain(`${K}.stopped`);
  });

  it('flags writes outside callers cannot make until they are allowed', async () => {
    await render(
      agentWith(
        [
          item({
            id: 't1',
            name: 'Blocked',
            owner_credential_writes: ['send', 'delete'],
          }),
          item({
            id: 't2',
            name: 'Allowed',
            owner_credential_writes: ['send'],
          }),
          item({ id: 't3', name: 'Reads', owner_credential_writes: [] }),
        ],
        { config: { api_write_allowlist: ['t1:send', 't2:send'] } },
      ),
    );
    await open();
    // One of two writes still blocked: some, not all.
    expect(rowOf('Blocked')?.textContent).toContain(`${K}.writesSomeOff`);
    expect(rowOf('Allowed')?.textContent).not.toContain(`${K}.writes`);
    expect(rowOf('Reads')?.textContent).not.toContain(`${K}.writes`);
    const alert = container.querySelector('[data-slot="alert"]');
    expect(alert?.textContent).toContain(`${K}.writesNote`);
    expect(alert?.textContent).not.toContain(`${K}.writesNoteMemberTail`);
  });

  it('marks a tool with every write blocked', async () => {
    await render(
      agentWith([
        item({ id: 't1', name: 'Blocked', owner_credential_writes: ['a'] }),
      ]),
    );
    await open();
    expect(rowOf('Blocked')?.textContent).toContain(`${K}.writesOff`);
    expect(rowOf('Blocked')?.textContent).not.toContain(`${K}.writesSomeOff`);
  });

  it('names only API and widget users for tools each person connects', async () => {
    await render(
      agentWith([
        item({
          id: 't1',
          name: 'Slack tool',
          credential_mode: 'member',
          note: 'per_user_account',
          connection: { id: null, connector_key: 'slack', name: 'Slack' },
          owner_credential_writes: ['send'],
        }),
      ]),
    );
    await open();
    const alert = container.querySelector('[data-slot="alert"]');
    expect(alert?.textContent).toBe(`${K}.writesNoteApi`);
  });

  it('says public-link users use their own account on mixed tools', async () => {
    await render(
      agentWith([
        item({ id: 't1', name: 'Mine', owner_credential_writes: ['a'] }),
        item({
          id: 't2',
          name: 'Slack tool',
          credential_mode: 'member',
          note: 'per_user_account',
          owner_credential_writes: ['send'],
        }),
      ]),
    );
    await open();
    const alert = container.querySelector('[data-slot="alert"]');
    expect(alert?.textContent).toBe(
      `${K}.writesNote ${K}.writesNoteMemberTail`,
    );
  });

  it('says when an admin turned changes off', async () => {
    await render(
      agentWith([
        item({
          id: 't1',
          name: 'GitHub tool',
          writes_allowed: false,
          owner_credential_writes: [],
        }),
      ]),
    );
    await open();
    expect(rowOf('GitHub tool')?.textContent).toContain(`${K}.adminOff`);
    expect(container.querySelector('[data-slot="alert"]')).toBeNull();
  });

  it('tells an editor the owner allows the writes', async () => {
    await render(
      agentWith(
        [item({ id: 't1', name: 'Blocked', owner_credential_writes: ['x'] })],
        { access: 'editor', allowed_actions: ['edit', 'share'] },
      ),
    );
    await open();
    expect(
      container.querySelector('[data-slot="alert"]')?.textContent,
    ).toContain(`${K}.writesNoteEditor`);
  });

  it('shows no writes note when every write is allowed', async () => {
    await render(
      agentWith([
        item({ id: 't1', name: 'Plain', owner_credential_writes: [] }),
      ]),
    );
    await open();
    expect(container.querySelector('[data-slot="alert"]')).toBeNull();
  });

  // "Allow" on a connector is the in-chat permission; the badge is about
  // the agent's own API write allowlist, so only that list clears it.
  it('drops the badge and the note once the write is on the allowlist', async () => {
    const linear = item({
      id: 'lin',
      name: 'Linear',
      connection: { id: 'c1', connector_key: 'mcp:linear', name: 'Linear' },
      credential_mode: 'owner',
      owner_credential_writes: ['create_issue'],
    });
    await render(agentWith([linear]));
    await open();
    expect(rowOf('Linear')?.textContent).toContain(`${K}.writesOff`);

    act(() => root.unmount());
    root = createRoot(container);
    await render(
      agentWith([linear], {
        config: { api_write_allowlist: ['LIN:create_issue'] },
      }),
    );
    await open();
    expect(rowOf('Linear')?.textContent).not.toContain(`${K}.writes`);
    expect(container.querySelector('[data-slot="alert"]')).toBeNull();
  });

  it('opens Access details from the note for the owner', async () => {
    const openDetails = vi.fn();
    await render(
      agentWith([
        item({ id: 't1', name: 'Blocked', owner_credential_writes: ['x'] }),
      ]),
      'me',
      openDetails,
    );
    await open();
    const button = Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-slot="alert"] button',
      ),
    ).find((b) => b.textContent === `${K}.openAccessDetails`);
    expect(button).toBeDefined();
    act(() => button!.click());
    expect(openDetails).toHaveBeenCalledTimes(1);
  });

  // Access details lists the writes only once the agent has an API key, so
  // without one the note says to create it there first.
  it('says the allowlist needs an API key when the agent has none', async () => {
    const blocked = [
      item({ id: 't1', name: 'Blocked', owner_credential_writes: ['x'] }),
    ];
    await render(agentWith(blocked), 'me', vi.fn());
    await open();
    const alert = () => container.querySelector('[data-slot="alert"]');
    expect(alert()?.textContent).toContain(`${K}.accessDetailsNeedsKey`);

    act(() => root.unmount());
    root = createRoot(container);
    await render(agentWith(blocked, { key: 'abcd...wxyz' }), 'me', vi.fn());
    await open();
    expect(alert()?.textContent).not.toContain(`${K}.accessDetailsNeedsKey`);
    expect(alert()?.textContent).toContain(`${K}.openAccessDetails`);
  });

  it('offers no Access details button to an editor or without a way there', async () => {
    const blocked = [
      item({ id: 't1', name: 'Blocked', owner_credential_writes: ['x'] }),
    ];
    await render(
      agentWith(blocked, { access: 'editor', allowed_actions: ['edit'] }),
      'me',
      vi.fn(),
    );
    await open();
    expect(container.querySelector('[data-slot="alert"] button')).toBeNull();

    act(() => root.unmount());
    root = createRoot(container);
    await render(agentWith(blocked));
    await open();
    expect(container.querySelector('[data-slot="alert"] button')).toBeNull();
  });

  it('includes the resources of a workflow agent’s nodes', async () => {
    getWorkflow.mockResolvedValue(
      ok({
        success: true,
        data: {
          resource_states: [
            item({ id: 'n1', name: 'Node tool' }),
            item({ id: 't1', name: 'Shared tool' }),
          ],
        },
      }),
    );
    await render(
      agentWith([item({ id: 't1', name: 'Shared tool' })], {
        agent_type: 'workflow',
        workflow: 'w1',
      }),
    );
    await open();
    expect(getWorkflow).toHaveBeenCalledWith('w1', 'tok');
    expect(rowOf('Node tool')).toBeDefined();
    expect(
      Array.from(container.querySelectorAll('li')).filter((li) =>
        li.textContent?.includes('Shared tool'),
      ),
    ).toHaveLength(1);
  });

  it('renders nothing for someone who may not edit the agent', async () => {
    await render(
      agentWith([item({ name: 'Hidden' })], {
        access: 'viewer',
        allowed_actions: ['use'],
      }),
    );
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing when the agent uses nothing listed', async () => {
    await render(agentWith([]));
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing when the agent fails to load', async () => {
    await render(null);
    expect(container.innerHTML).toBe('');
  });
});
