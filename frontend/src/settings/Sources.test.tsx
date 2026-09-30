import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';

const { dispatch, service, view, connectors, uploadProps, reconnect } =
  vi.hoisted(() => ({
    reconnect: vi.fn(),
    uploadProps: vi.fn(),
    connectors: { connections: [] as Record<string, unknown>[] },
    // The heavy children: each view reports the canEdit it was given.
    view:
      (testId: string) =>
      ({ canEdit }: { canEdit?: boolean }) => (
        <div data-testid={testId} data-can-edit={String(canEdit)} />
      ),
    dispatch: vi.fn(),
    service: {
      getConfig: vi.fn(),
      manageSync: vi.fn(),
      syncSource: vi.fn(),
      syncConnector: vi.fn(),
      reingestSource: vi.fn(),
      getDirectoryStructure: vi.fn(),
    },
  }));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('react-redux', () => ({
  useDispatch: () => dispatch,
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({
      preference: { token: null },
      upload: { tasks: [] },
      graphBuild: { builds: {} },
      connectors: { connections: connectors.connections, loaded: true },
    }),
}));

vi.mock('../hooks', () => ({
  useDebouncedValue: (value: unknown) => value,
  useLoaderState: (initial: boolean) => useState(initial),
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

vi.mock('../api/services/userService', () => ({ default: service }));
vi.mock('../api/services/modelService', () => ({
  default: { getModels: vi.fn(), transformModels: vi.fn(() => []) },
}));
vi.mock('../preferences/preferenceApi', () => ({
  getDocs: vi.fn(async () => []),
  getDocsWithPagination: vi.fn(async () => null),
}));

vi.mock('../components/Chunks', () => ({ default: view('chunks') }));
vi.mock('../components/FileTree', () => ({ default: view('file-tree') }));
vi.mock('../components/ConnectorTree', () => ({
  default: view('connector-tree'),
}));
vi.mock('../components/WikiViewer', () => ({ default: view('wiki') }));
vi.mock('../components/graph/GraphSourceView', () => ({
  default: view('graph'),
}));
vi.mock('./SourceConfigModal', () => ({ default: () => null }));
vi.mock('./TestRetrievalModal', () => ({ default: () => null }));
vi.mock('./ConvertToWikiModal', () => ({ default: () => null }));
vi.mock('./WikiSettingsModal', () => ({
  default: ({ document }: { document: { name: string } }) => (
    <div data-testid="wiki-settings">{document.name}</div>
  ),
}));
vi.mock('./EnableGraphRAGModal', () => ({ default: () => null }));
vi.mock('../teams/ShareToTeamModal', () => ({ default: () => null }));
vi.mock('../connectors/SignInAgainNotice', () => ({
  useSignInAgain: () => ({ reconnect, modals: null }),
}));
vi.mock('../upload/Upload', () => ({
  default: (props: unknown) => {
    uploadProps(props);
    return null;
  },
}));

import type { Doc } from '../models/misc';
import { getDocsWithPagination } from '../preferences/preferenceApi';
import Sources from './Sources';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const OWNER = ['delete', 'edit', 'manage_settings', 'reconnect', 'share'];
const EDITOR = ['edit', 'use', 'view_config'];
const VIEWER = ['use', 'view_config'];

const doc = (fields: Partial<Doc> = {}): Doc => ({
  id: 'src-1',
  name: 'Contracts',
  date: '',
  model: '',
  ...fields,
});

describe('Sources access', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    dispatch.mockReset();
    Object.values(service).forEach((fn) => fn.mockReset());
    service.getConfig.mockResolvedValue({ json: async () => ({}) });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  function Where() {
    const location = useLocation();
    return <div data-testid="where">{location.pathname + location.search}</div>;
  }

  const render = async (document: Doc) => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <Sources
            paginatedDocuments={[document]}
            handleDeleteDocument={vi.fn()}
          />
          <Where />
        </MemoryRouter>,
      );
    });
  };

  const menuItems = async () => {
    const trigger = container.querySelector<HTMLButtonElement>(
      '[data-testid="menu-button-src-1"]',
    )!;
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      trigger.click();
    });
    return Array.from(
      document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).map((el) => el.textContent);
  };

  const menuIcon = (label: string) =>
    Array.from(document.querySelectorAll<HTMLElement>('[role="menuitem"]'))
      .find((el) => el.textContent === label)
      ?.querySelector('svg')
      ?.getAttribute('class') ?? '';

  const clickItem = async (label: string) => {
    const item = Array.from(
      document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).find((el) => el.textContent === label)!;
    await act(async () => item.click());
  };

  const toasts = () =>
    dispatch.mock.calls
      .map(([action]) => action)
      .filter((action) => action?.type === 'actionToast/showActionToast');

  it('owner: Edit config, Test retrieval, Convert, Share and Delete', async () => {
    await render(
      doc({
        access: 'owner',
        allowed_actions: [...OWNER, 'use', 'view_config'],
      }),
    );
    expect(await menuItems()).toEqual([
      'settings.sources.view',
      'settings.sources.editConfig',
      'settings.sources.testRetrieval.action',
      'settings.sources.wiki.convert.action',
      'settings.sources.shareWithTeam',
      'convTile.delete',
    ]);
  });

  // The connection is managed on the Connectors page; a synced source's
  // menu keeps only what acts on the source itself.
  it('a synced source has no Manage connection item', async () => {
    connectors.connections = [
      {
        id: 'conn-1',
        connector_key: 'google_drive',
        name: 'Google Drive',
        icon: 'drive',
        status: 'connected',
        account_label: 'alex@example.com',
      },
    ];
    await render(
      doc({
        access: 'owner',
        allowed_actions: [...OWNER, 'use', 'view_config'],
        connectionId: 'conn-1',
      } as Partial<Doc>),
    );
    const items = await menuItems();
    connectors.connections = [];
    expect(items).not.toContain('settings.connectors.manageConnection');
    expect(items).toContain('settings.sources.editConfig');
    expect(items).toContain('convTile.delete');
  });

  // A source whose connection needs signing in again says so on its tile
  // and signs in again from there, without opening the source.
  it('reconnects a paused synced source from its tile', async () => {
    connectors.connections = [
      {
        id: 'conn-1',
        connector_key: 'google_drive',
        name: 'Google Drive',
        icon: 'drive',
        status: 'reconnect_needed',
        account_label: 'alex@example.com',
      },
    ];
    reconnect.mockClear();
    await render(doc({ connectionId: 'conn-1' } as Partial<Doc>));
    connectors.connections = [];
    // The state is the warning Badge, the action an outline sm pill.
    const badge = Array.from(
      container.querySelectorAll('[data-slot="badge"]'),
    ).find((b) => b.textContent === 'settings.connectors.status.reconnect')!;
    expect(badge.getAttribute('data-variant')).toBe('warning');
    expect(badge.hasAttribute('tabindex')).toBe(false);
    expect(container.textContent).not.toContain(
      'settings.connectors.detail.paused',
    );
    const button = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'settings.connectors.status.reconnect',
    )!;
    expect(button).toBeDefined();
    expect(button.getAttribute('data-variant')).toBe('outline');
    expect(button.getAttribute('data-size')).toBe('sm');
    expect(button.getAttribute('data-shape')).toBe('pill');
    // A sibling of the card's own button, never inside it.
    expect(button.closest('[role="button"]')).toBeNull();
    expect(button.parentElement!.closest('button')).toBeNull();
    await act(async () => button.click());
    expect(reconnect).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'conn-1', connector_key: 'google_drive' }),
    );
    // Only the reconnect: the source view stays closed.
    expect(container.querySelector('[data-testid="chunks"]')).toBeNull();
  });

  // The same rule as Tools and the nav dot: an expired or failing sign-in.
  it.each([
    ['error', true],
    ['disconnected', false],
  ])('status %s offers Reconnect: %s', async (status, shown) => {
    connectors.connections = [
      {
        id: 'conn-1',
        connector_key: 'google_drive',
        name: 'Google Drive',
        status,
      },
    ];
    await render(doc({ connectionId: 'conn-1' } as Partial<Doc>));
    connectors.connections = [];
    expect(
      Array.from(container.querySelectorAll('button')).some(
        (b) => b.textContent === 'settings.connectors.status.reconnect',
      ),
    ).toBe(shown);
  });

  // DESIGN "A clickable card that holds a link": the card opens through a
  // stretched button; the menu and Reconnect are its siblings.
  it('opens the source through a stretched button, controls beside it', async () => {
    connectors.connections = [
      {
        id: 'conn-1',
        connector_key: 'google_drive',
        name: 'Google Drive',
        icon: 'drive',
        status: 'reconnect_needed',
      },
    ];
    await render(doc({ connectionId: 'conn-1' } as Partial<Doc>));
    connectors.connections = [];
    expect(container.querySelector('[role="button"]')).toBeNull();
    const open = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Contracts"]',
    )!;
    expect(open).not.toBeNull();
    expect(open.className).toContain('after:inset-0');
    expect(open.querySelector('button, a, [tabindex]')).toBeNull();
    const menu = container.querySelector<HTMLElement>(
      '[data-testid="menu-button-src-1"]',
    )!;
    expect(open.contains(menu)).toBe(false);
    expect(menu.closest('.z-10')).not.toBeNull();
    const card = open.closest('[data-slot="card"]')!;
    expect(card.className).toContain('has-[>button:focus-visible]:ring-3');
    // Names the connection from the Knowledge namespace.
    expect(card.textContent).toContain('settings.sources.viaConnection');
    expect(card.textContent).not.toContain('settings.tools.viaConnection');
  });

  it('offers no Reconnect on a synced source that is running', async () => {
    connectors.connections = [
      {
        id: 'conn-1',
        connector_key: 'google_drive',
        name: 'Google Drive',
        status: 'connected',
      },
    ];
    await render(doc({ connectionId: 'conn-1' } as Partial<Doc>));
    connectors.connections = [];
    expect(
      Array.from(container.querySelectorAll('button')).some(
        (b) => b.textContent === 'settings.connectors.status.reconnect',
      ),
    ).toBe(false);
  });

  // Leaving Knowledge loses nothing, so its Add knowledge may browse the
  // whole Connectors page; the other openers keep the list in the dialog.
  it('lets Add knowledge browse the syncing connectors from Knowledge', async () => {
    await render(doc());
    uploadProps.mockClear();
    const add = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'settings.sources.addSource',
    )!;
    await act(async () => add.click());
    const props = uploadProps.mock.calls.at(-1)![0] as {
      onBrowseConnectors?: () => void;
    };
    await act(async () => props.onBrowseConnectors!());
    expect(container.querySelector('[data-testid="where"]')?.textContent).toBe(
      '/settings/connectors?capability=sync',
    );
  });

  it('a source with no access fields is the caller’s own', async () => {
    await render(doc());
    const items = await menuItems();
    expect(items).toContain('settings.sources.shareWithTeam');
    expect(items).toContain('convTile.delete');
  });

  it('editor: edits but cannot share or delete', async () => {
    await render(
      doc({
        access: 'editor',
        ownership: 'team',
        team_access: 'editor',
        allowed_actions: EDITOR,
      }),
    );
    expect(await menuItems()).toEqual([
      'settings.sources.view',
      'settings.sources.editConfig',
      'settings.sources.testRetrieval.action',
      'settings.sources.wiki.convert.action',
    ]);
    expect(menuIcon('settings.sources.editConfig')).not.toContain('lucide-eye');
  });

  it('editors_can_share / editors_can_delete widen the editor menu', async () => {
    await render(
      doc({
        access: 'editor',
        ownership: 'team',
        allowed_actions: [...EDITOR, 'share', 'delete'],
      }),
    );
    const items = await menuItems();
    expect(items).toContain('settings.sources.shareWithTeam');
    expect(items).toContain('convTile.delete');
  });

  it('viewer: View config and Test retrieval only', async () => {
    await render(
      doc({
        access: 'viewer',
        ownership: 'team',
        team_access: 'viewer',
        allowed_actions: VIEWER,
      }),
    );
    expect(await menuItems()).toEqual([
      'settings.sources.view',
      'settings.sources.viewConfig',
      'settings.sources.testRetrieval.action',
    ]);
    // View swaps the config item's icon for Eye, like every View label.
    expect(menuIcon('settings.sources.viewConfig')).toContain('lucide-eye');
  });

  it('viewer without view_config: no config item', async () => {
    await render(
      doc({ access: 'viewer', ownership: 'team', allowed_actions: ['use'] }),
    );
    expect(await menuItems()).toEqual([
      'settings.sources.view',
      'settings.sources.testRetrieval.action',
    ]);
  });

  it('a wiki owner gets Wiki settings; editors and viewers do not', async () => {
    const wiki = { type: 'wiki', config: { kind: 'wiki' } };
    await render(
      doc({ ...wiki, access: 'owner', allowed_actions: [...OWNER, 'use'] }),
    );
    expect(await menuItems()).toContain(
      'settings.sources.wiki.settings.action',
    );
    await clickItem('settings.sources.wiki.settings.action');
    expect(
      document.querySelector('[data-testid="wiki-settings"]')?.textContent,
    ).toBe('Contracts');

    for (const allowed of [EDITOR, VIEWER]) {
      await act(async () => root.unmount());
      root = createRoot(container);
      document.body
        .querySelectorAll('[role="menu"]')
        .forEach((m) => m.remove());
      await render(
        doc({ ...wiki, access: 'editor', allowed_actions: allowed }),
      );
      expect(await menuItems()).not.toContain(
        'settings.sources.wiki.settings.action',
      );
    }
  });

  it('a classic source has no Wiki settings', async () => {
    await render(doc({ access: 'owner', allowed_actions: [...OWNER, 'use'] }));
    expect(await menuItems()).not.toContain(
      'settings.sources.wiki.settings.action',
    );
  });

  it('sync and reingest are editor actions', async () => {
    const synced = { syncFrequency: 'daily', ingestStatus: 'failed' as const };
    await render(doc({ ...synced, access: 'editor', allowed_actions: EDITOR }));
    let items = await menuItems();
    expect(items).toContain('settings.sources.reingest');
    expect(items).toContain('settings.sources.syncNow');
    expect(items).toContain('settings.sources.syncFrequency.option');

    await act(async () => root.unmount());
    root = createRoot(container);
    document.body.querySelectorAll('[role="menu"]').forEach((m) => m.remove());
    await render(doc({ ...synced, access: 'viewer', allowed_actions: VIEWER }));
    items = await menuItems();
    expect(items).not.toContain('settings.sources.reingest');
    expect(items).not.toContain('settings.sources.syncNow');
    expect(items).not.toContain('settings.sources.syncFrequency.option');
  });

  it('a failed Sync now shows an error toast', async () => {
    service.syncSource.mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ success: false, message: 'Forbidden' }),
    });
    await render(doc({ syncFrequency: 'daily' }));
    await menuItems();
    await clickItem('settings.sources.syncNow');
    expect(toasts()).toEqual([
      expect.objectContaining({
        payload: expect.objectContaining({ variant: 'destructive' }),
      }),
    ]);
  });

  it('a failed sync-frequency change shows an error toast', async () => {
    service.manageSync.mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ success: false }),
    });
    await render(doc({ syncFrequency: 'daily' }));
    await menuItems();
    const weekly = Array.from(
      document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).filter(
      (el) => el.textContent === 'settings.sources.syncFrequency.option',
    )[2];
    await act(async () => weekly.click());
    expect(toasts()).toHaveLength(1);
  });

  it('a failed reingest shows an error toast', async () => {
    service.reingestSource.mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ success: false, message: 'Forbidden' }),
    });
    await render(doc({ ingestStatus: 'failed' }));
    await menuItems();
    await clickItem('settings.sources.reingest');
    expect(toasts()).toHaveLength(1);
  });

  const openView = async (document: Doc) => {
    await render(document);
    await act(async () =>
      container.querySelector<HTMLElement>('[aria-label="Contracts"]')!.click(),
    );
  };

  const canEditOf = (testId: string) =>
    container
      .querySelector(`[data-testid="${testId}"]`)
      ?.getAttribute('data-can-edit');

  it.each([
    ['chunks', {}],
    ['file-tree', { isNested: true }],
    ['connector-tree', { isNested: true, type: 'connector:file' }],
    ['wiki', { type: 'wiki' }],
    ['graph', { config: { kind: 'graphrag' } }],
  ] as const)(
    'the %s view is read-only for a viewer',
    async (testId, fields) => {
      await openView(
        doc({ ...fields, access: 'viewer', allowed_actions: VIEWER }),
      );
      expect(canEditOf(testId)).toBe('false');
    },
  );

  it('the source view is editable for an editor', async () => {
    await openView(
      doc({ isNested: true, access: 'editor', allowed_actions: EDITOR }),
    );
    expect(canEditOf('file-tree')).toBe('true');
  });
});

