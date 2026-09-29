import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

const { dispatch, service, view } = vi.hoisted(() => ({
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
      connectors: { connections: [], loaded: true },
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
vi.mock('../upload/Upload', () => ({ default: () => null }));

import type { Doc } from '../models/misc';
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

  const render = async (document: Doc) => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <Sources
            paginatedDocuments={[document]}
            handleDeleteDocument={vi.fn()}
          />
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
