import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';

const {
  dispatch,
  service,
  view,
  connectors,
  uploadProps,
  reconnect,
  knowledge,
  configModal,
  viewProps,
  changeModals,
} = vi.hoisted(() => ({
  // The callbacks Convert to wiki and Enable GraphRAG were given.
  changeModals: {
    onConverted: null as null | (() => void),
    onEnabled: null as null | (() => void),
  },
  // The last props Source settings was given (its onSaved patches the card).
  configModal: {
    props: null as null | {
      modalState: string;
      onSaved: (patch: Record<string, unknown>) => void;
      syncing?: boolean;
    },
  },
  // The last props each view was given.
  viewProps: {} as Record<string, Record<string, unknown>>,
  // The app-wide knowledge list (`preference.sourceDocs`); null is unloaded.
  knowledge: { docs: undefined as unknown },
  reconnect: vi.fn(),
  uploadProps: vi.fn(),
  connectors: {
    connections: [] as Record<string, unknown>[],
    // Syncs this session started (connectorsSlice.startedSyncs).
    startedSyncs: [] as Record<string, unknown>[],
    // The recent notification events (notifications.recentEvents).
    events: [] as Record<string, unknown>[],
  },
  // The heavy children: each view reports the canEdit and the citation
  // link it was given, and its Back leaves it.
  view:
    (testId: string) =>
    (props: {
      canEdit?: boolean;
      linkedChunk?: { id?: string; search: string };
      initialPath?: string;
      handleGoBack?: () => void;
      onBackToDocuments?: () => void;
      headerAction?: React.ReactNode;
      headerMenu?: React.ReactNode;
    }) => {
      const {
        canEdit,
        linkedChunk,
        initialPath,
        handleGoBack,
        onBackToDocuments,
        headerAction,
        headerMenu,
      } = props;
      viewProps[testId] = props;
      return (
        <div
          data-testid={testId}
          data-can-edit={String(canEdit)}
          data-linked={
            linkedChunk ? `${linkedChunk.id}|${linkedChunk.search}` : ''
          }
          data-initial-path={initialPath ?? ''}
        >
          <button type="button" onClick={handleGoBack ?? onBackToDocuments}>
            VIEW BACK
          </button>
          <div data-testid="view-actions">
            {headerAction}
            {headerMenu}
          </div>
        </div>
      );
    },
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
      preference: { token: null, sourceDocs: knowledge.docs },
      upload: { tasks: [] },
      graphBuild: { builds: {} },
      connectors: {
        connections: connectors.connections,
        loaded: true,
        startedSyncs: connectors.startedSyncs,
      },
      notifications: { recentEvents: connectors.events },
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
  // null is a failed load; a page resolves with the docs.
  getDocsWithPagination: vi.fn(async () => ({
    docs: [],
    totalDocuments: 1,
    totalPages: 1,
    currentPage: 1,
    nextCursor: '',
  })),
}));

vi.mock('../components/Chunks', () => ({ default: view('chunks') }));
vi.mock('../components/FileTree', () => ({ default: view('file-tree') }));
vi.mock('../components/ConnectorTree', () => ({
  default: view('connector-tree'),
}));
vi.mock('../components/WebsiteTree', () => ({
  default: view('website-tree'),
}));
vi.mock('../components/WikiViewer', () => ({ default: view('wiki') }));
vi.mock('../components/graph/GraphSourceView', () => ({
  default: view('graph'),
}));
vi.mock('./SourceConfigModal', () => ({
  default: (props: NonNullable<typeof configModal.props>) => {
    configModal.props = props;
    return null;
  },
}));
vi.mock('./TestRetrievalModal', () => ({ default: () => null }));
vi.mock('./ConvertToWikiModal', () => ({
  default: (props: { onConverted: () => void }) => {
    changeModals.onConverted = props.onConverted;
    return null;
  },
}));
vi.mock('./WikiSettingsModal', () => ({
  default: ({ document }: { document: { name: string } }) => (
    <div data-testid="wiki-settings">{document.name}</div>
  ),
}));
vi.mock('./EnableGraphRAGModal', () => ({
  default: (props: { onEnabled: () => void }) => {
    changeModals.onEnabled = props.onEnabled;
    return null;
  },
}));
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

import { syncForgotten } from '../connectors/connectorsSlice';
import type { Doc } from '../models/misc';
import { getDocs, getDocsWithPagination } from '../preferences/preferenceApi';
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

/** The URL: its path and its search, apart. */
function Where() {
  const location = useLocation();
  return (
    <>
      <div data-testid="path">{location.pathname}</div>
      <div data-testid="where">{location.search}</div>
    </>
  );
}

/** Renders the page at `entry` over the `listed` cards. */
const mount = (
  root: Root,
  listed: Doc[],
  {
    entry = '/settings/sources',
    onDelete = vi.fn(),
  }: {
    entry?: string;
    onDelete?: (index: number, doc: Doc) => void | Promise<unknown>;
  } = {},
) =>
  act(async () => {
    root.render(
      <MemoryRouter initialEntries={[entry]}>
        <Sources paginatedDocuments={listed} handleDeleteDocument={onDelete} />
        <Where />
      </MemoryRouter>,
    );
  });

