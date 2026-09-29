import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const mockState = {
  preference: { token: 'tok' },
  teams: {
    teams: [
      { id: 't1', name: 'Logistics', slug: 'logistics', owner_id: 'u1' },
      { id: 't2', name: 'Sales Ops', slug: 'sales', owner_id: 'u1' },
    ],
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
const updateResourceSettings = vi.fn();
const listMembers = vi.fn();
const share = vi.fn();
const unshare = vi.fn();

vi.mock('../api/services/teamsService', () => ({
  default: {
    listResourceShares: (...a: unknown[]) => listResourceShares(...a),
    getResourceSettings: (...a: unknown[]) => getResourceSettings(...a),
    updateResourceSettings: (...a: unknown[]) => updateResourceSettings(...a),
    listMembers: (...a: unknown[]) => listMembers(...a),
    share: (...a: unknown[]) => share(...a),
    unshare: (...a: unknown[]) => unshare(...a),
  },
}));

const setCredentialMode = vi.fn();
vi.mock('../api/services/connectorsService', () => ({
  default: {
    setCredentialMode: (...a: unknown[]) => setCredentialMode(...a),
  },
}));

// Mark formatted counts so a raw number in the UI shows up in a test.
vi.mock('../utils/dateTimeUtils', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../utils/dateTimeUtils')>()),
  formatCount: (value: number) => `#${value}`,
}));

import ShareToTeamModal, { type ShareCredentials } from './ShareToTeamModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const OWNER_ACTIONS = ['delete', 'edit', 'manage_settings', 'share', 'use'];
const EDITOR_ACTIONS = ['edit', 'share', 'use'];

const settingsResponse = (
  values: Record<string, boolean> = {},
  access: 'owner' | 'editor' = 'owner',
) => ({
  success: true,
  resource_type: 'agent',
  resource_id: 'a1',
  settings: [
    { key: 'editors_can_share', default: false },
    { key: 'editors_can_delete', default: false },
    { key: 'editors_can_manage_access_details', default: true },
    { key: 'viewers_can_see_logs', default: false },
  ].map((s) => ({ ...s, value: values[s.key] ?? s.default })),
  access,
  allowed_actions: access === 'owner' ? OWNER_ACTIONS : EDITOR_ACTIONS,
});

const apiError = (message: string) =>
  Object.assign(new Error(message), { name: 'TeamsApiError', status: 403 });

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
  Array.from(body().querySelectorAll('button')).find((b) =>
    b.textContent?.trim().startsWith(label),
  );

