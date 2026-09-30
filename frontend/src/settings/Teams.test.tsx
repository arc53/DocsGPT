import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';

// A JWT whose payload is {"sub":"me"}.
const TOKEN = `x.${btoa(JSON.stringify({ sub: 'me' }))}.y`;

const mockState = {
  preference: {
    token: TOKEN,
    agents: [],
    sourceDocs: [],
    prompts: [],
  },
  teams: {
    teams: [] as Array<Record<string, unknown>>,
    currentTeamId: null,
    loading: false,
    error: null,
  },
};

vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) => selector(mockState),
  useDispatch: () => () => ({ unwrap: () => Promise.resolve() }),
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

vi.mock('../navigation/SectionShell', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('../navigation/DetailBreadcrumb', () => ({ default: () => null }));
vi.mock('../components/PageToolbar', () => ({ default: () => null }));
vi.mock('../modals/ConfirmationModal', () => ({ default: () => null }));
vi.mock('../teams/ShareToTeamModal', () => ({
  default: () => <div data-testid="share-modal" />,
}));
// Render the ⋯ menu's options inline so tests can see them.
vi.mock('../components/ui/dropdown-menu', () => ({
  ActionMenu: ({ options }: { options: Array<{ label: string }> }) => (
    <div data-testid="team-menu">
      {options.map((o) => (
        <span key={o.label}>{o.label}</span>
      ))}
    </div>
  ),
}));
vi.mock('../api/services/userService', () => ({
  default: {
    getAgents: () => Promise.resolve({ json: () => Promise.resolve([]) }),
    getUserTools: () =>
      Promise.resolve({ json: () => Promise.resolve({ tools: [] }) }),
  },
}));

const listMembers = vi.fn();
const listGrants = vi.fn();
const unshare = vi.fn();
const share = vi.fn();
const getResourceSettings = vi.fn();

vi.mock('../api/services/teamsService', () => ({
  default: {
    listMembers: (...a: unknown[]) => listMembers(...a),
    listGrants: (...a: unknown[]) => listGrants(...a),
    unshare: (...a: unknown[]) => unshare(...a),
    share: (...a: unknown[]) => share(...a),
    getResourceSettings: (...a: unknown[]) => getResourceSettings(...a),
  },
}));

// Mark formatted counts so a raw number in the UI shows up in a test.
vi.mock('../utils/dateTimeUtils', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../utils/dateTimeUtils')>()),
  formatCount: (value: number) => `#${value}`,
}));

import Teams from './Teams';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const OWNER = {
  access: 'owner',
  allowed_actions: [
    'delete',
    'edit',
    'manage_settings',
    'share',
    'use',
    'view',
  ],
};
const VIEWER = { access: 'viewer', allowed_actions: ['pin', 'use'] };

const grant = (over: Record<string, unknown> = {}) => ({
  resource_type: 'source',
  resource_id: 's1',
  access_level: 'viewer',
  target_user_id: null,
  resource_name: 'Key Accounts',
  owner_id: 'lena',
  owner_label: 'Lena Fischer',
  target_user_label: null,
  created_at: '2026-09-12T10:00:00Z',
  granted_by_label: 'Lena Fischer',
  caller: OWNER,
  ...over,
});