/** Opens the menu behind a trigger; returns its item labels. */
const openMenu = async (testId: string) => {
  const trigger = document.querySelector<HTMLButtonElement>(
    `[data-testid="${testId}"]`,
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

/** Types into the page's search box. */
const typeSearch = async (value: string) => {
  const input = document.querySelector<HTMLInputElement>(
    '#document-search-input',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
};

/** The caller's one connection (`conn-1`), in `status`. */
const withConnection = (
  status: string,
  fields: Record<string, unknown> = {},
) => {
  connectors.connections = [
    {
      id: 'conn-1',
      connector_key: 'google_drive',
      name: 'Google Drive',
      icon: 'drive',
      status,
      account_label: 'alex@example.com',
      ...fields,
    },
  ];
};

describe('Sources access', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    dispatch.mockReset();
    Object.values(service).forEach((fn) => fn.mockReset());
    service.getConfig.mockResolvedValue({ json: async () => ({}) });
    connectors.connections = [];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document.body.innerHTML = '';
    connectors.connections = [];
  });

  const render = (document: Doc) => mount(root, [document]);

  const menuItems = () => openMenu('menu-button-src-1');

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

  // The real ConfirmationModal: pending on the delete's promise, and a
  // rejection keeps the dialog open with its message.
  it('keeps a failed delete in the confirm dialog with its message', async () => {
    const handleDeleteDocument = vi.fn(() =>
      Promise.reject(new Error('settings.sources.errors.forbidden')),
    );
    await mount(
      root,
      [doc({ access: 'owner', allowed_actions: [...OWNER, 'use'] })],
      { onDelete: handleDeleteDocument },
    );
    await menuItems();
    await clickItem('settings.sources.delete');
    // The confirm copy: the question as the title, the consequence below.
    expect(
      document.querySelector('[role="dialog"] [data-slot="dialog-description"]')
        ?.textContent,
    ).toBe('settings.sources.deleteConsequence');
    const submit = Array.from(
      document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button'),
    ).find((b) => b.textContent === 'settings.sources.delete')!;
    expect(submit.getAttribute('data-variant')).toBe('destructive');
    await act(async () => submit.click());
    expect(handleDeleteDocument).toHaveBeenCalled();
    const dialog = document.querySelector('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog!.textContent).toContain('settings.sources.errors.forbidden');
  });

  const VIEW = 'settings.sources.view';
  const TEST = 'settings.sources.testRetrieval.action';
  const CONVERT = 'settings.sources.wiki.convert.action';
  const SHARE = 'settings.sources.shareWithTeam';
  const DELETE = 'settings.sources.delete';
  const EDIT_CONFIG = 'settings.sources.editConfig';
  const VIEW_CONFIG = 'settings.sources.viewConfig';
  const FULL = [VIEW, EDIT_CONFIG, TEST, CONVERT, SHARE, DELETE];

  // `eye`: whether the config item carries the Eye icon, as every View
  // label does.
  it.each<[string, Partial<Doc>, string[], boolean | null]>([
    [
      'owner',
      { access: 'owner', allowed_actions: [...OWNER, 'use', 'view_config'] },
      FULL,
      false,
    ],
    [
      'editor: edits but cannot share or delete',
      {
        access: 'editor',
        ownership: 'team',
        team_access: 'editor',
        allowed_actions: EDITOR,
      },
      [VIEW, EDIT_CONFIG, TEST, CONVERT],
      false,
    ],
    [
      'editor with editors_can_share / editors_can_delete',
      {
        access: 'editor',
        ownership: 'team',
        allowed_actions: [...EDITOR, 'share', 'delete'],
      },
      FULL,
      false,
    ],
    [
      'viewer: View config and Test retrieval only',
      {
        access: 'viewer',
        ownership: 'team',
        team_access: 'viewer',
        allowed_actions: VIEWER,
      },
      [VIEW, VIEW_CONFIG, TEST],
      true,
    ],
    [
      'viewer without view_config: no config item',
      { access: 'viewer', ownership: 'team', allowed_actions: ['use'] },
      [VIEW, TEST],
      null,
    ],
    // No access fields: the caller's own.
    ['no access fields', {}, FULL, false],
  ])('the card menu of %s', async (_, fields, expected, eye) => {
    await render(doc(fields));
    expect(await menuItems()).toEqual(expected);
    if (eye !== null)
      expect(
        menuIcon(eye ? VIEW_CONFIG : EDIT_CONFIG).includes('lucide-eye'),
      ).toBe(eye);
  });

  // The connection is managed on the Connectors page; a synced source's
  // menu keeps only what acts on the source itself.
  it('a synced source has no Manage connection item', async () => {
    withConnection('connected');
    await render(
      doc({
        access: 'owner',
        allowed_actions: [...OWNER, 'use', 'view_config'],
        connectionId: 'conn-1',
      } as Partial<Doc>),
    );
    const items = await menuItems();
    expect(items).not.toContain('settings.connectors.manageConnection');
    expect(items).toContain('settings.sources.editConfig');
    expect(items).toContain('settings.sources.delete');
  });

  // A source whose connection needs signing in again says so on its tile
  // and signs in again from there, without opening the source.
  it('reconnects a paused synced source from its tile', async () => {
    withConnection('reconnect_needed');
    reconnect.mockClear();
    await render(doc({ connectionId: 'conn-1' } as Partial<Doc>));
    // The state is a warning Badge, not a control.
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
    ['connected', false],
  ])('status %s offers Reconnect: %s', async (status, shown) => {
    withConnection(status);
    await render(doc({ connectionId: 'conn-1' } as Partial<Doc>));
    expect(
      Array.from(container.querySelectorAll('button')).some(
        (b) => b.textContent === 'settings.connectors.status.reconnect',
      ),
    ).toBe(shown);
  });

  // DESIGN "A clickable card that holds a link": the card opens through a
  // stretched button; the menu and Reconnect are its siblings.
  it('opens the source through a stretched button, controls beside it', async () => {
    withConnection('reconnect_needed');
    await render(doc({ connectionId: 'conn-1' } as Partial<Doc>));
    expect(container.querySelector('[role="button"]')).toBeNull();
    const open = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Contracts"]',
    )!;
    expect(open).not.toBeNull();
    expect(open.querySelector('button, a, [tabindex]')).toBeNull();
    const menu = container.querySelector<HTMLElement>(
      '[data-testid="menu-button-src-1"]',
    )!;
    expect(open.contains(menu)).toBe(false);
    const card = open.closest('[data-slot="card"]')!;
    // Names the connection from the Knowledge namespace.
    expect(card.textContent).toContain('settings.sources.viaConnection');
    expect(card.textContent).not.toContain('settings.tools.viaConnection');
    // The ⋯ opens its menu and leaves the source closed; the card opens it.
    expect(await menuItems()).toContain('settings.sources.view');
    expect(container.querySelector('[data-testid="chunks"]')).toBeNull();
    await act(async () => open.click());
    expect(container.querySelector('[data-testid="chunks"]')).not.toBeNull();
  });

  it('counts the files of a synced source on its card', async () => {
    withConnection('connected');
    await render(doc({ connectionId: 'conn-1', files: 12 } as Partial<Doc>));
    const card = container.querySelector('[data-slot="card"]')!;
    expect(card.textContent).toContain('settings.sources.viaConnectionFiles');
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
    expect(container.querySelector('[data-testid="path"]')?.textContent).toBe(
      '/settings/connectors',
    );
    expect(container.querySelector('[data-testid="where"]')?.textContent).toBe(
      '?capability=sync',
    );
  });

  // A synced wiki: its Settings is Wiki settings, the owner's alone, and it
  // never syncs.
  it.each([
    ['owner', 'owner', [...OWNER, 'use'], true],
    ['editor', 'editor', EDITOR, false],
    ['viewer', 'viewer', VIEWER, false],
  ] as const)(
    "a wiki's Settings for its %s",
    async (_, access, allowed, settings) => {
      await render(
        doc({
          type: 'url',
          syncFrequency: 'weekly',
          config: { kind: 'wiki' },
          access,
          allowed_actions: [...allowed],
        }),
      );
      const items = await menuItems();
      expect(items).not.toContain('settings.sources.syncNow');
      // Labelled Settings, like every source's.
      expect(items.includes('settings.sources.editConfig')).toBe(settings);
      if (!settings) return;
      await clickItem('settings.sources.editConfig');
      expect(
        document.querySelector('[data-testid="wiki-settings"]')?.textContent,
      ).toBe('Contracts');
    },
  );

  it.each([
    ['editor', EDITOR, true],
    ['viewer', VIEWER, false],
  ] as const)(
    'sync and reingest are editor actions (%s)',
    async (access, allowed, shown) => {
      await render(
        doc({
          syncFrequency: 'daily',
          ingestStatus: 'failed',
          access,
          allowed_actions: [...allowed],
        }),
      );
      const items = await menuItems();
      expect(items.includes('settings.sources.reingest')).toBe(shown);
      expect(items.includes('settings.sources.syncNow')).toBe(shown);
      // The schedule lives in Settings, not as menu rows.
      expect(items).not.toContain('settings.sources.syncFrequency.option');
    },
  );

  // A 403 reads as "not allowed" whatever its body; another refusal says
  // why (the codes are syncRefusal's, see syncRefusal.test).
  it.each([
    [
      403,
      { success: false, message: 'Forbidden' },
      'settings.sources.errors.forbidden',
    ],
    [
      400,
      { success: false, code: 'wiki', error: 'English' },
      'settings.connectors.detail.syncRefusedWiki',
    ],
    [400, { success: false, message: 'Nothing to sync.' }, 'Nothing to sync.'],
  ])(
    'a Sync now refused with %i says why (%o)',
    async (status, body, message) => {
      service.syncSource.mockResolvedValue({
        ok: false,
        status,
        json: async () => body,
      });
      await render(doc({ syncFrequency: 'daily' }));
      await menuItems();
      await clickItem('settings.sources.syncNow');
      expect(toasts()).toEqual([
        expect.objectContaining({
          payload: { variant: 'destructive', message },
        }),
      ]);
    },
  );

  it('a successful Sync now says the sync started', async () => {
    service.syncConnector.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true }),
    });
    await render(doc({ type: 'connector:file', syncFrequency: 'weekly' }));
    await menuItems();
    await clickItem('settings.sources.syncNow');
    expect(service.syncConnector).toHaveBeenCalledWith('src-1', null);
    expect(toasts()).toEqual([
      expect.objectContaining({
        payload: {
          variant: 'success',
          message: 'settings.sources.syncStarted',
        },
      }),
    ]);
  });

  it('a synced card: Sync now, one Settings, no schedule rows, Delete set apart', async () => {
    await render(
      doc({
        type: 's3',
        connectionId: 'conn-1',
        syncFrequency: 'weekly',
        access: 'owner',
        allowed_actions: [...OWNER, 'use', 'view_config'],
      }),
    );
    expect(await menuItems()).toEqual([
      'settings.sources.view',
      'settings.sources.syncNow',
      'settings.sources.editConfig',
      'settings.sources.testRetrieval.action',
      'settings.sources.wiki.convert.action',
      'settings.sources.shareWithTeam',
      'settings.sources.delete',
    ]);
    const separator = document.querySelector(
      '[role="menu"] [role="separator"]',
    );
    expect(separator?.nextElementSibling?.textContent).toBe(
      'settings.sources.delete',
    );
  });

  it('a website card has one Settings item, not two', async () => {
    await render(
      doc({
        website: { hosts: ['docs.x.io'], pages: 9 },
        syncFrequency: 'weekly',
        access: 'owner',
        allowed_actions: [...OWNER, 'use', 'view_config'],
      }),
    );
    const items = await menuItems();
    expect(items).not.toContain('settings.sources.website.settingsTitle');
    expect(
      items.filter((item) => item === 'settings.sources.editConfig'),
    ).toHaveLength(1);
  });

  it('a schedule saved in Settings updates the card, not the whole grid', async () => {
    const listed = doc({ type: 's3', syncFrequency: 'never' });
    await render(listed);
    await menuItems();
    await clickItem('settings.sources.editConfig');
    expect(configModal.props!.modalState).toBe('ACTIVE');
    vi.mocked(getDocsWithPagination).mockClear();
    dispatch.mockClear();
    await act(async () =>
      configModal.props!.onSaved({ syncFrequency: 'weekly' }),
    );
    expect(getDocsWithPagination).not.toHaveBeenCalled();
    const patched = dispatch.mock.calls
      .map(([action]) => action)
      .find((action) => action?.type === 'preference/setPaginatedDocuments');
    expect(patched?.payload).toEqual([{ ...listed, syncFrequency: 'weekly' }]);
  });

  it('a scheduled card says how it stays current instead of its date', async () => {
    await render(
      doc({ type: 's3', syncFrequency: 'weekly', date: '2026-10-21' }),
    );
    expect(container.textContent).toContain('settings.sources.website.synced');
  });

  // The toast and the upload row's error: a 403 toasts as "not allowed";
  // a coded refusal is worded by syncRefusal (its codes: syncRefusal.test).
  it.each([
    [
      403,
      { success: false, message: 'Forbidden' },
      'settings.sources.errors.forbidden',
      'Forbidden',
    ],
    [
      409,
      { success: false, code: 'reconnect_needed', error: 'English' },
      'settings.connectors.detail.syncRefusedReconnect',
      'settings.connectors.detail.syncRefusedReconnect',
    ],
  ])(
    'a reingest refused with %i says why (%o)',
    async (status, body, toast, rowError) => {
      service.reingestSource.mockResolvedValue({
        ok: false,
        status,
        json: async () => body,
      });
      await render(doc({ ingestStatus: 'failed' }));
      await menuItems();
      await clickItem('settings.sources.reingest');
      expect(toasts().map((action) => action.payload.message)).toEqual([toast]);
      const failed = dispatch.mock.calls
        .map(([action]) => action)
        .find((action) => action?.payload?.updates?.status === 'failed');
      expect(failed?.payload.updates.errorMessage).toBe(rowError);
    },
  );

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

  const viewMenu = () => openMenu('source-view-menu');

  it('the opened source has the card menu, less View and Test retrieval, last', async () => {
    await openView(
      doc({
        isNested: true,
        access: 'owner',
        allowed_actions: [...OWNER, 'use', 'view_config'],
      }),
    );
    const actions = container.querySelector('[data-testid="view-actions"]')!;
    expect(actions.firstElementChild?.textContent).toBe(
      'settings.sources.testRetrieval.action',
    );
    expect(actions.lastElementChild?.getAttribute('data-testid')).toBe(
      'source-view-menu',
    );
    expect(await viewMenu()).toEqual([
      'settings.sources.editConfig',
      'settings.sources.wiki.convert.action',
      'settings.sources.shareWithTeam',
      'settings.sources.deleteSource',
    ]);
  });

  const WEBSITE_OWNER: Partial<Doc> = {
    isNested: true,
    website: { hosts: ['docs.x.io'], pages: 9 },
    syncFrequency: 'weekly',
    date: '2026-10-20T10:00:00Z',
    access: 'owner',
    allowed_actions: [...OWNER, 'use', 'view_config'],
  };
  // The views that wait for a website's sync: its page list, and the graph
  // view around it.
  const WEBSITE_VIEWS = [
    ['website-tree', WEBSITE_OWNER],
    [
      'graph',
      { ...WEBSITE_OWNER, config: { kind: 'graphrag' } as Doc['config'] },
    ],
  ] as const;

  const syncNowItem = () =>
    Array.from(
      document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).find((el) => el.textContent === 'settings.sources.syncNow')!;

  // Its menu keeps Sync now (Add pages is the primary).
  it.each(WEBSITE_VIEWS)(
    "the %s view's Sync now hands the view the sync, and is off until its wait ends",
    async (testId, fields) => {
      service.syncSource.mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ success: true, task_id: 'task-s' }),
      });
      await openView(doc(fields));
      expect(viewProps[testId].sync).toBeFalsy();
      const before = Date.now();
      await viewMenu();
      await clickItem('settings.sources.syncNow');
      expect(service.syncSource).toHaveBeenCalledWith(
        { source_id: 'src-1' },
        null,
      );
      const sync = viewProps[testId].sync as {
        startedAt: number;
        taskId: string | null;
      };
      expect(sync.taskId).toBe('task-s');
      expect(sync.startedAt).toBeGreaterThanOrEqual(before);
      expect(sync.startedAt).toBeLessThanOrEqual(Date.now());
      // The toast still says it started.
      expect(toasts()).toEqual([
        expect.objectContaining({
          payload: expect.objectContaining({ variant: 'success' }),
        }),
      ]);

      // Settings, from the same view, says the same in its footer.
      await viewMenu();
      await clickItem('settings.sources.editConfig');
      expect(configModal.props!.syncing).toBe(true);
      await viewMenu();
      expect(syncNowItem().hasAttribute('data-disabled')).toBe(true);

      const onSyncSettled = viewProps[testId].onSyncSettled as (
        settled: unknown,
      ) => void;
      await act(async () => onSyncSettled(sync));
      expect(viewProps[testId].sync).toBeFalsy();
      expect(configModal.props!.syncing).toBe(false);
      // The menu is still open, and its Sync now is back.
      expect(syncNowItem().hasAttribute('data-disabled')).toBe(false);
    },
  );

  it.each(WEBSITE_VIEWS)(
    "the %s view's Sync now is off while the view reports a change in flight",
    async (testId, fields) => {
      await openView(doc(fields));
      const onBusyChange = viewProps[testId].onBusyChange as (
        busy: boolean,
      ) => void;
      expect(onBusyChange).toBeInstanceOf(Function);
      await act(async () => onBusyChange(true));
      await viewMenu();
      expect(syncNowItem().hasAttribute('data-disabled')).toBe(true);
      await clickItem('settings.sources.editConfig');
      expect(configModal.props!.syncing).toBe(true);

      await act(async () => onBusyChange(false));
      expect(configModal.props!.syncing).toBe(false);
      await viewMenu();
      expect(syncNowItem().hasAttribute('data-disabled')).toBe(false);
    },
  );

  it('a refused Sync now hands the tree nothing to wait on', async () => {
    service.syncSource.mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ success: false, message: 'Nothing to sync.' }),
    });
    await openView(doc(WEBSITE_OWNER));
    await viewMenu();
    await clickItem('settings.sources.syncNow');
    expect(viewProps['website-tree'].sync).toBeFalsy();
  });

  it('a finished page change reads the open website source again', async () => {
    await openView(doc(WEBSITE_OWNER));
    const fetchPage = vi.mocked(getDocsWithPagination);
    fetchPage.mockClear();
    vi.mocked(getDocs).mockResolvedValueOnce([
      doc({
        ...WEBSITE_OWNER,
        website: { hosts: ['docs.x.io', 'blog.x.io'], pages: 12 },
        date: '2026-10-23T09:00:00Z',
      }),
    ]);
    const onPagesChanged = viewProps['website-tree'].onPagesChanged as
      (() => void) | undefined;
    expect(onPagesChanged).toBeInstanceOf(Function);
    await act(async () => onPagesChanged!());
    // The card's page count and the byline's hosts and date follow.
    expect(fetchPage).toHaveBeenCalled();
    expect(viewProps['website-tree'].hosts).toEqual(['docs.x.io', 'blog.x.io']);
    expect(viewProps['website-tree'].syncedAt).toBe('2026-10-23T09:00:00Z');
  });

  it("Source settings saved on an open website view make its tree read the source's list again", async () => {
    await openView(doc(WEBSITE_OWNER));
    const before = viewProps['website-tree'].settingsVersion as number;
    await viewMenu();
    await clickItem('settings.sources.editConfig');
    await act(async () =>
      configModal.props!.onSaved({ syncFrequency: 'weekly' }),
    );
    expect(viewProps['website-tree'].settingsVersion).toBe(before + 1);
  });

  it.each(['onConverted', 'onEnabled'] as const)(
    'an open source follows its own change (%s) from the knowledge list',
    async (callback) => {
      await openView(doc({ isNested: true, access: 'owner' }));
      // A source opened from a citation may be off this page: the
      // knowledge list carries its new state.
      vi.mocked(getDocs).mockResolvedValueOnce([
        doc({
          isNested: true,
          access: 'owner',
          config: { kind: 'graphrag' } as Doc['config'],
        }),
      ]);
      await act(async () => changeModals[callback]!());
      expect(getDocs).toHaveBeenCalled();
      expect(container.querySelector('[data-testid="graph"]')).not.toBeNull();
    },
  );

  it('a graph source whose connection was removed tells the view it cannot sync', async () => {
    await openView(
      doc({
        isNested: true,
        type: 'connector:file',
        connectionId: null,
        config: { kind: 'graphrag' } as Doc['config'],
        access: 'owner',
        allowed_actions: [...OWNER, 'use', 'view_config'],
      }),
    );
    expect(viewProps.graph.canSync).toBe(false);
  });

  it('a GraphRAG website source hands its pages to the graph view', async () => {
    const website = { hosts: ['docs.x.io'], pages: 9 };
    await openView(
      doc({
        isNested: true,
        config: { kind: 'graphrag' } as Doc['config'],
        website,
        syncFrequency: 'weekly',
        date: '2026-10-20T10:00:00Z',
        access: 'owner',
        allowed_actions: [...OWNER, 'use', 'view_config'],
      }),
    );
    expect(viewProps.graph).toEqual(
      expect.objectContaining({
        website,
        syncFrequency: 'weekly',
        syncedAt: '2026-10-20T10:00:00Z',
      }),
    );
  });

  it.each([
    ['an S3 source', { type: 's3', connectionId: 'conn-1' }],
    ['a scheduled GitHub source', { type: 'github', syncFrequency: 'weekly' }],
  ] as const)(
    '%s opens with the synced header, Sync now not repeated in its menu',
    async (_, fields) => {
      withConnection('connected', { name: 'Amazon S3', icon: 's3' });
      await openView(
        doc({
          ...fields,
          isNested: true,
          access: 'owner',
          allowed_actions: [...OWNER, 'use', 'view_config'],
        }),
      );
      expect(
        container.querySelector('[data-testid="connector-tree"]'),
      ).not.toBeNull();
      expect(container.querySelector('[data-testid="file-tree"]')).toBeNull();
      expect(viewProps['connector-tree'].sourceType).toBe(fields.type);
      if ('connectionId' in fields)
        expect(viewProps['connector-tree'].connection).toEqual(
          expect.objectContaining({ name: 'Amazon S3' }),
        );
      expect(await viewMenu()).not.toContain('settings.sources.syncNow');
    },
  );

  it('a flat synced source gets Sync now beside Test retrieval', async () => {
    await openView(
      doc({
        type: 'github',
        syncFrequency: 'weekly',
        access: 'owner',
        allowed_actions: [...OWNER, 'use', 'view_config'],
      }),
    );
    const labels = Array.from(
      container.querySelectorAll('[data-testid="view-actions"] > button'),
    ).map((b) => b.textContent);
    expect(labels).toEqual([
      'settings.sources.testRetrieval.action',
      'settings.sources.syncNow',
      '',
    ]);
  });

  it('Delete from the opened source returns to the list', async () => {
    const handleDeleteDocument = vi.fn(async () => undefined);
    const listed = doc({
      isNested: true,
      access: 'owner',
      allowed_actions: [...OWNER, 'use'],
    });
    await mount(root, [listed], { onDelete: handleDeleteDocument });
    await act(async () =>
      container.querySelector<HTMLElement>('[aria-label="Contracts"]')!.click(),
    );
    await viewMenu();
    await clickItem('settings.sources.deleteSource');
    const submit = Array.from(
      document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button'),
    ).find((b) => b.textContent === 'settings.sources.delete')!;
    await act(async () => submit.click());
    expect(handleDeleteDocument).toHaveBeenCalledWith(0, listed);
    expect(container.querySelector('[data-testid="file-tree"]')).toBeNull();
    expect(container.querySelector('[aria-label="Contracts"]')).not.toBeNull();
  });

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

  const render = (entry = '/settings/sources') =>
    mount(root, [doc()], { entry });

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

  it('shows a failed load as an error with Retry, not "no sources"', async () => {
    fetchPage.mockResolvedValue(null);
    await render();
    const state = container.querySelector<HTMLElement>(
      '[data-slot="empty-state"][data-tone="destructive"]',
    )!;
    expect(state).not.toBeNull();
    expect(state.textContent).toContain('settings.sources.loadError');
    expect(
      container.querySelector('[data-testid="menu-button-src-1"]'),
    ).toBeNull();
    fetchPage.mockResolvedValue(response(1));
    const retry = Array.from(state.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    )!;
    await act(async () => retry.click());
    expect(fetchPage).toHaveBeenCalledTimes(2);
    expect(
      container.querySelector(
        '[data-slot="empty-state"][data-tone="destructive"]',
      ),
    ).toBeNull();
  });

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

  // The last card on the last page: the page is fetched again after the
  // delete, so the server's clamp moves the grid back a page (not an empty
  // "no sources yet" while other sources exist).
  it('refetches after a delete and follows the clamped page', async () => {
    fetchPage.mockResolvedValue(response(8, 85));
    const handleDeleteDocument = vi.fn(async () => undefined);
    await mount(
      root,
      [doc({ access: 'owner', allowed_actions: [...OWNER, 'use'] })],
      { entry: '/settings/sources?page=8', onDelete: handleDeleteDocument },
    );
    await openMenu('menu-button-src-1');
    const item = Array.from(
      document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).find((el) => el.textContent === 'settings.sources.delete')!;
    await act(async () => item.click());
    fetchPage.mockClear();
    fetchPage.mockResolvedValue(response(7, 84));
    const submit = Array.from(
      document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button'),
    ).find((b) => b.textContent === 'settings.sources.delete')!;
    await act(async () => submit.click());
    expect(handleDeleteDocument).toHaveBeenCalled();
    expect(fetchPage).toHaveBeenCalled();
    expect(fetchPage.mock.calls[0][2]).toBe(8);
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
    fetchPage.mockResolvedValue(response(1, 5));
    await typeSearch('tender');
    const [, , page, , search] = fetchPage.mock.lastCall!;
    expect(page).toBe(1);
    expect(search).toBe('tender');
    expect(where()).toBe('');
  });

  // "Connect a service" would open the same Add knowledge modal.
  it('offers one way in when there is no knowledge yet', async () => {
    fetchPage.mockResolvedValue(response(1, 0));
    await mount(root, []);
    const empty = container.querySelector('[data-slot="empty-state"]')!;
    expect(empty.textContent).toContain('settings.sources.noData');
    expect(
      Array.from(empty.querySelectorAll('button')).map((b) => b.textContent),
    ).toEqual(['settings.sources.addSource']);
  });

  it('says no match in an unillustrated empty state, with no way in', async () => {
    fetchPage.mockResolvedValue(response(1, 0));
    await mount(root, []);
    await typeSearch('nothing');
    const empty = container.querySelector('[data-slot="empty-state"]')!;
    expect(empty.textContent).toContain('settings.sources.noResults');
    expect(empty.querySelector('svg')).toBeNull();
    expect(empty.querySelector('button')).toBeNull();
  });
});

