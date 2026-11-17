import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';

// A JWT whose payload is {"sub":"me"}.
const TOKEN = `x.${btoa(JSON.stringify({ sub: 'me' }))}.y`;

const mockState = {
  preference: { token: TOKEN },
  workspace: {
    current: 'personal',
    workspaces: [
      { id: 'personal', kind: 'personal', name: 'Personal' },
      { id: 't1', kind: 'team', name: 'Operations', role: 'admin' },
    ],
    loaded: true,
    loading: false,
    epoch: 0,
    lastReason: null,
    latestRequestId: null,
  },
};

const mockDispatch = vi.fn((action: unknown) => action);

vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) => selector(mockState),
  useDispatch: () => mockDispatch,
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

vi.mock('../../modals/ConfirmationModal', async () => {
  const { useState } = await import('react');
  return {
    default: function MockConfirm(props: {
      modalState: string;
      setModalState: (s: string) => void;
      message: string;
      description?: string;
      submitLabel: string;
      error?: string | ((reason: unknown) => string);
      handleSubmit: () => unknown;
    }) {
      const [failed, setFailed] = useState<{ reason: unknown } | null>(null);
      if (props.modalState !== 'ACTIVE') return null;
      const submit = () => {
        const result = props.handleSubmit();
        if (result instanceof Promise) {
          result.then(
            () => props.setModalState('INACTIVE'),
            (reason: unknown) => setFailed({ reason }),
          );
        } else props.setModalState('INACTIVE');
      };
      return (
        <div role="dialog" data-testid="confirm">
          <h2>{props.message}</h2>
          {props.description && <p>{props.description}</p>}
          {failed && (
            <p data-testid="confirm-error">
              {typeof props.error === 'function'
                ? props.error(failed.reason)
                : props.error}
            </p>
          )}
          <button type="button" onClick={submit}>
            {props.submitLabel}
          </button>
        </div>
      );
    },
  };
});

const getOutside = vi.fn();
const unshareTeamItem = vi.fn();
vi.mock('../../api/services/teamsService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/services/teamsService')>()),
  default: {
    getOutside: (...a: unknown[]) => getOutside(...a),
    unshareTeamItem: (...a: unknown[]) => unshareTeamItem(...a),
    getResourceSettings: vi.fn(() => Promise.resolve(null)),
  },
}));

import {
  type OutsideShare,
  type TeamGrant,
  type TeamOutside,
  TeamsApiError,
} from '../../api/services/teamsService';
import type { Team } from '../teamsSlice';
import SharedItemsTab from './SharedItemsTab';
import { sharedBy } from './teamGrants';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const flush = async () => {
  for (let i = 0; i < 8; i += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
};

const body = () => document.body;

const TEAM: Team = {
  id: 't1',
  name: 'Operations',
  slug: 'operations',
  owner_id: 'lena',
  outside_policy: 'admins',
  can_set_outside_policy: true,
};

const share = (over: Partial<OutsideShare> = {}): OutsideShare => ({
  id: 's1',
  resource_type: 'source',
  resource_id: 'src1',
  resource_name: 'Lane notes',
  team_id: 't2',
  name: 'Dev',
  shared_by: { user_id: 'dana', label: 'dana@x.io' },
  created_at: '2026-11-10T10:00:00Z',
  can_revoke: true,
  used_by_count: 3,
  paused_reason: null,
  ...over,
});

const outside = (over: Partial<TeamOutside> = {}): TeamOutside => ({
  outside_policy: 'admins',
  can_set_outside_policy: true,
  shares: [
    share(),
    share({
      id: 's2',
      resource_type: 'agent',
      resource_id: 'a1',
      resource_name: 'Carrier desk',
      used_by_count: null,
    }),
    share({
      id: 's3',
      resource_type: 'tool',
      resource_id: 'tool1',
      resource_name: 'Tender API',
      used_by_count: 0,
    }),
    share({
      id: 's4',
      resource_type: 'prompt',
      resource_id: 'p1',
      resource_name: 'House style',
      used_by_count: null,
    }),
  ],
  published: [
    {
      agent_id: 'a5',
      name: 'Tender helper',
      outside_access: {
        api_key: true,
        public_link: false,
        webhook: true,
        paid_by: { user_id: 'dana', label: 'dana@x.io' },
        paused_for: null,
      },
    },
  ],
  ...over,
});

const personalGrant: TeamGrant = {
  resource_type: 'source',
  resource_id: 'mine1',
  access_level: 'viewer',
  resource_name: 'Dana notes',
  owner_id: 'dana',
  owner_label: 'dana@x.io',
  origin: 'personal_shared',
};

const incoming = (over: Partial<TeamGrant> = {}): TeamGrant => ({
  id: 'in1',
  resource_type: 'source',
  resource_id: 'src9',
  access_level: 'viewer',
  resource_name: 'Dev handbook',
  owner_id: '__team__t2',
  origin: 'team_shared',
  shared_from: { team_id: 't2', name: 'Dev' },
  paused_reason: null,
  can_revoke: true,
  used_by: [
    { id: 'a7', name: 'Ops desk' },
    { id: 'a8', name: 'Night shift' },
  ],
  ...over,
});

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>;
}

