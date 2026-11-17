import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

const mockState = {
  preference: { token: 'tok' as string | null },
  teams: {
    teams: [
      { id: 't1', name: 'Operations', slug: 'ops', owner_id: 'u1' },
      { id: 't2', name: 'Dev', slug: 'dev', owner_id: 'u1' },
    ],
  },
  workspace: {
    current: 'personal',
    workspaces: [
      { id: 'personal', kind: 'personal', name: 'Personal' },
      { id: 't1', kind: 'team', name: 'Operations', role: 'editor' },
      { id: 't2', kind: 'team', name: 'Dev', role: 'viewer' },
    ],
    loaded: true,
    loading: false,
    epoch: 0,
    lastReason: null,
    latestRequestId: null,
  },
};

vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) => selector(mockState),
  useDispatch: () => () => undefined,
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
  }),
}));

const listResourceShares = vi.fn();
const getResourceSettings = vi.fn();
const listMembers = vi.fn();
const share = vi.fn();
const shareTeamItem = vi.fn();
const unshareTeamItem = vi.fn();

// The real error helpers (codes, refusal bodies); only the calls are faked.
vi.mock('../api/services/teamsService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/services/teamsService')>()),
  default: {
    listResourceShares: (...a: unknown[]) => listResourceShares(...a),
    getResourceSettings: (...a: unknown[]) => getResourceSettings(...a),
    updateResourceSettings: vi.fn(),
    listMembers: (...a: unknown[]) => listMembers(...a),
    share: (...a: unknown[]) => share(...a),
    unshare: vi.fn(),
    shareTeamItem: (...a: unknown[]) => shareTeamItem(...a),
    unshareTeamItem: (...a: unknown[]) => unshareTeamItem(...a),
  },
}));

vi.mock('../agents/components/AgentUsesSection', () => ({
  default: () => null,
}));

vi.mock('../workspace/move/MoveToWorkspaceModal', () => ({
  default: (props: { initialTeamId?: string; subject: { id: string } }) => (
    <div data-testid="move-dialog">
      {props.subject.id}:{props.initialTeamId}
    </div>
  ),
}));

vi.mock('../utils/dateTimeUtils', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../utils/dateTimeUtils')>()),
  formatCount: (value: number) => `#${value}`,
}));

import { TeamsApiError } from '../api/services/teamsService';
import ShareToTeamModal from './ShareToTeamModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const flush = async () => {
  for (let i = 0; i < 6; i += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
};

const body = () => document.body;
const text = () => body().textContent ?? '';
const buttonByText = (label: string) =>
  Array.from(body().querySelectorAll('button')).find(
    (b) => b.textContent?.trim() === label,
  );

const ADMIN_ACTIONS = ['use', 'edit', 'share_outside'];

// An Operations item as an Admin of Operations reads its share dialog.
const teamItem = (over: Record<string, unknown> = {}) => ({
  success: true,
  shares: [],
  workspace: { kind: 'team', team_id: 't1', name: 'Operations' },
  members_count: 6,
  access: 'admin',
  team_role: 'admin',
  origin: 'team',
  allowed_actions: ADMIN_ACTIONS,
  outside_policy: 'admins',
  outside_shares: [],
  share_targets: [{ team_id: 't2', name: 'Dev' }],
  warning_kind: 'source',
  ...over,
});

const outsideShare = (over: Record<string, unknown> = {}) => ({
  id: 's1',
  resource_type: 'source',
  resource_id: 'r1',
  resource_name: 'Rates',
  team_id: 't3',
  name: 'Finance',
  shared_by: { user_id: 'u7', label: 'dana@meridian.example' },
  created_at: '2026-11-17T10:00:00Z',
  can_revoke: true,
  used_by_count: 2,
  paused_reason: null,
  ...over,
});