describe('Sources citation link', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    service.getConfig.mockResolvedValue({ json: async () => ({}) });
    vi.mocked(getDocsWithPagination).mockResolvedValue({
      docs: [],
      totalDocuments: 1,
      totalPages: 1,
      currentPage: 1,
      nextCursor: '',
    } as never);
    knowledge.docs = [];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document.body.innerHTML = '';
    knowledge.docs = undefined;
  });

  const render = (entry: string, listed: Doc[] = []) =>
    mount(root, listed, { entry });

  const viewOf = (testId: string) =>
    container.querySelector<HTMLElement>(`[data-testid="${testId}"]`);
  const where = () =>
    container.querySelector('[data-testid="where"]')?.textContent;

  it('opens the linked chunk of a source on the page, then drops the link from the URL', async () => {
    // A list on page 2 of 3, so the page stays in the URL.
    vi.mocked(getDocsWithPagination).mockResolvedValue({
      docs: [],
      totalDocuments: 30,
      totalPages: 3,
      currentPage: 2,
      nextCursor: '',
    } as never);
    await render(
      '/settings/knowledge?page=2&source=src-1&chunk=c7&q=Late%20pickup',
      [doc({ access: 'viewer', allowed_actions: VIEWER })],
    );
    const chunks = viewOf('chunks');
    expect(chunks?.dataset.linked).toBe('c7|Late pickup');
    // The source's own access, not a guess from the link.
    expect(chunks?.dataset.canEdit).toBe('false');
    expect(where()).toBe('?page=2');
  });

  it('finds a source off this page in the knowledge list, folders included', async () => {
    knowledge.docs = [
      { ...doc({ id: 'src-9', name: 'Handbook' }), is_nested: true },
    ];
    await render(
      '/settings/knowledge?source=src-9&chunk=c1&q=Leave&path=hr%2Fleave.md',
    );
    const tree = viewOf('file-tree');
    expect(tree?.dataset.initialPath).toBe('hr/leave.md');
    expect(tree?.dataset.linked).toBe('c1|Leave');
  });

  // The knowledge list (/api/sources) carries `website` and `files` too.
  it('opens a website source found only in the knowledge list in its page view', async () => {
    knowledge.docs = [
      {
        ...doc({ id: 'src-9', name: 'Docs site', type: 'website' }),
        is_nested: true,
        website: { hosts: ['docs.x.io'], pages: 12 },
        files: 12,
      },
    ];
    await render(
      '/settings/knowledge?source=src-9&chunk=c1&q=Docker&path=Deploying%2FDocker.md',
    );
    const tree = viewOf('website-tree');
    expect(tree).not.toBeNull();
    expect(tree?.dataset.initialPath).toBe('Deploying/Docker.md');
    expect(tree?.dataset.linked).toBe('c1|Docker');
    expect(viewOf('file-tree')).toBeNull();
  });

  it('opens a wiki at the cited page', async () => {
    await render('/settings/knowledge?source=src-1&wikiPage=guide%2Fleave.md', [
      doc({ type: 'wiki' }),
    ]);
    expect(viewOf('wiki')?.dataset.initialPath).toBe('guide/leave.md');
  });

  it('opens a graph source on the cited chunk', async () => {
    await render('/settings/knowledge?source=src-1&chunk=c3&q=Nordhaven', [
      doc({ config: { kind: 'graphrag' } as Doc['config'] }),
    ]);
    expect(viewOf('graph')?.dataset.linked).toBe('c3|Nordhaven');
  });

  it('waits for the knowledge list before giving up on a source', async () => {
    knowledge.docs = null;
    await render('/settings/knowledge?source=src-9&chunk=c1&q=x');
    expect(where()).toBe('?source=src-9&chunk=c1&q=x');
    expect(viewOf('chunks')).toBeNull();
  });

  it('shows the list for a source the caller cannot see', async () => {
    await render('/settings/knowledge?source=gone&chunk=c1&q=x');
    expect(viewOf('chunks')).toBeNull();
    expect(where()).toBe('');
  });

  describe('a source whose first sync is still running', () => {
    const started = {
      id: 'src-new',
      name: 'Handbook',
      connectionId: 'conn-drive',
      // Just started, so the page still waits for its event.
      startedAt: new Date().toISOString(),
    };
    const ingest = (type: string) => ({
      id: `evt-${type}`,
      type,
      scope: { kind: 'source', id: 'src-new' },
    });

    beforeEach(() => {
      dispatch.mockReset();
      vi.mocked(getDocs).mockReset();
      vi.mocked(getDocs).mockResolvedValue([]);
      connectors.startedSyncs = [started];
      connectors.events = [];
    });

    afterEach(() => {
      connectors.startedSyncs = [];
      connectors.events = [];
    });

    it('keeps the link while it indexes, then opens the source once listed', async () => {
      // The store applies the list read back, as the real slice does.
      dispatch.mockImplementation(
        (action: { type?: string; payload?: unknown }) => {
          if (action?.type === 'preference/setSourceDocs')
            knowledge.docs = action.payload;
        },
      );
      await render('/settings/knowledge?source=src-new');
      // Not listed yet: the list shows and the link waits.
      expect(viewOf('file-tree')).toBeNull();
      expect(where()).toBe('?source=src-new');

      // The first ingest finishes: the knowledge list is read again, and
      // the source opens from it; the link is spent.
      const fresh = {
        ...doc({ id: 'src-new', name: 'Handbook' }),
        is_nested: true,
      };
      vi.mocked(getDocs).mockResolvedValue([fresh] as never);
      connectors.events = [ingest('source.ingest.completed')];
      await render('/settings/knowledge?source=src-new');
      expect(getDocs).toHaveBeenCalledTimes(1);
      expect(viewOf('file-tree')).not.toBeNull();
      expect(where()).toBe('');
    });

    it('drops the link when the first sync fails', async () => {
      await render('/settings/knowledge?source=src-new');
      expect(where()).toBe('?source=src-new');
      connectors.events = [ingest('source.ingest.failed')];
      await render('/settings/knowledge?source=src-new');
      expect(where()).toBe('');
      expect(viewOf('file-tree')).toBeNull();
    });

    it('drops the link when the finished source still is not listed', async () => {
      connectors.events = [ingest('source.ingest.completed')];
      await render('/settings/knowledge?source=src-new');
      // Read again once; still missing, so the plain list stays.
      expect(getDocs).toHaveBeenCalledTimes(1);
      expect(where()).toBe('');
    });
  });

  describe('a sync still indexing shows on the list', () => {
    const START = '2026-10-23T10:00:00.000Z';
    const started = {
      id: 'src-new',
      name: 'Handbook',
      connectionId: 'conn-drive',
      startedAt: START,
    };
    const fresh = {
      ...doc({ id: 'src-new', name: 'Handbook' }),
      is_nested: true,
    };
    const ingest = (type: string) => ({
      id: `evt-${type}`,
      type,
      scope: { kind: 'source', id: 'src-new' },
    });
    const cards = () =>
      Array.from(container.querySelectorAll<HTMLElement>('[data-slot="card"]'));
    const pendingCard = () =>
      cards().find((card) => card.textContent?.includes('Handbook'));
    // Lets the poll's promises settle inside act.
    const advance = async (ms: number) => {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(ms);
      });
      await act(async () => undefined);
    };
    beforeEach(() => {
      vi.useFakeTimers({
        toFake: ['setTimeout', 'clearTimeout', 'Date'],
      });
      vi.setSystemTime(new Date(START));
      dispatch.mockReset();
      // The store applies the list read back, as the real slice does.
      dispatch.mockImplementation(
        (action: { type?: string; payload?: unknown }) => {
          if (action?.type === 'preference/setSourceDocs')
            knowledge.docs = action.payload;
        },
      );
      vi.mocked(getDocs).mockReset();
      vi.mocked(getDocs).mockResolvedValue([]);
      withConnection('connected', { id: 'conn-drive' });
      connectors.startedSyncs = [started];
      connectors.events = [];
    });

    afterEach(() => {
      connectors.connections = [];
      connectors.startedSyncs = [];
      connectors.events = [];
      vi.useRealTimers();
    });

    it('is the first card: Indexing…, its connection and start, no menu', async () => {
      await render('/settings/knowledge', [doc()]);
      const first = cards()[0];
      expect(first.textContent).toContain('Handbook');
      expect(first.textContent).toContain('settings.sources.ingestProcessing');
      expect(first.textContent).toContain('settings.sources.viaConnection');
      expect(first.textContent).toContain(
        'settings.connectors.detail.firstSyncStarted',
      );
      // Nothing to open or manage until the source exists.
      expect(first.querySelector('button')).toBeNull();
      expect(first.querySelector('[data-testid^="menu-button"]')).toBeNull();
      expect(cards()[1].textContent).toContain('Contracts');
    });

    it('shows on an empty list instead of the empty state', async () => {
      await render('/settings/knowledge');
      expect(pendingCard()).toBeDefined();
      expect(container.querySelector('[data-slot="empty-state"]')).toBeNull();
    });

    it('shows only on the first page', async () => {
      vi.mocked(getDocsWithPagination).mockResolvedValue({
        docs: [],
        totalDocuments: 30,
        totalPages: 3,
        currentPage: 2,
        nextCursor: '',
      } as never);
      await render('/settings/knowledge?page=2', [doc()]);
      expect(pendingCard()).toBeUndefined();
    });

    it('shows while its name matches the search', async () => {
      await render('/settings/knowledge', [doc()]);
      await typeSearch('HAND');
      expect(pendingCard()).toBeDefined();
      await typeSearch('tender');
      expect(pendingCard()).toBeUndefined();
    });

    it('shows every sync in flight, not only the linked one', async () => {
      connectors.startedSyncs = [
        started,
        { ...started, id: 'src-two', name: 'Price lists' },
      ];
      await render('/settings/knowledge');
      const names = cards().map((card) => card.textContent);
      // Newest first.
      expect(names[0]).toContain('Price lists');
      expect(names[1]).toContain('Handbook');
    });

    it('goes once the real source is listed', async () => {
      await render('/settings/knowledge', [fresh]);
      expect(cards()).toHaveLength(1);
      expect(cards()[0].textContent).not.toContain(
        'settings.sources.ingestProcessing',
      );
    });

    it('reads the lists again when its first sync finishes', async () => {
      connectors.events = [ingest('source.ingest.completed')];
      vi.mocked(getDocs).mockResolvedValue([fresh] as never);
      const pages = vi.mocked(getDocsWithPagination).mock.calls.length;
      await render('/settings/knowledge');
      expect(getDocs).toHaveBeenCalledTimes(1);
      // The mount's load, then the reload for the finished source.
      expect(vi.mocked(getDocsWithPagination).mock.calls.length).toBe(
        pages + 2,
      );
      expect(pendingCard()).toBeUndefined();
    });

    it('says the sync failed, and stops waiting for it', async () => {
      await render('/settings/knowledge?source=src-new');
      expect(vi.getTimerCount()).toBeGreaterThan(0);
      connectors.events = [ingest('source.ingest.failed')];
      await render('/settings/knowledge?source=src-new');
      const card = pendingCard()!;
      expect(card.textContent).toContain('settings.sources.ingestFailed');
      expect(card.textContent).not.toContain(
        'settings.sources.ingestProcessing',
      );
      expect(where()).toBe('');
      // Nothing left to poll for.
      expect(vi.getTimerCount()).toBe(0);
      // Its card can only be dismissed, which forgets the sync.
      const dismiss = card.querySelector<HTMLButtonElement>(
        'button[aria-label="settings.connectors.detail.dismissFailedSync"]',
      )!;
      await act(async () => dismiss.click());
      expect(dispatch).toHaveBeenCalledWith(syncForgotten(['src-new']));
    });

    it('checks the list every 30 s after 2 minutes, and opens the source once it appears', async () => {
      await render('/settings/knowledge?source=src-new');
      await advance(119_000);
      expect(getDocs).not.toHaveBeenCalled();
      await advance(1_000);
      expect(getDocs).toHaveBeenCalledTimes(1);
      await advance(30_000);
      expect(getDocs).toHaveBeenCalledTimes(2);
      expect(viewOf('file-tree')).toBeNull();
      expect(where()).toBe('?source=src-new');

      vi.mocked(getDocs).mockResolvedValue([fresh] as never);
      await advance(30_000);
      expect(getDocs).toHaveBeenCalledTimes(3);
      // The store hands the page the list read back.
      expect(knowledge.docs).toEqual([fresh]);
      await render('/settings/knowledge?source=src-new');
      expect(viewOf('file-tree')).not.toBeNull();
      expect(where()).toBe('');
    });

    it('gives up after 15 minutes: the link is dropped and never opens later', async () => {
      await render('/settings/knowledge?source=src-new');
      await advance(15 * 60_000);
      expect(where()).toBe('');
      const polls = vi.mocked(getDocs).mock.calls.length;
      expect(polls).toBeGreaterThan(0);
      await advance(10 * 60_000);
      expect(getDocs).toHaveBeenCalledTimes(polls);
      expect(vi.getTimerCount()).toBe(0);
      // Still indexing as far as the page knows.
      expect(pendingCard()?.textContent).toContain(
        'settings.sources.ingestProcessing',
      );

      // The list reloads for another reason and now holds the source: it
      // appears, but nothing opens.
      knowledge.docs = [fresh];
      await render('/settings/knowledge', [fresh]);
      expect(viewOf('file-tree')).toBeNull();
      expect(cards()).toHaveLength(1);
    });

    it('drops the link when another source is opened meanwhile', async () => {
      await render('/settings/knowledge?source=src-new', [doc()]);
      const open = container.querySelector<HTMLButtonElement>(
        'button[aria-label="Contracts"]',
      )!;
      await act(async () => open.click());
      expect(viewOf('chunks')).not.toBeNull();
      expect(where()).toBe('');
    });

    it('leaves no timers behind', async () => {
      await render('/settings/knowledge?source=src-new');
      expect(vi.getTimerCount()).toBeGreaterThan(0);
      await act(async () => root.unmount());
      expect(vi.getTimerCount()).toBe(0);
      root = createRoot(container);
    });
  });

  it('Back drops the link: the source opened again lists from the start', async () => {
    await render('/settings/knowledge?source=src-1&chunk=c7&q=Late', [doc()]);
    const back = viewOf('chunks')!.querySelector('button')!;
    await act(async () => back.click());
    const open = container.querySelector<HTMLButtonElement>(
      'button[aria-label="settings.sources.viewSource"], [data-slot="card"] > button',
    );
    expect(open).not.toBeNull();
    await act(async () => open!.click());
    expect(viewOf('chunks')?.dataset.linked).toBe('');
  });
});
