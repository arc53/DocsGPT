import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

const mockState = {
  preference: { token: 'tok' },
  teams: {
    teams: [] as Array<Record<string, unknown>>,
    loading: false,
    error: null as string | null,
  },
  workspace: {
    current: 'personal',
    workspaces: [{ id: 'personal', kind: 'personal', name: 'Personal' }],
    loaded: true,
    loading: false,
    epoch: 0,
    lastReason: null,
    latestRequestId: null,
  },
};

const mockDispatch = vi.fn((action: unknown) => {
  void action;
  return { unwrap: () => Promise.resolve() };
});

vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) => selector(mockState),
  useDispatch: () => mockDispatch,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts?.name ? `${key}(${opts.name})` : key,
  }),
}));

vi.mock('../../navigation/SectionShell', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('../../navigation/DetailBreadcrumb', () => ({ default: () => null }));

// Each tab is a marker naming the role it was given.
vi.mock('./MembersTab', () => ({
  default: ({ role }: { role: string }) => (
    <div data-testid="tab-members" data-role={role} />
  ),
}));
vi.mock('./SharedItemsTab', () => ({
  default: ({ role }: { role: string }) => (
    <div data-testid="tab-shared" data-role={role} />
  ),
}));
vi.mock('./SettingsTab', () => ({
  default: ({ role }: { role: string }) => (
    <div data-testid="tab-settings" data-role={role} />
  ),
}));
vi.mock('./UsageTab', () => ({
  default: ({ role }: { role: string }) => (
    <div data-testid="tab-usage" data-role={role} />
  ),
}));

const listGrants = vi.fn();
vi.mock('../../api/services/teamsService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/services/teamsService')>()),
  default: {
    listGrants: (...a: unknown[]) => listGrants(...a),
    list: () => Promise.resolve({ teams: [] }),
  },
}));

import Teams from '../../settings/Teams';
import { TEAM_TABS, teamPath, visibleTeamTabs } from './teamTabs';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const flush = async () => {
  for (let i = 0; i < 6; i += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
};

const body = () => document.body;

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>;
}

describe('the team tabs config', () => {
  it('has a Usage tab for the owner and admins', () => {
    const usage = TEAM_TABS.find((tab) => tab.key === 'usage');
    expect(usage?.enabled).toBe(true);
    expect(visibleTeamTabs('owner').map((tab) => tab.key)).toEqual([
      'members',
      'shared',
      'usage',
      'settings',
    ]);
    expect(visibleTeamTabs('admin').map((tab) => tab.key)).toEqual([
      'members',
      'shared',
      'usage',
      'settings',
    ]);
    expect(visibleTeamTabs('editor').map((tab) => tab.key)).toEqual([
      'members',
      'shared',
    ]);
  });

  it('puts the tab in the path, and Members at the team root', () => {
    expect(teamPath('t1')).toBe('/teams/t1');
    expect(teamPath('t1', 'members')).toBe('/teams/t1');
    expect(teamPath('t1', 'settings')).toBe('/teams/t1/settings');
  });
});

describe('TeamDetail', () => {
  let container: HTMLDivElement;
  let root: Root;

  const setTeam = (over: Record<string, unknown> = {}) => {
    mockState.teams.teams = [
      {
        id: 't1',
        name: 'Operations',
        slug: 'operations',
        owner_id: 'me',
        is_owner: true,
        role: 'owner',
        member_role: 'team_admin',
        member_count: 12,
        ...over,
      },
    ];
  };

  beforeEach(() => {
    setTeam();
    mockState.teams.error = null;
    listGrants.mockReset().mockResolvedValue({ grants: [], role: null });
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

  const render = async (path: string) => {
    act(() => {
      root.render(
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/teams/*" element={<Teams />} />
          </Routes>
          <Where />
        </MemoryRouter>,
      );
    });
    await flush();
  };

  const tabLinks = () =>
    Array.from(
      body().querySelectorAll<HTMLElement>(
        'nav[aria-label="settings.teams.tabs.label"] [data-slot="nav-tab"]',
      ),
    );
  const where = () =>
    body().querySelector('[data-testid="where"]')?.textContent;

  it('opens on Members, with a tab per page the role may open', async () => {
    await render('/teams/t1');
    expect(tabLinks().map((tab) => tab.textContent)).toEqual([
      'settings.teams.tabs.members',
      'settings.teams.tabs.shared',
      'settings.teams.tabs.usage',
      'settings.teams.tabs.settings',
    ]);
    expect(tabLinks()[0].getAttribute('aria-current')).toBe('page');
    expect(body().querySelector('[data-testid="tab-members"]')).not.toBeNull();
  });

  it('reads the tab from the URL', async () => {
    await render('/teams/t1/shared');
    expect(tabLinks()[1].getAttribute('aria-current')).toBe('page');
    expect(body().querySelector('[data-testid="tab-shared"]')).not.toBeNull();
    expect(body().querySelector('[data-testid="tab-members"]')).toBeNull();
  });

  it('links each tab to its own path', async () => {
    await render('/teams/t1');
    const shared = tabLinks()[1].closest('a') ?? tabLinks()[1];
    expect(shared.getAttribute('href')).toBe('/teams/t1/shared');
    act(() => (shared as HTMLAnchorElement).click());
    await flush();
    expect(where()).toBe('/teams/t1/shared');
  });

  it('gives a Viewer no Settings tab, and its path goes to Members', async () => {
    setTeam({ role: 'viewer', member_role: 'team_member', is_owner: false });
    await render('/teams/t1/settings');
    expect(where()).toBe('/teams/t1');
    expect(tabLinks().map((tab) => tab.textContent)).toEqual([
      'settings.teams.tabs.members',
      'settings.teams.tabs.shared',
    ]);
    expect(
      body()
        .querySelector('[data-testid="tab-members"]')
        ?.getAttribute('data-role'),
    ).toBe('viewer');
  });

  it('opens the Usage tab for the owner', async () => {
    await render('/teams/t1/usage');
    expect(where()).toBe('/teams/t1/usage');
    expect(
      body()
        .querySelector('[data-testid="tab-usage"]')
        ?.getAttribute('data-role'),
    ).toBe('owner');
  });

  it("sends an Editor's Usage path to Members", async () => {
    setTeam({ role: 'editor', member_role: 'team_member', is_owner: false });
    await render('/teams/t1/usage');
    expect(where()).toBe('/teams/t1');
    expect(body().textContent).not.toContain('settings.teams.tabs.usage');
  });

  it("takes the caller's live role from the grants answer", async () => {
    setTeam({ role: 'viewer', member_role: 'team_member', is_owner: false });
    listGrants.mockResolvedValue({
      grants: [],
      role: 'admin',
      team_role: 'team_admin',
    });
    await render('/teams/t1/settings');
    expect(where()).toBe('/teams/t1/settings');
    expect(
      body()
        .querySelector('[data-testid="tab-settings"]')
        ?.getAttribute('data-role'),
    ).toBe('admin');
  });

  it('says so when the team is not one of yours', async () => {
    await render('/teams/nope');
    expect(body().textContent).toContain('settings.teams.detail.notFound');
    expect(tabLinks()).toHaveLength(0);
  });

  it('opens a team the old way (navigation state) at its own path', async () => {
    act(() => {
      root.render(
        <MemoryRouter
          initialEntries={[{ pathname: '/teams', state: { openTeamId: 't1' } }]}
        >
          <Routes>
            <Route path="/teams/*" element={<Teams />} />
          </Routes>
          <Where />
        </MemoryRouter>,
      );
    });
    await flush();
    expect(where()).toBe('/teams/t1');
  });
});