describe('ShareToTeamModal', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    listResourceShares.mockReset().mockResolvedValue({ shares: [] });
    getResourceSettings.mockReset().mockResolvedValue(settingsResponse());
    updateResourceSettings.mockReset();
    listMembers.mockReset().mockResolvedValue({ members: [] });
    share.mockReset().mockResolvedValue({ success: true });
    unshare.mockReset().mockResolvedValue({ success: true });
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
        <ShareToTeamModal
          resourceType="agent"
          resourceId="a1"
          resourceName="QBR Report Builder"
          onClose={() => undefined}
        />,
      );
    });
    await flush();
  };

  describe('access settings', () => {
    it('shows a collapsed Access settings toggle to the owner', async () => {
      await render();
      const toggle = buttonByText('settings.teams.accessSettings.title');
      expect(toggle).toBeDefined();
      expect(toggle?.getAttribute('aria-expanded')).toBe('false');
      // An inline disclosure (no Card around it to draw section-toggle's
      // ring), so the button shows its own keyboard focus.
      expect(toggle?.getAttribute('data-variant')).toBe('link');
      expect(toggle?.className).toContain('focus-visible:ring-3');
      expect(toggle?.className).not.toContain('focus-visible:ring-0');
      expect(body().querySelectorAll('[role="switch"]')).toHaveLength(0);
      act(() => toggle!.click());
      expect(body().querySelectorAll('[role="switch"]')).toHaveLength(4);
      expect(text()).toContain(
        'settings.teams.accessSettings.agent.editors_can_share.label',
      );
    });

    it('opens by default when a setting is off its default', async () => {
      getResourceSettings.mockResolvedValue(
        settingsResponse({ editors_can_share: true }),
      );
      await render();
      const toggle = buttonByText('settings.teams.accessSettings.title');
      expect(toggle?.getAttribute('aria-expanded')).toBe('true');
      expect(body().querySelectorAll('[role="switch"]')).toHaveLength(4);
    });

    it('is hidden from an editor without manage_settings', async () => {
      getResourceSettings.mockResolvedValue(settingsResponse({}, 'editor'));
      await render();
      expect(buttonByText('settings.teams.accessSettings.title')).toBe(
        undefined,
      );
    });

    it('PUTs the new value when a switch is toggled', async () => {
      updateResourceSettings.mockResolvedValue(
        settingsResponse({ editors_can_share: true }),
      );
      await render();
      act(() => buttonByText('settings.teams.accessSettings.title')!.click());
      const sw = body().querySelector<HTMLButtonElement>(
        '#share-setting-editors_can_share',
      );
      act(() => sw!.click());
      await flush();
      expect(updateResourceSettings).toHaveBeenCalledWith(
        'agent',
        'a1',
        { editors_can_share: true },
        'tok',
      );
      expect(sw!.getAttribute('aria-checked')).toBe('true');
    });

    it('reverts the switch and shows an Alert when the PUT fails', async () => {
      updateResourceSettings.mockRejectedValue(apiError('Forbidden'));
      await render();
      act(() => buttonByText('settings.teams.accessSettings.title')!.click());
      const sw = body().querySelector<HTMLButtonElement>(
        '#share-setting-editors_can_share',
      );
      act(() => sw!.click());
      await flush();
      expect(sw!.getAttribute('aria-checked')).toBe('false');
      const alert = body().querySelector('[role="alert"]');
      expect(alert?.textContent).toContain('Forbidden');
    });
  });

  describe('editor hint', () => {
    it('describes the default editor rights', async () => {
      await render();
      const hint = body().querySelector('[data-testid="share-editor-hint"]');
      expect(hint?.textContent).toContain('settings.teams.editorHint.agent');
      expect(hint?.textContent).toContain(
        'settings.teams.editorHint.noShareNoDelete',
      );
      expect(hint?.className).toContain('text-muted-foreground');
      expect(hint?.className).toContain('mt-1.5');
      expect(hint?.className).toContain('text-xs');
    });

    it('says editors can also share when the switch is on', async () => {
      getResourceSettings.mockResolvedValue(
        settingsResponse({
          editors_can_share: true,
          editors_can_manage_access_details: false,
        }),
      );
      await render();
      const hint = body().querySelector('[data-testid="share-editor-hint"]');
      expect(hint?.textContent).toContain(
        'settings.teams.editorHint.agentNoAccessDetails',
      );
      expect(hint?.textContent).toContain(
        'settings.teams.editorHint.shareOnly',
      );
    });
  });

  describe('long list', () => {
    const manyShares = (n: number) =>
      Array.from({ length: n }, (_, i) => ({
        team_id: i % 2 ? 't1' : 't2',
        team_name: i % 2 ? 'Logistics' : 'Sales Ops',
        access_level: i < 2 ? 'editor' : 'viewer',
        target_user_id: i < 2 ? null : `user-${i}`,
        created_at: `2026-09-${String(10 + i).padStart(2, '0')}T00:00:00Z`,
      }));

    it('shows every grant and no Show all link up to 5', async () => {
      listResourceShares.mockResolvedValue({ shares: manyShares(5) });
      await render();
      expect(buttonByText('settings.teams.share.showAll')).toBe(undefined);
      // You + 5 grants.
      expect(body().querySelectorAll('[data-slot="list-row"]')).toHaveLength(6);
    });

    it('shows You + 3 most recent and a Show all link above 5', async () => {
      listResourceShares.mockResolvedValue({ shares: manyShares(8) });
      await render();
      const rows = body().querySelectorAll('[data-slot="list-row"]');
      expect(rows).toHaveLength(4);
      // Most recent first: user-7, user-6, user-5.
      expect(rows[1].textContent).toContain('user-7');
      expect(text()).toContain(
        'settings.teams.share.andMore(count=5,formatted=#5)',
      );
      const showAll = buttonByText('settings.teams.share.showAll');
      expect(showAll?.textContent).toContain(
        'settings.teams.share.showAll(formatted=#8)',
      );
      expect(showAll?.getAttribute('data-variant')).toBe('link');
      expect(body().querySelector('.max-h-72')).toBeNull();
    });

    it('opens the full list step with search and filters', async () => {
      listResourceShares.mockResolvedValue({ shares: manyShares(8) });
      await render();
      act(() => buttonByText('settings.teams.share.showAll')!.click());
      expect(text()).toContain(
        'settings.teams.share.allSummary(name=QBR Report Builder,teams=#2,people=#6)',
      );
      expect(buttonByText('settings.teams.share.back')).toBeDefined();
      // You + all 8.
      expect(body().querySelectorAll('[data-slot="list-row"]')).toHaveLength(9);
      expect(
        Array.from(body().querySelectorAll('[role="radio"]')).map(
          (p) => p.textContent,
        ),
      ).toEqual([
        'settings.teams.share.filter.all #8',
        'settings.teams.share.filter.teams #2',
        'settings.teams.share.filter.people #6',
        'settings.teams.share.filter.editors #2',
      ]);

      const teamsPill = Array.from(
        body().querySelectorAll<HTMLButtonElement>('[role="radio"]'),
      ).find((b) =>
        b.textContent?.includes('settings.teams.share.filter.teams'),
      );
      act(() => teamsPill!.click());
      // The two whole-team grants; You is only listed under All.
      expect(body().querySelectorAll('[data-slot="list-row"]')).toHaveLength(2);

      const allPill = Array.from(
        body().querySelectorAll<HTMLButtonElement>('[role="radio"]'),
      ).find((b) => b.textContent?.includes('settings.teams.share.filter.all'));
      act(() => allPill!.click());
      const search = body().querySelector<HTMLInputElement>(
        'input[aria-label="settings.teams.share.searchAccess"]',
      );
      act(() => {
        const setter = Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          'value',
        )!.set!;
        setter.call(search, 'user-6');
        search!.dispatchEvent(new Event('input', { bubbles: true }));
      });
      const rows = body().querySelectorAll('[data-slot="list-row"]');
      expect(rows).toHaveLength(1);
      expect(rows[0].textContent).toContain('user-6');

      // No match: the "no results" EmptyState line, not a bare paragraph.
      act(() => {
        const setter = Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          'value',
        )!.set!;
        setter.call(search, 'nobody-here');
        search!.dispatchEvent(new Event('input', { bubbles: true }));
      });
      const empty = body().querySelector('[data-slot="empty-state"]');
      expect(empty?.getAttribute('data-size')).toBe('xs');
      expect(empty?.querySelector('img')).toBeNull();
      expect(empty?.textContent).toContain('settings.teams.share.noMatches');

      act(() => buttonByText('settings.teams.share.back')!.click());
      expect(buttonByText('settings.teams.share.showAll')).toBeDefined();
    });
  });

  it('shows the server message when a share fails', async () => {
    listResourceShares.mockResolvedValue({
      shares: [
        {
          team_id: 't1',
          team_name: 'Logistics',
          access_level: 'viewer',
          target_user_id: null,
        },
      ],
    });
    unshare.mockRejectedValue(apiError('Not allowed'));
    await render();
    const remove = body().querySelector<HTMLButtonElement>(
      'button[aria-label="settings.teams.share.removeAccess"]',
    );
    act(() => remove!.click());
    await flush();
    expect(body().querySelector('[role="alert"]')?.textContent).toContain(
      'Not allowed',
    );
  });
});