describe('SharedItemsTab, outside the team', () => {
  let container: HTMLDivElement;
  let root: Root;
  const onGrantsChanged = vi.fn();

  beforeEach(() => {
    getOutside.mockReset().mockResolvedValue(outside());
    unshareTeamItem
      .mockReset()
      .mockResolvedValue({ success: true, side: 'owner' });
    onGrantsChanged.mockReset();
    mockDispatch.mockClear();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = async (
    grants: TeamGrant[] = [],
    role: 'owner' | 'admin' | 'editor' | 'viewer' = 'admin',
  ) => {
    act(() => {
      root.render(
        <MemoryRouter initialEntries={['/teams/t1/shared']}>
          <SharedItemsTab
            team={TEAM}
            role={role}
            grants={grants}
            onGrantsChanged={onGrantsChanged}
          />
          <Where />
        </MemoryRouter>,
      );
    });
    await flush();
  };

  const section = (id: string) =>
    body().querySelector<HTMLElement>(`[data-testid="${id}"]`);
  const rows = (id: string) =>
    Array.from(body().querySelectorAll<HTMLElement>(`[data-testid="${id}"]`));
  const button = (label: string, scope: ParentNode = body()) =>
    Array.from(scope.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent === label,
    );
  const confirm = () =>
    body().querySelector<HTMLElement>('[data-testid="confirm"]');

  it('lists what the team shares with other teams: the team, who shared it and when', async () => {
    await render();
    expect(getOutside).toHaveBeenCalledWith('t1', TOKEN);
    const [source] = rows('outside-share-row');
    expect(source.textContent).toContain('Lane notes');
    expect(source.textContent).toContain(
      'settings.teams.outside.shares.with(team=Dev)',
    );
    expect(source.textContent).toContain(
      'settings.teams.outside.shares.by(name=dana@x.io)',
    );
    expect(source.textContent).toContain('settings.teams.resourceType.source');
    expect(section('outside-shares')!.textContent).toContain(
      'settings.teams.outside.shares.policy(policy=settings.teams.outside.policy.admins)',
    );
  });

  it("drops a late answer for the team you left, so its shares don't show on the next team's page", async () => {
    let answerFirst: (value: TeamOutside) => void = () => {};
    getOutside.mockImplementation((teamId: string) =>
      teamId === 't1'
        ? new Promise((resolve) => {
            answerFirst = resolve;
          })
        : Promise.resolve(
            outside({
              shares: [share({ id: 'd1', resource_name: 'Dev runbook' })],
              published: [],
            }),
          ),
    );
    const show = (team: Team) =>
      act(() => {
        root.render(
          <MemoryRouter initialEntries={['/teams/t1/shared']}>
            <SharedItemsTab
              team={team}
              role="admin"
              grants={[]}
              onGrantsChanged={onGrantsChanged}
            />
          </MemoryRouter>,
        );
      });
    show(TEAM);
    await flush();
    show({ ...TEAM, id: 't2', name: 'Dev', slug: 'dev' });
    await flush();
    // The team you left answers last.
    answerFirst(outside());
    await flush();
    const names = rows('outside-share-row').map((row) => row.textContent);
    expect(names.join(' ')).toContain('Dev runbook');
    expect(names.join(' ')).not.toContain('Lane notes');
  });

  it('offers Stop sharing only on rows the server lets the reader revoke', async () => {
    getOutside.mockResolvedValue(
      outside({ shares: [share(), share({ id: 's2', can_revoke: false })] }),
    );
    await render([], 'viewer');
    const [revocable, fixed] = rows('outside-share-row');
    expect(
      button('settings.teams.outside.shares.revoke', revocable),
    ).toBeDefined();
    expect(button('settings.teams.outside.shares.revoke', fixed)).toBe(
      undefined,
    );
  });

  it('marks shares paused while the team is locked', async () => {
    getOutside.mockResolvedValue(
      outside({
        outside_policy: 'locked',
        shares: [share({ paused_reason: 'team_locked' })],
      }),
    );
    await render();
    const [row] = rows('outside-share-row');
    expect(row.textContent).toContain(
      'settings.teams.outside.paused(team=Operations)',
    );
    expect(section('outside-shares')!.textContent).toContain(
      'settings.teams.outside.shares.locked(team=Operations)',
    );
  });

  it.each([
    [0, 'settings.teams.outside.stops.usedBy(team=Dev,count=3,formatted=3)'],
    [1, 'settings.teams.outside.stops.agent(team=Dev)'],
    [2, 'settings.teams.outside.stops.none(team=Dev)'],
    [3, 'settings.teams.outside.stops.unknown(team=Dev)'],
  ])('says what stops before revoking share %i', async (index, stops) => {
    await render();
    const row = rows('outside-share-row')[index];
    act(() => button('settings.teams.outside.shares.revoke', row)!.click());
    await flush();
    expect(confirm()!.textContent).toContain(stops);
  });

  it('revokes from the receiving team and reads the list again', async () => {
    await render();
    act(() =>
      button(
        'settings.teams.outside.shares.revoke',
        rows('outside-share-row')[0],
      )!.click(),
    );
    await flush();
    expect(confirm()!.textContent).toContain(
      'settings.teams.outside.shares.revokeTitle(name=Lane notes,team=Dev)',
    );
    act(() =>
      button('settings.teams.outside.shares.revoke', confirm()!)!.click(),
    );
    await flush();
    expect(unshareTeamItem).toHaveBeenCalledWith(
      't2',
      { resource_type: 'source', resource_id: 'src1' },
      TOKEN,
    );
    expect(getOutside).toHaveBeenCalledTimes(2);
    expect(confirm()).toBeNull();
  });

  it('keeps a refused revoke in its confirm, worded by its code', async () => {
    unshareTeamItem.mockRejectedValue(
      new TeamsApiError(403, 'no', 'workspace_role_required'),
    );
    await render();
    act(() =>
      button(
        'settings.teams.outside.shares.revoke',
        rows('outside-share-row')[0],
      )!.click(),
    );
    await flush();
    act(() =>
      button('settings.teams.outside.shares.revoke', confirm()!)!.click(),
    );
    await flush();
    expect(
      body().querySelector('[data-testid="confirm-error"]')?.textContent,
    ).toBe('settings.teams.errors.roleRequired');
  });

  it('lists agents reachable from outside, read-only, opened in the team by Editors', async () => {
    await render([], 'editor');
    const [agent] = rows('outside-published-row');
    expect(agent.textContent).toContain('Tender helper');
    expect(agent.textContent).toContain('payer.team.paused.access');
    expect(button('settings.teams.outside.shares.revoke', agent)).toBe(
      undefined,
    );
    act(() => button('settings.teams.outside.published.open', agent)!.click());
    await flush();
    expect(
      body().querySelector('[data-testid="where"]')?.textContent,
    ).toContain('a5');
    expect(mockDispatch).toHaveBeenCalled();
  });

  it('gives Viewers no way to open a published agent', async () => {
    await render([], 'viewer');
    const [agent] = rows('outside-published-row');
    expect(button('settings.teams.outside.published.open', agent)).toBe(
      undefined,
    );
  });

  it('says when nothing is shared outside', async () => {
    getOutside.mockResolvedValue(outside({ shares: [], published: [] }));
    await render();
    expect(section('outside-shares')!.textContent).toContain(
      'settings.teams.outside.shares.empty',
    );
  });

  it('says when the list could not load, with Retry', async () => {
    getOutside.mockRejectedValueOnce(new Error('down'));
    await render();
    expect(section('outside-shares')!.textContent).toContain(
      'settings.teams.outside.shares.loadError',
    );
  });

  it("keeps another team's items out of the members' shared items", async () => {
    await render([personalGrant, incoming()]);
    const personal = Array.from(
      body().querySelectorAll('[data-testid="shared-resource-row"]'),
    );
    expect(personal).toHaveLength(1);
    expect(personal[0].closest('li')!.textContent).toContain('Dana notes');
    const [row] = rows('shared-from-team-row');
    expect(row.textContent).toContain('Dev handbook');
    expect(row.textContent).toContain(
      'workspace.page.sharedFromTeams.from(team=Dev)',
    );
  });

  it('leaves out "Shared from other teams" when there are none', async () => {
    await render([personalGrant]);
    expect(section('shared-from-teams')).toBeNull();
  });

  it("marks another team's item paused while that team is locked", async () => {
    await render([incoming({ paused_reason: 'team_locked' })]);
    expect(rows('shared-from-team-row')[0].textContent).toContain(
      'settings.teams.outside.paused(team=Dev)',
    );
  });

  it('offers Remove from this team only when the server allows it', async () => {
    await render([incoming({ can_revoke: false })], 'viewer');
    expect(
      button(
        'settings.teams.outside.fromTeams.remove',
        rows('shared-from-team-row')[0],
      ),
    ).toBe(undefined);
  });

  it("removes another team's item, naming this team's agents that stop using it", async () => {
    unshareTeamItem.mockResolvedValue({ success: true, side: 'receiver' });
    await render([incoming()]);
    act(() =>
      button(
        'settings.teams.outside.fromTeams.remove',
        rows('shared-from-team-row')[0],
      )!.click(),
    );
    await flush();
    const text = confirm()!.textContent ?? '';
    expect(text).toContain(
      'settings.teams.outside.fromTeams.removeTitle(name=Dev handbook,team=Operations)',
    );
    expect(text).toContain(
      'settings.teams.outside.stops.agents(team=Operations,names=Ops desk, Night shift)',
    );
    expect(text).toContain(
      'settings.teams.outside.fromTeams.removeAgain(from=Dev)',
    );
    act(() =>
      button('settings.teams.outside.fromTeams.remove', confirm()!)!.click(),
    );
    await flush();
    expect(unshareTeamItem).toHaveBeenCalledWith(
      't1',
      { resource_type: 'source', resource_id: 'src9' },
      TOKEN,
    );
    expect(onGrantsChanged).toHaveBeenCalled();
  });

  it('says a shared agent stops answering this team when removed', async () => {
    await render([
      incoming({ resource_type: 'agent', resource_id: 'a9', used_by: null }),
    ]);
    act(() =>
      button(
        'settings.teams.outside.fromTeams.remove',
        rows('shared-from-team-row')[0],
      )!.click(),
    );
    await flush();
    expect(confirm()!.textContent).toContain(
      'settings.teams.outside.stops.agent(team=Operations)',
    );
  });
});

describe('sharedBy', () => {
  it("never counts another team's item as a member's", () => {
    const fromTeam = incoming({ owner_id: 'dana' });
    expect(sharedBy([personalGrant, fromTeam], 'dana')).toHaveLength(1);
  });
});