const flush = async () => {
  for (let i = 0; i < 8; i += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
};

const body = () => document.body;
const rowButtons = () =>
  Array.from(
    body().querySelectorAll<HTMLButtonElement>(
      '[data-testid="shared-resource-row"]',
    ),
  );

describe('Teams page', () => {
  let container: HTMLDivElement;
  let root: Root;

  const setTeam = (over: Record<string, unknown> = {}) => {
    mockState.teams.teams = [
      {
        id: 't1',
        name: 'Revenue Ops',
        slug: 'revenue-ops',
        owner_id: 'me',
        member_role: 'team_admin',
        ...over,
      },
    ];
  };

  beforeEach(() => {
    setTeam();
    listMembers.mockReset().mockResolvedValue({ members: [] });
    listGrants
      .mockReset()
      .mockResolvedValue({ grants: [], team_role: 'team_admin' });
    unshare.mockReset().mockResolvedValue({ success: true });
    share.mockReset().mockResolvedValue({ success: true });
    getResourceSettings.mockReset().mockResolvedValue({
      success: true,
      resource_type: 'source',
      resource_id: 's1',
      settings: [
        { key: 'editors_can_share', value: false, default: false },
        { key: 'editors_can_delete', value: false, default: false },
        { key: 'viewers_can_see_config', value: true, default: true },
      ],
      access: 'owner',
      allowed_actions: OWNER.allowed_actions,
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  function Where() {
    return <div data-testid="where">{useLocation().pathname}</div>;
  }

  const render = async () => {
    act(() => {
      root.render(
        <MemoryRouter
          initialEntries={[{ pathname: '/teams', state: { openTeamId: 't1' } }]}
        >
          <Teams />
          <Where />
        </MemoryRouter>,
      );
    });
    await flush();
  };

  const openDrawer = async (index = 0) => {
    act(() => rowButtons()[index].click());
    await flush();
  };

  it('asks for members 25 at a time; no search or pager for a small team', async () => {
    listMembers.mockResolvedValue({
      members: [
        {
          user_id: 'u1',
          email: 'a@x.io',
          role: 'team_member',
          source: 'manual',
        },
      ],
      total: 1,
    });
    await render();
    expect(listMembers).toHaveBeenCalledWith('t1', TOKEN, {
      q: '',
      page: 1,
      pageSize: 25,
    });
    expect(
      body().querySelector('input[placeholder="settings.teams.searchMembers"]'),
    ).toBeNull();
    expect(body().textContent).not.toContain('settings.teams.membersRange');
  });

  it('a large team gets member search and the numbered pager', async () => {
    listMembers.mockImplementation(
      async (_id: string, _t: unknown, opts: { page: number }) => ({
        members: Array.from({ length: 25 }, (_, i) => ({
          user_id: `u${(opts.page - 1) * 25 + i}`,
          email: `m${(opts.page - 1) * 25 + i}@x.io`,
          role: 'team_member',
          source: 'manual',
        })),
        total: 312,
      }),
    );
    await render();
    expect(body().textContent).toContain('settings.teams.members · #312');
    expect(
      body().querySelector('input[placeholder="settings.teams.searchMembers"]'),
    ).not.toBeNull();
    const pagers = body().querySelectorAll('[data-slot="pagination-full"]');
    expect(pagers[0].textContent).toContain('settings.teams.membersRange');
    act(() =>
      pagers[0]
        .querySelector<HTMLButtonElement>(
          '[aria-label="pagination.goToPage(page=2)"]',
        )!
        .click(),
    );
    await flush();
    expect(listMembers).toHaveBeenLastCalledWith('t1', TOKEN, {
      q: '',
      page: 2,
      pageSize: 25,
    });
  });

  // A safety net: 48 per page, so a usual list never splits.
  it('pages past 48 shared resources; a filter starts on page 1', async () => {
    listGrants.mockResolvedValue({
      team_role: 'team_admin',
      grants: Array.from({ length: 50 }, (_, i) =>
        grant({ resource_id: `s${i}`, resource_name: `Source ${i}` }),
      ),
    });
    await render();
    expect(rowButtons()).toHaveLength(48);
    const pager = () =>
      body().querySelector<HTMLElement>('[data-slot="pagination-full"]')!;
    expect(pager().textContent).toContain(
      'settings.teams.sharedList.pageRange',
    );
    act(() =>
      pager()
        .querySelector<HTMLButtonElement>(
          '[aria-label="pagination.goToPage(page=2)"]',
        )!
        .click(),
    );
    expect(rowButtons()).toHaveLength(2);
    const sourcePill = Array.from(
      body().querySelectorAll<HTMLButtonElement>('[role="radio"]'),
    ).find((p) => p.textContent?.includes('filter.source'))!;
    act(() => sourcePill.click());
    expect(rowButtons()).toHaveLength(48);
  });

  it('pages the teams list past 48 teams', async () => {
    mockState.teams.teams = Array.from({ length: 50 }, (_, i) => ({
      id: `t${i}`,
      name: `Team ${i}`,
      slug: `team-${i}`,
      owner_id: 'me',
      member_role: 'member',
    }));
    act(() => {
      root.render(
        <MemoryRouter initialEntries={['/teams']}>
          <Teams />
        </MemoryRouter>,
      );
    });
    await flush();
    const pager = body().querySelector('[data-slot="pagination-full"]');
    expect(pager?.textContent).toContain('settings.teams.pageRange');
    expect(body().textContent).toContain('Team 47');
    expect(body().textContent).not.toContain('Team 48');
  });

  it('groups duplicate grants into one row per resource', async () => {
    listGrants.mockResolvedValue({
      team_role: 'team_admin',
      grants: [
        grant(),
        grant({
          access_level: 'editor',
          target_user_id: 'dana',
          target_user_label: 'Dana Whitfield',
        }),
        grant({
          resource_type: 'prompt',
          resource_id: 's1',
          resource_name: 'Pre-call brief',
        }),
      ],
    });
    await render();
    const rows = rowButtons();
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain('Key Accounts');
    expect(rows[0].textContent).toContain(
      'settings.teams.sharedList.badgeWithEditors(level=viewer,count=1,formatted=#1)',
    );
    expect(rows[0].textContent).toContain(
      'settings.teams.sharedList.meta(type=settings.teams.resourceType.source,owner=Lena Fischer)',
    );
    // Filter pills with counts.
    const pills = Array.from(body().querySelectorAll('[role="radio"]'));
    expect(pills.map((p) => p.textContent)).toEqual([
      'settings.teams.sharedList.filter.all #2',
      'settings.teams.sharedList.filter.agent #0',
      'settings.teams.sharedList.filter.source #1',
      'settings.teams.sharedList.filter.tool #0',
      'settings.teams.sharedList.filter.prompt #1',
    ]);
    expect(body().textContent).toContain('settings.teams.sharedResources · #2');
  });

  it('shows the no-results line when the search matches nothing', async () => {
    listGrants.mockResolvedValue({
      team_role: 'team_admin',
      grants: [grant()],
    });
    await render();
    const search = body().querySelector<HTMLInputElement>(
      'input[aria-label="settings.teams.sharedList.search"]',
    )!;
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!;
      setter.call(search, 'nothing like this');
      search.dispatchEvent(new Event('input', { bubbles: true }));
    });
    const empty = Array.from(
      body().querySelectorAll('[data-slot="empty-state"]'),
    ).find((e) =>
      e.textContent?.includes('settings.teams.sharedList.noMatches'),
    );
    expect(empty?.getAttribute('data-size')).toBe('xs');
    expect(empty?.querySelector('img')).toBeNull();
  });

  it('keeps the drawer header fixed above one scrolling body', async () => {
    listGrants.mockResolvedValue({
      team_role: 'team_admin',
      grants: [grant()],
    });
    await render();
    await openDrawer();
    const sheet = body().querySelector('[data-slot="sheet-content"]')!;
    const title = sheet.querySelector('[data-slot="sheet-title"]')!;
    expect(title.className).toContain('wrap-break-word');
    expect(title.className).not.toContain('truncate');
    const scrollers = sheet.querySelectorAll('.overflow-y-auto');
    expect(scrollers).toHaveLength(1);
    // The title and the Open button stay put; the details scroll.
    expect(scrollers[0].contains(title)).toBe(false);
    expect(scrollers[0].textContent).toContain('settings.teams.drawer.owner');
    expect(scrollers[0].className).toContain('px-6 py-6');
  });

  it('shows role selects, remove and Manage sharing to a caller who can share', async () => {
    listGrants.mockResolvedValue({
      team_role: 'team_member',
      grants: [
        grant(),
        grant({
          access_level: 'editor',
          target_user_id: 'dana',
          target_user_label: 'Dana Whitfield',
        }),
      ],
    });
    setTeam({ member_role: 'team_member' });
    await render();
    await openDrawer();
    const sheet = body().querySelector('[data-slot="sheet-content"]');
    expect(sheet).not.toBeNull();
    expect(sheet!.textContent).toContain(
      'settings.teams.drawer.accessIn(team=Revenue Ops)',
    );
    expect(sheet!.querySelectorAll('[role="combobox"]')).toHaveLength(2);
    expect(
      sheet!.querySelectorAll(
        'button[aria-label="settings.teams.drawer.removeGrant"]',
      ),
    ).toHaveLength(2);
    expect(sheet!.textContent).toContain('settings.teams.drawer.manageSharing');
    // What people here can do, from the settings.
    expect(sheet!.textContent).toContain(
      'settings.teams.capabilities.source.viewers',
    );
    expect(sheet!.textContent).toContain(
      'settings.teams.capabilities.switch.editors_can_share.off',
    );
    // The selected row keeps its tint while the drawer is open.
    expect(rowButtons()[0].className).toContain('bg-secondary');
  });

  it('gives a team admin who cannot share badges and remove only', async () => {
    listGrants.mockResolvedValue({
      team_role: 'team_admin',
      grants: [grant({ caller: VIEWER })],
    });
    await render();
    await openDrawer();
    const sheet = body().querySelector('[data-slot="sheet-content"]')!;
    expect(sheet.querySelectorAll('[role="combobox"]')).toHaveLength(0);
    expect(
      sheet.querySelectorAll(
        'button[aria-label="settings.teams.drawer.removeGrant"]',
      ),
    ).toHaveLength(1);
    expect(sheet.textContent).not.toContain(
      'settings.teams.drawer.manageSharing',
    );
  });

  it('is read-only for a member who cannot share', async () => {
    setTeam({ member_role: 'team_member', owner_id: 'someone' });
    listGrants.mockResolvedValue({
      team_role: 'team_member',
      grants: [grant({ caller: VIEWER })],
    });
    await render();
    await openDrawer();
    const sheet = body().querySelector('[data-slot="sheet-content"]')!;
    expect(sheet.querySelectorAll('[role="combobox"]')).toHaveLength(0);
    expect(
      sheet.querySelectorAll(
        'button[aria-label="settings.teams.drawer.removeGrant"]',
      ),
    ).toHaveLength(0);
    expect(sheet.textContent).toContain(
      'settings.teams.drawer.open(type=settings.teams.resourceType.source)',
    );
  });

  it('opens a shared source on the Knowledge page', async () => {
    listGrants.mockResolvedValue({
      team_role: 'team_member',
      grants: [grant({ caller: VIEWER })],
    });
    await render();
    await openDrawer();
    const open = Array.from(
      body().querySelectorAll<HTMLButtonElement>(
        '[data-slot="sheet-content"] button',
      ),
    ).find((b) =>
      b.textContent?.startsWith('settings.teams.drawer.open(type='),
    )!;
    act(() => open.click());
    await flush();
    expect(body().querySelector('[data-testid="where"]')?.textContent).toBe(
      '/settings/knowledge',
    );
  });

  it('sends target_user_id when removing a per-member grant', async () => {
    listGrants.mockResolvedValue({
      team_role: 'team_admin',
      grants: [
        grant({
          access_level: 'editor',
          target_user_id: 'dana',
          target_user_label: 'Dana Whitfield',
        }),
      ],
    });
    await render();
    await openDrawer();
    const remove = body().querySelector<HTMLButtonElement>(
      'button[aria-label="settings.teams.drawer.removeGrant"]',
    );
    act(() => remove!.click());
    await flush();
    expect(unshare).toHaveBeenCalledWith(
      't1',
      { resource_type: 'source', resource_id: 's1', target_user_id: 'dana' },
      TOKEN,
    );
  });

  it('shows Delete team only to the team owner', async () => {
    await render();
    let menu = body().querySelector('[data-testid="team-menu"]');
    expect(menu?.textContent).toContain('settings.teams.deleteTeam');

    act(() => root.unmount());
    root = createRoot(container);
    setTeam({ owner_id: 'someone-else', member_role: 'team_admin' });
    await render();
    menu = body().querySelector('[data-testid="team-menu"]');
    expect(menu?.textContent).toContain('settings.teams.editTeam');
    expect(menu?.textContent).not.toContain('settings.teams.deleteTeam');
  });

  it('prefers is_owner over owner_id when the server sends it', async () => {
    setTeam({ owner_id: 'me', is_owner: false, member_role: 'team_admin' });
    await render();
    const menu = body().querySelector('[data-testid="team-menu"]');
    expect(menu?.textContent).not.toContain('settings.teams.deleteTeam');
  });
});