describe('ShareToTeamModal outside the team', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    listResourceShares.mockReset().mockResolvedValue({ shares: [] });
    getResourceSettings.mockReset().mockResolvedValue({
      success: true,
      resource_type: 'agent',
      resource_id: 'r1',
      settings: [],
      access: 'owner',
      allowed_actions: ['share', 'use', 'manage_settings'],
    });
    listMembers.mockReset().mockResolvedValue({ members: [] });
    share.mockReset().mockResolvedValue({ success: true });
    shareTeamItem.mockReset().mockResolvedValue({ success: true });
    unshareTeamItem.mockReset().mockResolvedValue({ success: true });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = async (resourceType: 'agent' | 'source' = 'source') => {
    act(() => {
      root.render(
        <MemoryRouter>
          <ShareToTeamModal
            resourceType={resourceType}
            resourceId="r1"
            resourceName="Rates"
            onClose={() => undefined}
          />
        </MemoryRouter>,
      );
    });
    await flush();
  };

  // The team item's picker by its name; the personal add row is the only
  // other combobox.
  const openPicker = async (label?: string) => {
    const picker = body().querySelector<HTMLButtonElement>(
      label
        ? `button[role="combobox"][aria-label="${label}"]`
        : 'button[role="combobox"]',
    );
    expect(picker).not.toBeNull();
    await act(async () => {
      picker!.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      picker!.click();
    });
    return Array.from(
      body().querySelectorAll<HTMLElement>('[data-slot="command-item"]'),
    );
  };

  const pickTarget = async (name: string) => {
    const items = await openPicker('workspace.share.outside.picker');
    const item = items.find((i) => i.textContent?.includes(name));
    expect(item).toBeDefined();
    await act(async () => item!.click());
  };

  describe("a team's item", () => {
    it('shares with a team from share_targets after saying what it gets', async () => {
      listResourceShares.mockResolvedValue(teamItem());
      await render();
      expect(text()).toContain('workspace.share.outside.teamsTitle');
      const items = await openPicker('workspace.share.outside.picker');
      expect(items.map((i) => i.textContent)).toEqual(['DDev']);
      await act(async () => items[0].click());
      expect(text()).toContain(
        'workspace.share.outside.warning.source(team=Dev,owner=Operations)',
      );
      expect(text()).toContain(
        'workspace.share.outside.warning.always(team=Dev)',
      );
      listResourceShares.mockClear();
      await act(async () =>
        buttonByText('workspace.share.outside.share')!.click(),
      );
      await flush();
      expect(shareTeamItem).toHaveBeenCalledWith(
        't2',
        { resource_type: 'source', resource_id: 'r1' },
        'tok',
      );
      // The dialog reloads, so the new share shows as a row.
      expect(listResourceShares).toHaveBeenCalled();
    });

    it('offers no picker without share_outside', async () => {
      listResourceShares.mockResolvedValue(
        teamItem({
          access: 'editor',
          team_role: 'editor',
          allowed_actions: ['use', 'edit'],
        }),
      );
      await render();
      expect(
        body().querySelector(
          'button[aria-label="workspace.share.outside.picker"]',
        ),
      ).toBeNull();
      expect(buttonByText('workspace.share.outside.share')).toBeUndefined();
      // A Viewer or Editor with nothing shared reads no section at all.
      expect(text()).not.toContain('workspace.share.outside.teamsTitle');
    });

    it('says there is no team to share with when it has no targets', async () => {
      listResourceShares.mockResolvedValue(teamItem({ share_targets: [] }));
      await render();
      expect(text()).toContain('workspace.share.outside.noTargets');
      expect(
        body().querySelector(
          'button[aria-label="workspace.share.outside.picker"]',
        ),
      ).toBeNull();
    });

    it.each([
      ['agent', 'agent(team=Dev,owner=Operations)'],
      ['prompt', 'prompt(team=Dev,owner=Operations)'],
      ['tool_stored', 'toolStored(team=Dev,owner=Operations)'],
      ['tool_member', 'toolMember(team=Dev,owner=Operations)'],
    ])('warns for a %s', async (kind, line) => {
      listResourceShares.mockResolvedValue(teamItem({ warning_kind: kind }));
      await render();
      await pickTarget('Dev');
      expect(text()).toContain(`workspace.share.outside.warning.${line}`);
      expect(text()).toContain(
        'workspace.share.outside.warning.always(team=Dev)',
      );
    });

    it('shows an info note instead of the picker while the team is locked', async () => {
      listResourceShares.mockResolvedValue(
        teamItem({
          outside_policy: 'locked',
          allowed_actions: ['use', 'edit'],
          share_targets: [],
          outside_shares: [outsideShare({ paused_reason: 'team_locked' })],
        }),
      );
      await render();
      const note = Array.from(body().querySelectorAll('[role="note"]')).find(
        (n) =>
          n.textContent?.includes(
            'workspace.share.outside.locked(team=Operations)',
          ),
      );
      expect(note?.getAttribute('data-variant')).toBe('info');
      expect(
        body().querySelector(
          'button[aria-label="workspace.share.outside.picker"]',
        ),
      ).toBeNull();
      expect(text()).toContain(
        'workspace.share.outside.pausedLocked(owner=Operations)',
      );
      // Its Admins may still stop a paused share.
      expect(
        body().querySelector(
          'button[aria-label="workspace.share.outside.revoke"]',
        ),
      ).not.toBeNull();
    });

    it('lists its shares, and stops one after saying what stops', async () => {
      listResourceShares.mockResolvedValue(
        teamItem({ outside_shares: [outsideShare()] }),
      );
      await render();
      expect(text()).toContain('Finance');
      expect(text()).toContain(
        'workspace.share.outside.sharedBy(name=dana@meridian.example)',
      );
      expect(text()).toContain(
        'workspace.share.outside.usedBy(count=2,formatted=#2)',
      );
      await act(async () =>
        body()
          .querySelector<HTMLButtonElement>(
            'button[aria-label="workspace.share.outside.revoke"]',
          )!
          .click(),
      );
      expect(text()).toContain(
        'workspace.share.outside.revokeConfirm(team=Finance)',
      );
      expect(text()).toContain(
        'workspace.share.outside.revokeUsed(count=2,formatted=#2,team=Finance)',
      );
      const confirm = Array.from(
        body().querySelectorAll<HTMLButtonElement>('button'),
      ).filter(
        (b) => b.textContent?.trim() === 'workspace.share.outside.revoke',
      );
      await act(async () => confirm.at(-1)!.click());
      await flush();
      expect(unshareTeamItem).toHaveBeenCalledWith(
        't3',
        { resource_type: 'source', resource_id: 'r1' },
        'tok',
      );
    });

    it("says an agent's receivers stop chatting when its share stops", async () => {
      listResourceShares.mockResolvedValue(
        teamItem({
          warning_kind: 'agent',
          outside_shares: [
            outsideShare({ resource_type: 'agent', used_by_count: null }),
          ],
        }),
      );
      await render('agent');
      await act(async () =>
        body()
          .querySelector<HTMLButtonElement>(
            'button[aria-label="workspace.share.outside.revoke"]',
          )!
          .click(),
      );
      expect(text()).toContain(
        'workspace.share.outside.revokeAgent(team=Finance)',
      );
    });

    it('offers no Stop sharing on a share the caller may not stop', async () => {
      listResourceShares.mockResolvedValue(
        teamItem({ outside_shares: [outsideShare({ can_revoke: false })] }),
      );
      await render();
      expect(text()).toContain('Finance');
      expect(
        body().querySelector(
          'button[aria-label="workspace.share.outside.revoke"]',
        ),
      ).toBeNull();
    });

    it('shows a refused share in its own words by code', async () => {
      listResourceShares.mockResolvedValue(teamItem({ warning_kind: 'agent' }));
      shareTeamItem.mockRejectedValue(
        new TeamsApiError(403, 'server words', 'borrowed_resource'),
      );
      await render('agent');
      await pickTarget('Dev');
      await act(async () =>
        buttonByText('workspace.share.outside.share')!.click(),
      );
      await flush();
      expect(text()).toContain('settings.teams.errors.borrowedResource');
      expect(text()).not.toContain('server words');
    });
  });

  describe('an item another team shares with the caller', () => {
    it('says where it comes from and that it is not shared on', async () => {
      listResourceShares.mockResolvedValue({
        success: true,
        shares: [],
        workspace: { kind: 'team', team_id: 't2', name: 'Dev' },
        access: 'viewer',
        team_role: null,
        origin: 'team_shared',
        shared_from: { team_id: 't1', name: 'Operations' },
        allowed_actions: ['use'],
        outside_shares: [],
        share_targets: [],
      });
      await render();
      expect(text()).toContain(
        'workspace.share.outside.received.body(owner=Operations,team=Dev)',
      );
      expect(text()).toContain('workspace.share.outside.received.note');
      expect(text()).not.toContain('workspace.share.everyoneInTeam');
      expect(text()).not.toContain('workspace.share.outside.teamsTitle');
      expect(body().querySelector('[role="combobox"]')).toBeNull();
    });
  });

  describe("a personal agent using a team's items", () => {
    const usesOps = [
      {
        team_id: 't1',
        name: 'Operations',
        items: [{ key: 'source:s1', type: 'source', id: 's1', name: 'Rates' }],
      },
    ];

    it('suggests only the teams and people who can use them', async () => {
      listResourceShares.mockResolvedValue({
        shares: [],
        uses_team_items: usesOps,
      });
      listMembers.mockImplementation((teamId: string) =>
        Promise.resolve({
          members:
            teamId === 't1'
              ? [{ user_id: 'u2', email: 'ana@x.example' }]
              : [
                  { user_id: 'u2', email: 'ana@x.example' },
                  { user_id: 'u3', email: 'bo@x.example' },
                ],
        }),
      );
      await render('agent');
      expect(text()).toContain('workspace.share.outside.uses.note');
      const items = await openPicker();
      const labels = items.map((i) => i.textContent);
      expect(labels).toContain('OOperations');
      expect(labels).not.toContain('DDev');
      // Ana is in Operations, so she can use its items; Bo can't.
      expect(labels.some((l) => l?.includes('ana@x.example'))).toBe(true);
      expect(labels.some((l) => l?.includes('bo@x.example'))).toBe(false);
    });

    it('offers the move when a share is refused over its team items', async () => {
      getResourceSettings.mockResolvedValue({
        success: true,
        resource_type: 'agent',
        resource_id: 'r1',
        settings: [],
        access: 'owner',
        allowed_actions: ['share', 'use', 'manage_settings', 'move_to_team'],
      });
      // Only through a share does Dev reach the source, so the dialog
      // can't tell: the server answers.
      listResourceShares.mockResolvedValue({ shares: [], uses_team_items: [] });
      share.mockRejectedValue(
        new TeamsApiError(409, 'This agent uses Rates', 'uses_team_items', {
          error: 'uses_team_items',
          uses_team_items: usesOps,
          move_to: { team_id: 't1', name: 'Operations' },
        }),
      );
      await render('agent');
      const items = await openPicker();
      await act(async () =>
        items.find((i) => i.textContent === 'DDev')!.click(),
      );
      await flush();
      const note = Array.from(body().querySelectorAll('[role="note"]')).find(
        (n) => n.textContent?.includes('settings.teams.errors.usesTeamItems'),
      );
      expect(note).toBeDefined();
      expect(note!.textContent).toContain(
        'workspace.share.outside.uses.fromTeam(team=Operations,items=Rates)',
      );
      const move = buttonByText(
        'workspace.share.outside.uses.moveTo(team=Operations)',
      );
      expect(move).toBeDefined();
      await act(async () => move!.click());
      expect(
        body().querySelector('[data-testid="move-dialog"]')?.textContent,
      ).toBe('r1:t1');
    });

    it('offers no move to a caller who may not move it', async () => {
      listResourceShares.mockResolvedValue({ shares: [], uses_team_items: [] });
      share.mockRejectedValue(
        new TeamsApiError(409, 'refused', 'uses_team_items', {
          error: 'uses_team_items',
          uses_team_items: usesOps,
          move_to: { team_id: 't1', name: 'Operations' },
        }),
      );
      await render('agent');
      const items = await openPicker();
      await act(async () =>
        items.find((i) => i.textContent === 'DDev')!.click(),
      );
      await flush();
      expect(text()).toContain('workspace.share.outside.uses.remove');
      expect(
        buttonByText('workspace.share.outside.uses.moveTo(team=Operations)'),
      ).toBeUndefined();
    });
  });
});
