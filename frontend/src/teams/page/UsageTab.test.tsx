import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

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

const getTeamUsage = vi.fn();
vi.mock('../../api/services/payerService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/services/payerService')>()),
  default: {
    getTeamUsage: (...a: unknown[]) => getTeamUsage(...a),
  },
}));

import type { TeamUsage } from '../../api/services/payerService';
import type { Team } from '../teamsSlice';
import { visibleTeamTabs } from './teamTabs';
import UsageTab from './UsageTab';

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
};

const person = (
  user_id: string,
  role: string | null,
  cost: number,
): TeamUsage['by_person'][number] => ({
  user_id,
  label: `${user_id}@x.io`,
  role,
  tokens: cost * 1000,
  cost,
});

const usage = (over: Partial<TeamUsage> = {}): TeamUsage => ({
  period: {
    kind: 'month',
    start: '2026-11-01T00:00:00Z',
    end: '2026-12-01T00:00:00Z',
    current: true,
  },
  totals: { tokens: 900000, cost: 412, people: 9 },
  split: {
    chats: { tokens: 600000, cost: 284 },
    runs: { tokens: 300000, cost: 128 },
  },
  by_person: [
    person('me', 'admin', 131),
    person('dana', 'editor', 118),
    person('ines', null, 40),
  ],
  by_agent: [
    {
      agent_id: 'a1',
      name: 'Carrier desk',
      tokens: 188000,
      cost: 188,
      requests: 1204,
      people: 9,
      limit_on: false,
      published: null,
      moved_out: false,
    },
    {
      agent_id: 'a2',
      name: 'Tender helper',
      tokens: 96000,
      cost: 96,
      requests: 311,
      people: 4,
      limit_on: true,
      published: { paid_by: { user_id: 'me', label: 'me@x.io' } },
      moved_out: false,
    },
    {
      agent_id: 'a3',
      name: null,
      tokens: 1000,
      cost: 1,
      requests: 2,
      people: 1,
      limit_on: false,
      published: null,
      moved_out: false,
    },
    {
      agent_id: 'a4',
      name: null,
      tokens: 500,
      cost: 0.5,
      requests: 1,
      people: 1,
      limit_on: false,
      published: null,
      moved_out: true,
    },
  ],
  paused: [
    {
      type: 'schedule',
      id: 's1',
      name: 'Tender digest',
      agent: { id: 'a2', name: 'Tender helper' },
      paused_for: {
        reason: 'payer_out_of_allowance',
        until: '2026-12-01T00:00:00Z',
      },
      paid_by: { user_id: 'tomas', label: 'Tomas' },
    },
    {
      type: 'outside_access',
      id: 'a1',
      agent: { id: 'a1', name: 'Carrier desk' },
      access: ['api_key', 'webhook'],
      paused_for: { reason: 'payer_left' },
      paid_by: { user_id: 'ines', label: 'ines@x.io' },
    },
    {
      type: 'source_sync',
      id: 'src1',
      name: 'Lane notes',
      paused_for: { reason: 'sync_no_payer', since: null },
    },
  ],
  ...over,
});

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>;
}

describe('the Usage tab config', () => {
  it('shows the tab to the owner and admins, not to editors or viewers', () => {
    const keys = (role: 'owner' | 'admin' | 'editor' | 'viewer') =>
      visibleTeamTabs(role).map((tab) => tab.key);
    expect(keys('owner')).toContain('usage');
    expect(keys('admin')).toContain('usage');
    expect(keys('editor')).not.toContain('usage');
    expect(keys('viewer')).not.toContain('usage');
  });
});