describe('Sources paging', () => {
  let container: HTMLDivElement;
  let root: Root;
  const fetchPage = vi.mocked(getDocsWithPagination);

  beforeEach(() => {
    localStorage.clear();
    fetchPage.mockReset();
    service.getConfig.mockResolvedValue({ json: async () => ({}) });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
  });

  function Where() {
    const location = useLocation();
    return <div data-testid="where">{location.search}</div>;
  }

  const render = async (entry = '/settings/sources') => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={[entry]}>
          <Sources
            paginatedDocuments={[doc()]}
            handleDeleteDocument={vi.fn()}
          />
          <Where />
        </MemoryRouter>,
      );
    });
  };

  const response = (currentPage: number, total = 86) => ({
    docs: [doc()],
    totalDocuments: total,
    totalPages: Math.ceil(total / 12),
    currentPage,
    nextCursor: '',
  });

  const where = () =>
    container.querySelector('[data-testid="where"]')!.textContent;

  const stubWidth = (desktop: boolean) =>
    vi.stubGlobal('matchMedia', () => ({ matches: desktop }));

  it('asks for 24 per page on desktop', async () => {
    stubWidth(true);
    fetchPage.mockResolvedValue(response(1));
    await render();
    expect(fetchPage.mock.calls[0][3]).toBe(24);
  });

  it('asks for 12 per page below desktop, starting on the page in the URL', async () => {
    stubWidth(false);
    fetchPage.mockResolvedValue(response(3));
    await render('/settings/sources?page=3');
    expect(fetchPage).toHaveBeenCalledTimes(1);
    const [, , page, rows] = fetchPage.mock.calls[0];
    expect(page).toBe(3);
    expect(rows).toBe(12);
    expect(where()).toBe('?page=3');
  });

  it('pages with the numbered pager and keeps the page in the URL', async () => {
    fetchPage.mockResolvedValue(response(1));
    await render();
    const pager = container.querySelector('[data-slot="pagination-full"]')!;
    expect(pager.textContent).toContain('settings.sources.pageRange');
    const page2 = pager.querySelector<HTMLButtonElement>(
      '[aria-label="pagination.goToPage"]:not([aria-current])',
    )!;
    fetchPage.mockResolvedValue(response(2));
    await act(async () => page2.click());
    expect(fetchPage.mock.lastCall![2]).toBe(2);
    expect(where()).toBe('?page=2');
  });

  // Deleting the last card on the last page: the server clamps the page.
  it('follows the page the server clamped to', async () => {
    fetchPage.mockResolvedValue(response(7, 84));
    await render('/settings/sources?page=8');
    expect(where()).toBe('?page=7');
  });

  it('uses the remembered page size', async () => {
    localStorage.setItem('DocsGPTPageSize:sources', '48');
    fetchPage.mockResolvedValue(response(1));
    await render();
    expect(fetchPage.mock.calls[0][3]).toBe(48);
  });

  it('a new search starts on page 1', async () => {
    fetchPage.mockResolvedValue(response(3));
    await render('/settings/sources?page=3');
    const input = container.querySelector<HTMLInputElement>(
      '#document-search-input',
    )!;
    fetchPage.mockResolvedValue(response(1, 5));
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!;
      setValue.call(input, 'tender');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    const [, , page, , search] = fetchPage.mock.lastCall!;
    expect(page).toBe(1);
    expect(search).toBe('tender');
    expect(where()).toBe('');
  });

  const renderEmpty = async () => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <Sources paginatedDocuments={[]} handleDeleteDocument={vi.fn()} />
        </MemoryRouter>,
      );
    });
  };

  // "Connect a service" would open the same Add knowledge modal.
  it('offers one way in when there is no knowledge yet', async () => {
    fetchPage.mockResolvedValue(response(1, 0));
    await renderEmpty();
    const empty = container.querySelector('[data-slot="empty-state"]')!;
    expect(empty.getAttribute('data-size')).toBe('default');
    expect(
      Array.from(empty.querySelectorAll('button')).map((b) => b.textContent),
    ).toEqual(['settings.sources.addSource']);
  });

  it('says no match in the small, unillustrated empty state', async () => {
    fetchPage.mockResolvedValue(response(1, 0));
    await renderEmpty();
    const input = container.querySelector<HTMLInputElement>(
      '#document-search-input',
    )!;
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!;
      setValue.call(input, 'nothing');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    const empty = container.querySelector('[data-slot="empty-state"]')!;
    expect(empty.textContent).toContain('settings.sources.noResults');
    expect(empty.getAttribute('data-size')).toBe('xs');
    expect(empty.querySelector('svg')).toBeNull();
  });
});
