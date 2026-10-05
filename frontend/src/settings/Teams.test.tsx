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

// What a dispatched thunk's unwrap() resolves to (createTeam in tests).
const mockUnwrap = vi.fn(() => Promise.resolve());
// Every dispatched action, so a test can see a toast that shouldn't be there.
const mockDispatch = vi.fn((action: unknown) => {
  void action;
  return { unwrap: () => mockUnwrap() };
});

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
  }),
}));

vi.mock('../navigation/SectionShell', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('../navigation/DetailBreadcrumb', () => ({ default: () => null }));
// Only the page action matters here (it carries no plus).
vi.mock('../components/PageToolbar', () => ({
  default: ({ action }: { action?: React.ReactNode }) => (
    <div data-slot="page-toolbar">{action}</div>
  ),
}));
// A light stand-in for the promise-aware confirm: the open dialog's title,
// description and submit; a resolved submit closes it, a rejected one keeps
// it open with `error`.
vi.mock('../modals/ConfirmationModal', async () => {
  const { useState } = await import('react');
  return {
    default: function MockConfirm(props: {
      modalState: string;
      setModalState: (s: string) => void;
      message: string;
      description?: string;
      submitLabel: string;
      variant?: string;
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
                : (props.error ?? 'actionFailed')}
            </p>
          )}
          <button
            type="button"
            data-variant={props.variant ?? 'default'}
            onClick={submit}
          >
            {props.submitLabel}
          </button>
        </div>
      );
    },
  };
});
vi.mock('../teams/ShareToTeamModal', () => ({
  default: () => <div data-testid="share-modal" />,
}));
// Render the ⋯ menu's options inline so tests can see them.
vi.mock('../components/ui/dropdown-menu', () => ({
  ActionMenu: ({
    options,
  }: {
    options: Array<{ label: string; onClick: () => void }>;
  }) => (
    <div data-testid="team-menu">
      {options.map((o) => (
        <button key={o.label} type="button" onClick={o.onClick}>
          {o.label}
        </button>
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
const addMember = vi.fn();
const removeMember = vi.fn();

vi.mock('../api/services/teamsService', () => ({
  default: {
    listMembers: (...a: unknown[]) => listMembers(...a),
    listGrants: (...a: unknown[]) => listGrants(...a),
    unshare: (...a: unknown[]) => unshare(...a),
    share: (...a: unknown[]) => share(...a),
    getResourceSettings: (...a: unknown[]) => getResourceSettings(...a),
    addMember: (...a: unknown[]) => addMember(...a),
    removeMember: (...a: unknown[]) => removeMember(...a),
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
    addMember.mockReset().mockResolvedValue({ success: true });
    removeMember.mockReset().mockResolvedValue({ success: true });
    mockDispatch.mockClear();
    mockUnwrap.mockReset().mockImplementation(() => Promise.resolve());
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
    // The count is SectionHeader's muted count, not part of the title text.
    const membersHeading = Array.from(body().querySelectorAll('h4')).find(
      (h) => h.firstChild?.textContent === 'settings.teams.members',
    );
    expect(
      membersHeading?.querySelector('[data-slot="count"]')?.textContent,
    ).toBe('#312');
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

  // The verb says "add": page actions carry no plus.
  it('puts no plus on the New team page action', async () => {
    await render();
    const action = Array.from(
      body().querySelectorAll('[data-slot="page-toolbar"] button'),
    ).find((b) => b.textContent === 'settings.teams.newTeam')!;
    expect(action.querySelector('svg')).toBeNull();
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
    expect(
      pills.map((p) => [
        p.firstChild?.textContent,
        p.querySelector('[data-slot="count"]')?.textContent,
      ]),
    ).toEqual([
      ['settings.teams.sharedList.filter.all', '#2'],
      ['settings.teams.sharedList.filter.agent', '#0'],
      ['settings.teams.sharedList.filter.source', '#1'],
      ['settings.teams.sharedList.filter.tool', '#0'],
      ['settings.teams.sharedList.filter.prompt', '#1'],
    ]);
    const sharedHeading = Array.from(body().querySelectorAll('h4')).find(
      (h) => h.firstChild?.textContent === 'settings.teams.sharedResources',
    );
    expect(
      sharedHeading?.querySelector('[data-slot="count"]')?.textContent,
    ).toBe('#2');
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
    // Removing someone's access asks first, in the confirm copy pattern.
    expect(unshare).not.toHaveBeenCalled();
    const confirm = body().querySelector('[data-testid="confirm"]')!;
    expect(confirm.textContent).toContain(
      'settings.teams.share.removeConfirm(name=Dana Whitfield)',
    );
    expect(confirm.textContent).toContain(
      'settings.teams.share.removeConfirmPerson(name=Dana Whitfield,resource=Key Accounts,team=Revenue Ops)',
    );
    const submit = Array.from(
      confirm.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent === 'settings.teams.remove')!;
    expect(submit.getAttribute('data-variant')).toBe('destructive');
    act(() => submit.click());
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

  it('keeps the members row at the 38px field height', async () => {
    listMembers.mockResolvedValue({
      members: Array.from({ length: 25 }, (_, i) => ({
        user_id: `u${i}`,
        email: `m${i}@x.io`,
        role: 'team_member',
        source: 'manual',
      })),
      total: 48,
    });
    await render();
    const add = Array.from(body().querySelectorAll('button')).find((b) =>
      b.textContent?.includes('settings.teams.addMember'),
    )!;
    expect(add.className).toContain('h-9.5');
  });

  it('a failed teams load offers the pill Retry', async () => {
    mockState.teams.error = 'down' as unknown as null;
    try {
      act(() => {
        root.render(
          <MemoryRouter initialEntries={['/teams']}>
            <Teams />
          </MemoryRouter>,
        );
      });
      await flush();
      const retry = Array.from(body().querySelectorAll('button')).find(
        (b) => b.textContent === 'retry',
      );
      expect(retry?.className).toContain('rounded-full');
    } finally {
      mockState.teams.error = null;
    }
  });

  it('an empty team list offers a text-only pill New team', async () => {
    mockState.teams.teams = [];
    act(() => {
      root.render(
        <MemoryRouter initialEntries={['/teams']}>
          <Teams />
        </MemoryRouter>,
      );
    });
    await flush();
    const cta = body().querySelector<HTMLButtonElement>(
      '[data-slot="empty-state"] button',
    )!;
    expect(cta.textContent).toBe('settings.teams.newTeam');
    expect(cta.className).toContain('rounded-full');
    expect(cta.className).toContain('bg-primary');
    expect(cta.querySelector('svg')).toBeNull();
  });

  it('opens the New team sheet on a phone without focusing the field', async () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: query.includes('max-width'),
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      onchange: null,
      dispatchEvent: () => false,
    })) as typeof window.matchMedia;
    try {
      await render();
      const action = Array.from(
        body().querySelectorAll('[data-slot="page-toolbar"] button'),
      ).find((b) => b.textContent === 'settings.teams.newTeam')!;
      act(() => (action as HTMLButtonElement).click());
      await flush();
      const input = body().querySelector<HTMLInputElement>(
        '[data-slot="modal-content"] input',
      )!;
      expect(input).not.toBeNull();
      expect(document.activeElement).not.toBe(input);
    } finally {
      window.matchMedia = original;
    }
  });

  const typeInto = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!;
    act(() => {
      setter.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };

  const dialogButton = (label: string) =>
    Array.from(
      body().querySelectorAll<HTMLButtonElement>(
        '[data-slot="modal-content"] button',
      ),
    ).find((b) => b.textContent === label)!;

  it('shows a failed members load as an error with Retry, not "no members"', async () => {
    listMembers.mockRejectedValueOnce(new Error('down'));
    await render();
    const state = body().querySelector<HTMLElement>(
      '[data-slot="empty-state"][data-tone="destructive"]',
    )!;
    expect(state).not.toBeNull();
    expect(state.textContent).toContain('settings.teams.membersLoadError');
    expect(body().textContent).not.toContain('settings.teams.noMembers');
    listMembers.mockResolvedValue({ members: [] });
    const retry = Array.from(state.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    )!;
    const calls = listMembers.mock.calls.length;
    act(() => retry.click());
    await flush();
    expect(listMembers.mock.calls.length).toBe(calls + 1);
    expect(
      body().querySelector(
        '[data-slot="empty-state"][data-tone="destructive"]',
      ),
    ).toBeNull();
    expect(body().textContent).toContain('settings.teams.noMembers');
  });

  it('shows pending on Create team while the request runs', async () => {
    let finish!: (team: unknown) => void;
    mockUnwrap.mockImplementation(
      () => new Promise<void>((resolve) => (finish = resolve as never)),
    );
    await render();
    const action = Array.from(
      body().querySelectorAll('[data-slot="page-toolbar"] button'),
    ).find((b) => b.textContent === 'settings.teams.newTeam')!;
    act(() => (action as HTMLButtonElement).click());
    await flush();
    typeInto(
      body().querySelector<HTMLInputElement>(
        '[data-slot="modal-content"] input',
      )!,
      'Sales',
    );
    act(() => dialogButton('settings.teams.create').click());
    await flush();
    const submit = dialogButton('settings.teams.create');
    expect(submit.getAttribute('aria-busy')).toBe('true');
    expect(submit.disabled).toBe(true);
    await act(async () => finish({ id: 't2', name: 'Sales' }));
    await flush();
  });

  it('shows pending on Add member while the request runs', async () => {
    let finish!: (value: unknown) => void;
    addMember.mockImplementation(
      () => new Promise((resolve) => (finish = resolve)),
    );
    await render();
    const open = Array.from(body().querySelectorAll('button')).find(
      (b) => b.textContent === 'settings.teams.addMember',
    )!;
    act(() => open.click());
    await flush();
    typeInto(
      body().querySelector<HTMLInputElement>(
        '[data-slot="modal-content"] input[type="email"]',
      )!,
      'a@x.io',
    );
    act(() => dialogButton('settings.teams.add').click());
    await flush();
    expect(dialogButton('settings.teams.add').getAttribute('aria-busy')).toBe(
      'true',
    );
    // Enter while pending doesn't send a second request.
    const input = body().querySelector<HTMLInputElement>(
      '[data-slot="modal-content"] input[type="email"]',
    )!;
    act(() => {
      input.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
    expect(addMember).toHaveBeenCalledTimes(1);
    await act(async () => finish({ success: true }));
    await flush();
  });

  // A dispatched destructive toast (the page's old failure path).
  const toasts = () =>
    mockDispatch.mock.calls
      .map(([action]) => action as { payload?: { variant?: string } })
      .filter((a) => a?.payload?.variant === 'destructive');

  const confirmSubmit = (label: string) =>
    Array.from(
      body().querySelectorAll<HTMLButtonElement>(
        '[data-testid="confirm"] button',
      ),
    ).find((b) => b.textContent === label)!;

  it('keeps a failed remove member open with the domain error, no toast', async () => {
    listMembers.mockResolvedValue({
      members: [{ user_id: 'priya', email: 'priya@x.io', role: 'team_member' }],
    });
    removeMember.mockRejectedValue(new Error('Request failed (500)'));
    await render();
    const trash = body().querySelector<HTMLButtonElement>(
      'button[aria-label="settings.teams.remove"]',
    )!;
    act(() => trash.click());
    await flush();
    act(() => confirmSubmit('settings.teams.remove').click());
    await flush();
    expect(removeMember).toHaveBeenCalledWith('t1', 'priya', TOKEN);
    const confirm = body().querySelector('[data-testid="confirm"]')!;
    expect(confirm).not.toBeNull();
    // The dialog still names the member it failed to remove.
    expect(confirm.textContent).toContain('name=priya@x.io');
    expect(
      body().querySelector('[data-testid="confirm-error"]')?.textContent,
    ).toBe('settings.teams.removeMemberError');
    expect(confirm.textContent).not.toContain('Request failed (500)');
    expect(toasts()).toHaveLength(0);
  });

  // What teamsService throws for a non-2xx: its message is the server's.
  const serverError = (message: string) =>
    Object.assign(new Error(message), { name: 'TeamsApiError' });

  it("shows the server's reason when removing a member is refused", async () => {
    listMembers.mockResolvedValue({
      members: [{ user_id: 'priya', email: 'priya@x.io', role: 'team_admin' }],
    });
    removeMember.mockRejectedValue(serverError('Cannot remove the last admin'));
    await render();
    act(() =>
      body()
        .querySelector<HTMLButtonElement>(
          'button[aria-label="settings.teams.remove"]',
        )!
        .click(),
    );
    await flush();
    act(() => confirmSubmit('settings.teams.remove').click());
    await flush();
    expect(
      body().querySelector('[data-testid="confirm-error"]')?.textContent,
    ).toBe('Cannot remove the last admin');
  });

  it("shows the server's reason when deleting a team is refused", async () => {
    await render();
    mockUnwrap.mockImplementation(() =>
      Promise.reject(serverError('Only the owner can delete a team')),
    );
    const menuItem = Array.from(
      body().querySelectorAll<HTMLButtonElement>(
        '[data-testid="team-menu"] button',
      ),
    ).find((b) => b.textContent === 'settings.teams.deleteTeam')!;
    act(() => menuItem.click());
    await flush();
    act(() => confirmSubmit('settings.teams.delete').click());
    await flush();
    expect(
      body().querySelector('[data-testid="confirm-error"]')?.textContent,
    ).toBe('Only the owner can delete a team');
  });

  it('closes the remove member confirm once the request succeeds', async () => {
    listMembers.mockResolvedValue({
      members: [{ user_id: 'priya', email: 'priya@x.io', role: 'team_member' }],
    });
    await render();
    act(() =>
      body()
        .querySelector<HTMLButtonElement>(
          'button[aria-label="settings.teams.remove"]',
        )!
        .click(),
    );
    await flush();
    act(() => confirmSubmit('settings.teams.remove').click());
    await flush();
    expect(body().querySelector('[data-testid="confirm"]')).toBeNull();
  });

  it('keeps a failed delete team open with the domain error, no toast', async () => {
    await render();
    mockUnwrap.mockImplementation(() =>
      Promise.reject(new Error('Request failed (500)')),
    );
    const menuItem = Array.from(
      body().querySelectorAll<HTMLButtonElement>(
        '[data-testid="team-menu"] button',
      ),
    ).find((b) => b.textContent === 'settings.teams.deleteTeam')!;
    act(() => menuItem.click());
    await flush();
    act(() => confirmSubmit('settings.teams.delete').click());
    await flush();
    expect(body().querySelector('[data-testid="confirm"]')).not.toBeNull();
    expect(
      body().querySelector('[data-testid="confirm-error"]')?.textContent,
    ).toBe('settings.teams.deleteTeamError');
    expect(toasts()).toHaveLength(0);
  });

  it('keeps a failed unshare open with the domain error, no toast', async () => {
    listGrants.mockResolvedValue({
      team_role: 'team_admin',
      grants: [grant()],
    });
    unshare.mockRejectedValue(new Error('Request failed (500)'));
    await render();
    await openDrawer();
    act(() =>
      body()
        .querySelector<HTMLButtonElement>(
          'button[aria-label="settings.teams.drawer.removeGrant"]',
        )!
        .click(),
    );
    await flush();
    act(() => confirmSubmit('settings.teams.remove').click());
    await flush();
    expect(unshare).toHaveBeenCalled();
    expect(body().querySelector('[data-testid="confirm"]')).not.toBeNull();
    expect(
      body().querySelector('[data-testid="confirm-error"]')?.textContent,
    ).toBe('settings.teams.unshareError');
    expect(toasts()).toHaveLength(0);
    // The grant row is still there and no longer busy.
    expect(
      body().querySelector<HTMLButtonElement>(
        'button[aria-label="settings.teams.drawer.removeGrant"]',
      )!.disabled,
    ).toBe(false);
  });
});
