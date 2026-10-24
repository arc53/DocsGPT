import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { tree, dispatch, sync, waitForChange } = vi.hoisted(() => ({
  dispatch: vi.fn(),
  waitForChange: vi.fn(
    async (): Promise<{ terminal: string; reason: string | null }> => ({
      terminal: 'completed',
      reason: null,
    }),
  ),
  sync: { connector: vi.fn(), source: vi.fn() },
  tree: {
    structure: {
      'a.docx': { type: 'docx' },
      'b.docx': { type: 'docx' },
    } as Record<string, unknown>,
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => null,
  useDispatch: () => dispatch,
  useStore: () => ({ getState: () => ({}), subscribe: () => () => {} }),
}));

vi.mock('../hooks', () => ({
  useDarkTheme: () => [false],
  useDebouncedValue: (value: unknown) => value,
  useLoaderState: (initial: boolean) => useState(initial),
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
  useOutsideAlerter: () => undefined,
}));

vi.mock('../api/services/userService', () => ({
  default: {
    getDirectoryStructure: vi.fn(async () => ({
      json: async () => ({
        provider: 'google_drive',
        directory_structure: tree.structure,
      }),
    })),
    syncConnector: sync.connector,
    syncSource: sync.source,
    getDocumentChunks: vi.fn(async () => ({
      ok: true,
      json: async () => ({ page: 1, per_page: 12, total: 0, chunks: [] }),
    })),
  },
}));

// The sync's progress waits on the event stream; it finishes at once here.
vi.mock('./tree/useReingestWait', () => ({
  useReingestSseWaiter: () => ({
    waitForChange,
    mountedRef: { current: true },
  }),
}));

import ConnectorTree, { providerLabel } from './ConnectorTree';
import FileTree from './FileTree';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('providerLabel', () => {
  it('names known providers and title-cases the rest', () => {
    expect(providerLabel('google_drive')).toBe('Google Drive');
    expect(providerLabel('share_point')).toBe('SharePoint');
    expect(providerLabel('box_sync')).toBe('Box Sync');
  });
});

describe('ConnectorTree and FileTree headers', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (node: React.ReactNode) => {
    await act(async () => root.render(node));
  };
  const renderConnector = (
    props: Partial<React.ComponentProps<typeof ConnectorTree>> = {},
  ) =>
    render(
      <ConnectorTree
        docId="doc"
        sourceName="Drive"
        onBackToDocuments={vi.fn()}
        {...props}
      />,
    );

  const badge = () => container.querySelector('[data-slot="badge"]');
  // The title row's controls, in order.
  const titleRow = () =>
    Array.from(
      Array.from(container.querySelectorAll('button'))
        .find((b) => b.textContent === 'source menu')!
        .parentElement!.querySelectorAll('button'),
    ).map((b) => b.textContent);
  const retrieval = <button type="button">retrieval</button>;

  it('ConnectorTree shows the provider badge, headerAction and Sync', async () => {
    await renderConnector({ headerAction: retrieval });
    expect(badge()!.textContent).toBe('Google Drive');
    expect(badge()!.getAttribute('data-variant')).toBe('neutral');
    expect(container.textContent).toContain('retrieval');
    expect(container.textContent).toContain('settings.sources.syncNow');
  });

  it('shows the connection as the badge when it is known', async () => {
    await renderConnector({
      sourceName: 'test-2',
      sourceType: 's3',
      connection: { name: 'Amazon S3', icon: 's3' },
    });
    expect(badge()!.textContent).toBe('Amazon S3');
    expect(badge()!.querySelector('svg')).not.toBeNull();
  });

  it('puts the schedule in the byline', async () => {
    await renderConnector({
      sourceName: 'test-2',
      syncFrequency: 'weekly',
      syncedAt: '2026-10-21T10:00:00Z',
    });
    const byline = container.querySelector('p.text-muted-foreground');
    expect(byline?.textContent).toBe(
      'settings.sources.filesByline · settings.sources.website.synced',
    );
  });

  it('puts the source menu last in the title row', async () => {
    await renderConnector({
      headerAction: retrieval,
      headerMenu: <button type="button">source menu</button>,
    });
    expect(titleRow()).toEqual([
      'retrieval',
      'settings.sources.syncNow',
      'source menu',
    ]);
  });

  const toasts = () =>
    dispatch.mock.calls
      .map(([action]) => action)
      .filter((action) => action?.type === 'actionToast/showActionToast')
      .map((action) => action.payload);

  const confirmSync = async () => {
    const open = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'settings.sources.syncNow',
    )!;
    await act(async () => open.click());
    const submit = Array.from(
      document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button'),
    ).find((b) => b.textContent === 'settings.sources.syncNow')!;
    await act(async () => submit.click());
  };

  it('syncs a loader-typed source through sync_source and says so', async () => {
    dispatch.mockReset();
    sync.source.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, task_id: 't' }),
    });
    await renderConnector({ sourceName: 'test-2', sourceType: 's3' });
    await confirmSync();
    expect(sync.source).toHaveBeenCalledWith({ source_id: 'doc' }, null);
    expect(sync.connector).not.toHaveBeenCalled();
    // The sync's events carry its task id, so the wait matches them.
    expect(waitForChange).toHaveBeenCalledWith('doc', expect.any(Number), {
      taskId: 't',
    });
    expect(toasts()).toEqual([
      { variant: 'success', message: 'settings.sources.syncStarted' },
    ]);
  });

  it.each([
    [
      's3',
      400,
      { code: 'not_syncable', error: 'English' },
      'settings.connectors.detail.syncRefusedNotSyncable',
    ],
    [
      's3',
      400,
      { success: false, message: 'Nothing to sync.' },
      'Nothing to sync.',
    ],
    // A server error's own text is never shown: the generic line instead.
    [
      'connector:file',
      500,
      { success: false, error: 'boom' },
      'settings.sources.errors.sync',
    ],
  ])(
    'a refused %s sync (%s) says why (%o)',
    async (sourceType, status, body, message) => {
      dispatch.mockReset();
      const endpoint = sourceType === 's3' ? sync.source : sync.connector;
      endpoint.mockResolvedValue({
        ok: false,
        status,
        json: async () => body,
      });
      await renderConnector({ sourceType });
      await confirmSync();
      expect(endpoint).toHaveBeenCalled();
      expect(toasts()).toEqual([{ variant: 'destructive', message }]);
    },
  );

  it.each([
    [null, 'destructive', 'settings.sources.errors.sync'],
    ['busy', 'warning', 'settings.sources.website.changeBusy'],
    ['wiki', 'destructive', 'settings.connectors.detail.syncRefusedWiki'],
    ['gone', 'destructive', 'settings.sources.website.sourceGone'],
  ])(
    'a sync the worker did not run says why (reason %s)',
    async (reason, variant, message) => {
      dispatch.mockReset();
      sync.connector.mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, task_id: 't' }),
      });
      waitForChange.mockResolvedValueOnce({ terminal: 'failed', reason });
      await renderConnector({ sourceType: 'connector:file' });
      await confirmSync();
      expect(toasts()).toEqual([
        { variant: 'success', message: 'settings.sources.syncStarted' },
        { variant, message },
      ]);
    },
  );

  it('embedded ConnectorTree drops the badge and headerAction, keeps Sync', async () => {
    await renderConnector({ embedded: true, headerAction: retrieval });
    expect(badge()).toBeNull();
    expect(container.textContent).not.toContain('retrieval');
    expect(container.textContent).toContain('settings.sources.syncNow');
    expect(container.textContent).not.toContain('settings.sources.label');
  });

  it('embedded FileTree drops headerAction, keeps Add file', async () => {
    await render(
      <FileTree
        embedded
        docId="doc"
        sourceName="Files"
        onBackToDocuments={vi.fn()}
        headerAction={retrieval}
      />,
    );
    expect(badge()).toBeNull();
    expect(container.textContent).not.toContain('retrieval');
    expect(container.textContent).toContain('settings.sources.addFile');
  });

  const crumbs = () =>
    Array.from(container.querySelectorAll('[data-slot="breadcrumb-item"]')).map(
      (el) => el.textContent,
    );

  it('ConnectorTree and FileTree open the initialPath file', async () => {
    await renderConnector({ initialPath: 'b.docx' });
    expect(crumbs()).toEqual(['settings.sources.label', 'Drive', 'b.docx']);

    await render(
      <FileTree
        docId="doc"
        sourceName="Files"
        onBackToDocuments={vi.fn()}
        initialPath="a.docx"
      />,
    );
    expect(crumbs()).toEqual(['settings.sources.label', 'Files', 'a.docx']);
  });
  const openFirstRowMenu = async () => {
    const trigger = container.querySelector<HTMLButtonElement>(
      'tbody button[aria-label="settings.sources.menuAlt"]',
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

  it.each([
    ['a read-only', { canEdit: false }],
    ['a nothing-to-sync-with', { canSync: false }],
  ])('%s ConnectorTree hides Sync, keeps headerAction', async (_, props) => {
    await renderConnector({ headerAction: retrieval, ...props });
    expect(container.textContent).toContain('retrieval');
    expect(container.textContent).not.toContain('settings.sources.syncNow');
  });

  it('read-only FileTree hides Add file and the row Delete', async () => {
    await render(
      <FileTree
        docId="doc"
        sourceName="Files"
        onBackToDocuments={vi.fn()}
        headerAction={retrieval}
        canEdit={false}
      />,
    );
    expect(container.textContent).toContain('retrieval');
    expect(container.textContent).not.toContain('settings.sources.addFile');
    expect(await openFirstRowMenu()).not.toContain('settings.sources.delete');
  });

  it('an editable FileTree keeps Add file and the row Delete', async () => {
    await render(
      <FileTree
        docId="doc"
        sourceName="Files"
        onBackToDocuments={vi.fn()}
        canEdit
      />,
    );
    expect(container.textContent).toContain('settings.sources.addFile');
    expect(await openFirstRowMenu()).toContain('settings.sources.delete');
    // Delete is set apart by a rule.
    const separator = document.querySelector(
      '[role="menu"] [role="separator"]',
    );
    expect(separator?.nextElementSibling?.textContent).toBe(
      'settings.sources.delete',
    );
  });

  it('FileTree puts the source menu after Add file', async () => {
    await render(
      <FileTree
        docId="doc"
        sourceName="Files"
        onBackToDocuments={vi.fn()}
        headerAction={retrieval}
        headerMenu={<button type="button">source menu</button>}
      />,
    );
    expect(titleRow()).toEqual([
      'retrieval',
      'settings.sources.addFile',
      'source menu',
    ]);
  });

  it('a one-file FileTree has no file menu in the title row', async () => {
    tree.structure = { 'a.docx': { type: 'docx' } };
    try {
      await render(
        <FileTree
          docId="doc"
          sourceName="Files"
          onBackToDocuments={vi.fn()}
          canEdit
        />,
      );
      expect(
        container.querySelector(
          'button[aria-label="settings.sources.menuAlt"]',
        ),
      ).toBeNull();
    } finally {
      tree.structure = {
        'a.docx': { type: 'docx' },
        'b.docx': { type: 'docx' },
      };
    }
  });

  it('a read-only one-file FileTree has no header menu and no Add chunk', async () => {
    tree.structure = { 'a.docx': { type: 'docx' } };
    try {
      await render(
        <FileTree
          docId="doc"
          sourceName="Files"
          onBackToDocuments={vi.fn()}
          canEdit={false}
        />,
      );
      expect(
        container.querySelector(
          'button[aria-label="settings.sources.menuAlt"]',
        ),
      ).toBeNull();
      expect(container.textContent).not.toContain('settings.sources.addChunk');
    } finally {
      tree.structure = {
        'a.docx': { type: 'docx' },
        'b.docx': { type: 'docx' },
      };
    }
  });
});