describe('UsageTab', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getTeamUsage.mockReset().mockResolvedValue(usage());
    mockDispatch.mockClear();
    mockState.workspace.current = 'personal';
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = async () => {
    act(() => {
      root.render(
        <MemoryRouter initialEntries={['/teams/t1/usage']}>
          <Routes>
            <Route
              path="/teams/:teamId/:tab"
              element={<UsageTab team={TEAM} role="admin" />}
            />
            <Route path="*" element={null} />
          </Routes>
          <Where />
        </MemoryRouter>,
      );
    });
    await flush();
  };

  const section = (id: string) =>
    body().querySelector<HTMLElement>(`[data-testid="${id}"]`)!;
  const rows = (id: string) =>
    Array.from(
      section(id).querySelectorAll<HTMLElement>('[data-slot="list-row"]'),
    );
  const button = (label: string, scope: ParentNode = body()) =>
    Array.from(scope.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent === label,
    );
  const where = () =>
    body().querySelector('[data-testid="where"]')?.textContent;

  it("asks for this period's report", async () => {
    await render();
    expect(getTeamUsage).toHaveBeenCalledWith('t1', 'current', TOKEN);
  });

  it('shows the totals, the split and that it is no limit', async () => {
    await render();
    const text = body().textContent ?? '';
    expect(text).toContain('payer.team.stats.used(team=Operations)');
    expect(text).toMatch(/\$412\.00/);
    expect(text).toContain('payer.team.stats.people(count=9');
    expect(text).toContain('payer.team.stats.chats');
    expect(text).toMatch(/\$284\.00/);
    expect(text).toContain('payer.team.stats.runs');
    expect(text).toMatch(/\$128\.00/);
    expect(text).toContain('payer.team.notALimit');
  });

  it('shows tokens when nothing is priced', async () => {
    getTeamUsage.mockResolvedValue(
      usage({
        totals: { tokens: 900000, cost: 0, people: 2 },
        split: {
          chats: { tokens: 600000, cost: 0 },
          runs: { tokens: 300000, cost: 0 },
        },
      }),
    );
    await render();
    expect(body().textContent).toContain(
      'payer.team.tokens(count=900000,formatted=900,000)',
    );
  });

  it('lists people with their role, you, and who left the team', async () => {
    await render();
    const [me, dana, ines] = rows('usage-by-person');
    expect(me.textContent).toContain('me@x.io');
    expect(me.textContent).toContain('workspace.common.roles.admin');
    expect(me.textContent).toContain('payer.team.byPerson.you');
    expect(dana.textContent).toContain('workspace.common.roles.editor');
    expect(ines.textContent).toContain('payer.team.byPerson.left');
  });

  it('lists agents with their limit and who pays for outside use', async () => {
    await render();
    const [carrier, tender, deleted, moved] = rows('usage-by-agent');
    expect(carrier.textContent).toContain('Carrier desk');
    expect(carrier.textContent).toContain('payer.team.byAgent.noLimit');
    expect(tender.textContent).toContain('payer.team.byAgent.limitOn');
    expect(tender.textContent).toContain('payer.team.byAgent.outsidePaidByYou');
    expect(deleted.textContent).toContain('payer.team.byAgent.deleted');
    // An agent the team no longer owns: no name, limit or payer that are now someone else's.
    expect(moved.textContent).toContain('payer.team.byAgent.movedOut');
    expect(moved.textContent).not.toContain('payer.team.byAgent.noLimit');
    // Agentless chats and deleted agents count in the totals only.
    expect(section('usage-by-agent').textContent).toContain(
      'payer.team.byAgent.totalsOnly',
    );
  });

  it('names the team that shared an agent with this one, with no limit line', async () => {
    getTeamUsage.mockResolvedValue(
      usage({
        by_agent: [
          {
            agent_id: 'a9',
            name: 'Dispatch helper',
            tokens: 4000,
            cost: 4,
            requests: 12,
            people: 2,
            limit_on: false,
            published: null,
            moved_out: false,
            shared_from: { team_id: 't2', name: 'Dev' },
          },
          {
            agent_id: 'a8',
            name: 'Hidden origin',
            tokens: 1000,
            cost: 1,
            requests: 1,
            people: 1,
            limit_on: false,
            published: null,
            moved_out: false,
            shared_from: { team_id: 't3', name: null },
          },
        ],
      }),
    );
    await render();
    const [shared, unnamed] = rows('usage-by-agent');
    expect(shared.textContent).toContain('Dispatch helper');
    expect(shared.textContent).toContain(
      'workspace.page.sharedFromTeams.from(team=Dev)',
    );
    // Its limit belongs to the team that owns it: not shown here.
    expect(shared.textContent).not.toContain('payer.team.byAgent.noLimit');
    expect(unnamed.textContent).toContain(
      'settings.teams.outside.fromAnotherTeam',
    );
  });

  it('shows five rows, then all of them on Show all', async () => {
    getTeamUsage.mockResolvedValue(
      usage({
        by_person: ['a', 'b', 'c', 'd', 'e', 'f', 'g'].map((id, i) =>
          person(id, 'viewer', 10 - i),
        ),
      }),
    );
    await render();
    expect(rows('usage-by-person')).toHaveLength(5);
    const all = button(
      'payer.team.showAll(formatted=7)',
      section('usage-by-person'),
    )!;
    act(() => all.click());
    await flush();
    expect(rows('usage-by-person')).toHaveLength(7);
  });

  it('lists what is paused, with the reason and Take over links', async () => {
    await render();
    const [schedule, access, sync] = rows('usage-paused');
    expect(schedule.textContent).toContain('Tender digest');
    expect(schedule.textContent).toContain(
      'payer.common.pause.outOfAllowance(name=Tomas',
    );
    expect(access.textContent).toContain('Carrier desk');
    expect(access.textContent).toContain(
      'payer.common.pause.payerLeft(name=ines@x.io,team=Operations)',
    );
    expect(sync.textContent).toContain('Lane notes');
    expect(sync.textContent).toContain('payer.team.paused.syncNoPayer');
    // A source sync can't be taken over.
    expect(button('payer.common.takeOver.submit', sync)).toBeUndefined();

    act(() => button('payer.common.takeOver.submit', schedule)!.click());
    await flush();
    expect(where()).toBe('/agents/manage/schedules/a2');
    // The agent is the team's: the app moves to the team to open it.
    expect(mockDispatch).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'workspace/switched',
        payload: expect.objectContaining({ id: 't1' }),
      }),
    );
  });

  it("opens the agent's page to take over outside access", async () => {
    mockState.workspace.current = 't1';
    await render();
    const access = rows('usage-paused')[1];
    act(() => button('payer.common.takeOver.submit', access)!.click());
    await flush();
    expect(where()).toBe('/agents/manage/edit/a1');
    // Already in the team: no switch.
    expect(mockDispatch).not.toHaveBeenCalledWith(
      expect.objectContaining({ type: 'workspace/switched' }),
    );
  });

  it('offers no Take over on what the reader already pays for', async () => {
    getTeamUsage.mockResolvedValue(
      usage({
        paused: [
          {
            type: 'schedule',
            id: 's1',
            name: 'Tender digest',
            agent: { id: 'a2', name: 'Tender helper' },
            paused_for: {
              reason: 'payer_out_of_allowance',
              until: '2026-12-01T00:00:00Z',
            },
            paid_by: { user_id: 'me', label: 'me@x.io' },
          },
        ],
      }),
    );
    await render();
    const [schedule] = rows('usage-paused');
    expect(schedule.textContent).toContain(
      'payer.common.pause.outOfAllowanceYou',
    );
    expect(button('payer.common.takeOver.submit', schedule)).toBeUndefined();
  });

  it('leaves the paused list out when nothing is paused', async () => {
    getTeamUsage.mockResolvedValue(usage({ paused: [] }));
    await render();
    expect(section('usage-paused')).toBeNull();
  });

  it('switches to the previous period', async () => {
    await render();
    const previous = Array.from(
      body().querySelectorAll<HTMLButtonElement>('button[role="radio"]'),
    ).find((b) => b.textContent === 'payer.team.period.previous.month')!;
    getTeamUsage.mockResolvedValue(
      usage({
        period: {
          kind: 'month',
          start: '2026-10-01T00:00:00Z',
          end: '2026-11-01T00:00:00Z',
          current: false,
        },
      }),
    );
    act(() => previous.click());
    await flush();
    expect(getTeamUsage).toHaveBeenLastCalledWith('t1', 'previous', TOKEN);
  });

  it('says when the report could not load, with Retry', async () => {
    getTeamUsage.mockRejectedValue(new Error('down'));
    await render();
    expect(body().textContent).toContain('payer.team.loadError');
    getTeamUsage.mockResolvedValue(usage());
    act(() => button('retry')!.click());
    await flush();
    expect(getTeamUsage).toHaveBeenCalledTimes(2);
  });
});