describe('ShareToTeamModal credentials', () => {
  let container: HTMLDivElement;
  let root: Root;

  const credentials = (
    overrides: Partial<ShareCredentials> = {},
  ): ShareCredentials => ({
    toolId: 'tool-1',
    connectorName: 'Linear',
    account: 'lena@meridian.example',
    mode: 'owner',
    hasWrites: false,
    ...overrides,
  });

  beforeEach(() => {
    listResourceShares.mockReset().mockResolvedValue({ shares: [] });
    getResourceSettings.mockReset().mockResolvedValue(settingsResponse());
    listMembers.mockReset().mockResolvedValue({ members: [] });
    setCredentialMode.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = async (creds?: ShareCredentials) => {
    act(() => {
      root.render(
        <ShareToTeamModal
          resourceType="tool"
          resourceId="tool-1"
          resourceName="Linear"
          credentials={creds}
          onClose={() => undefined}
        />,
      );
    });
    await flush();
  };

  // A compact segmented choice, not a pair of picker tiles.
  const toggle = (value: 'owner' | 'member') =>
    Array.from(
      body().querySelectorAll<HTMLButtonElement>(
        '[data-slot="toggle-group-item"]',
      ),
    ).find(
      (item) =>
        item.textContent === `settings.connectors.sharing.${value}Short`,
    )!;
  const picker = () =>
    body().querySelector<HTMLButtonElement>('[role="combobox"]')!;

  it('shows nothing about accounts for a resource without a connection', async () => {
    await render();
    expect(text()).not.toContain('settings.connectors.share.heading');
  });

  it('says whose account members use on a tool that only reads', async () => {
    await render(credentials());
    expect(body().querySelector('[role="note"]')).toBeNull();
    expect(body().querySelector('[data-slot="option-card"]')).toBeNull();
    expect(toggle('owner').getAttribute('aria-checked')).toBe('true');
    expect(text()).toContain(
      'settings.connectors.share.ownerWarning(account=lena@meridian.example',
    );
  });

  it('asks only for the confirmation on a tool that can act, with no warning box', async () => {
    await render(credentials({ hasWrites: true }));
    expect(body().querySelector('[role="note"]')).toBeNull();
    expect(text()).not.toContain('settings.connectors.share.ownerWarning');
    expect(body().querySelector('#share-confirm-writes')).not.toBeNull();
  });

  it('blocks sharing an owner-mode tool with writes until confirmed', async () => {
    await render(credentials({ hasWrites: true }));
    expect(picker().disabled).toBe(true);
    const box = body().querySelector<HTMLButtonElement>(
      '#share-confirm-writes',
    )!;
    await act(async () => box.click());
    expect(picker().disabled).toBe(false);
  });

  it('saves a mode change and rolls back when the save fails', async () => {
    setCredentialMode.mockResolvedValue({ success: false });
    await render(credentials({ hasWrites: true }));
    await act(async () => toggle('member').click());
    await flush();
    expect(setCredentialMode).toHaveBeenCalledWith('tool-1', 'member', 'tok');
    expect(toggle('owner').getAttribute('aria-checked')).toBe('true');
    expect(text()).toContain('settings.connectors.share.saveFailed');
  });

  it('locks the other mode when an admin forces one', async () => {
    await render(credentials({ forcedMode: 'member' }));
    expect(toggle('member').getAttribute('aria-checked')).toBe('true');
    expect(toggle('owner').disabled).toBe(true);
    expect(text()).toContain('settings.connectors.share.forced');
  });

  describe('access settings of a connected tool', () => {
    const toolSettings = (values: Record<string, boolean> = {}) => ({
      success: true,
      resource_type: 'tool',
      resource_id: 'tool-1',
      settings: [
        { key: 'editors_can_change_credentials', default: true },
        { key: 'editors_can_share', default: false },
        { key: 'viewers_can_use_in_agents', default: true },
      ].map((s) => ({ ...s, value: values[s.key] ?? s.default })),
      access: 'owner',
      allowed_actions: OWNER_ACTIONS,
    });
    const openSettings = () =>
      act(() => buttonByText('settings.teams.accessSettings.title')!.click());

    beforeEach(() => {
      getResourceSettings.mockResolvedValue(toolSettings());
    });

    // The connection's secret is the owner's alone, so the switch would
    // promise editors something the server refuses.
    it('has no switch for editors to change credentials', async () => {
      await render(credentials());
      openSettings();
      expect(
        body().querySelector('#share-setting-editors_can_change_credentials'),
      ).toBeNull();
      expect(
        body().querySelector('#share-setting-viewers_can_use_in_agents'),
      ).not.toBeNull();
    });

    it('keeps the switch for a tool with no connection', async () => {
      await render();
      openSettings();
      expect(
        body().querySelector('#share-setting-editors_can_change_credentials'),
      ).not.toBeNull();
    });

    it('tells editors they cannot change credentials', async () => {
      await render(credentials());
      const hint = body().querySelector('[data-testid="share-editor-hint"]');
      expect(hint?.textContent).toContain(
        'settings.teams.editorHint.toolNoCredentials',
      );
    });

    it("says viewers' runs use each member's own account in member mode", async () => {
      await render(credentials({ mode: 'member' }));
      openSettings();
      expect(text()).toContain(
        'settings.teams.accessSettings.tool.viewers_can_use_in_agents.descriptionMember',
      );
    });

    it("says viewers' runs use the owner's credentials in owner mode", async () => {
      await render(credentials());
      openSettings();
      expect(text()).toContain(
        'settings.teams.accessSettings.tool.viewers_can_use_in_agents.description',
      );
      expect(text()).not.toContain('descriptionMember');
    });
  });

  describe('for an editor allowed to share', () => {
    const shared = (overrides: Partial<ShareCredentials> = {}) =>
      credentials({ account: '', readOnly: true, ...overrides });

    it("shows whose account shares use but doesn't let them change it", async () => {
      await render(shared());
      expect(toggle('owner').getAttribute('aria-checked')).toBe('true');
      expect(toggle('owner').disabled).toBe(true);
      expect(toggle('member').disabled).toBe(true);
      expect(text()).toContain('settings.connectors.share.ownerChooses');
      expect(text()).toContain(
        'settings.connectors.share.ownerWarningShared(name=Linear)',
      );
    });

    it('still asks for the write confirmation before adding people', async () => {
      await render(shared({ hasWrites: true }));
      expect(text()).toContain(
        'settings.connectors.share.confirmWriteShared(name=Linear)',
      );
      expect(picker().disabled).toBe(true);
      await act(async () =>
        body()
          .querySelector<HTMLButtonElement>('#share-confirm-writes')!
          .click(),
      );
      expect(picker().disabled).toBe(false);
    });
  });
});
