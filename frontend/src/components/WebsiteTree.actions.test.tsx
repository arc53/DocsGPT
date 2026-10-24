import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { TreeBrowserProps } from './tree/TreeBrowser';
import type { RowMenuContext } from './tree/types';
import type { MenuOption } from './ui/dropdown-menu';

const { bus, captured, dispatch, service } = vi.hoisted(() => ({
  dispatch: vi.fn(),
  // The notifications ring the reingest waiter reads, and its listeners.
  bus: { events: [] as unknown[], listeners: new Set<() => void>() },
  captured: {
    props: null as TreeBrowserProps | null,
    onQueued: null as
      ((startedAt: number, taskId: string | null) => void) | null,
    onQueueFailed: null as ((message: string) => void) | null,
  },
  service: {
    getWebsite: vi.fn(),
    removeWebsitePages: vi.fn(),
    refreshWebsitePage: vi.fn(),
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key} ${JSON.stringify(opts)}` : key,
  }),
}));

vi.mock('react-redux', () => {
  const store = {
    getState: () => ({ notifications: { recentEvents: bus.events } }),
    subscribe: (listener: () => void) => {
      bus.listeners.add(listener);
      return () => bus.listeners.delete(listener);
    },
  };
  return {
    useSelector: () => 'token',
    useDispatch: () => dispatch,
    useStore: () => store,
  };
});

vi.mock('../api/services/userService', () => ({ default: service }));

// The tree itself is covered by WebsiteTree.test.tsx; here we drive the
// props WebsiteTree hands it.
vi.mock('./tree/TreeBrowser', () => ({
  default: (props: TreeBrowserProps) => {
    captured.props = props;
    return (
      <div>
        {props.topRightAction}
        {props.extraContent}
      </div>
    );
  },
}));

vi.mock('./AddWebsitePagesModal', () => ({
  default: (props: {
    graph?: boolean;
    onQueued: NonNullable<typeof captured.onQueued>;
    onQueueFailed: NonNullable<typeof captured.onQueueFailed>;
  }) => {
    captured.onQueued = props.onQueued;
    captured.onQueueFailed = props.onQueueFailed;
    return <div>add-pages-modal{props.graph ? ' graph' : ''}</div>;
  },
}));

import WebsiteTree from './WebsiteTree';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const STRUCTURE = {
  Deploying: {
    'Docker.md': {
      type: 'text/markdown',
      token_count: 1,
      url: 'https://docs.x.io/Deploying/Docker',
    },
  },
  'extra.md': {
    type: 'text/markdown',
    token_count: 1,
    url: 'https://docs.x.io/extra',
  },
};

// A page from before pages kept their address (an older website source).
const LEGACY = {
  'legacy.md': { type: 'text/markdown', token_count: 1 },
  Old: { 'a.md': { type: 'text/markdown', token_count: 1 } },
};

// A page added as /old whose fetch landed on /new.
const REDIRECTED = {
  type: 'text/markdown',
  token_count: 1,
  url: 'https://docs.x.io/new',
  requested_urls: ['https://docs.x.io/old'],
};

const view: MenuOption = { label: 'view', onClick: vi.fn() };

/** GET /api/website's answer: the config, and the pages it lists by address. */
const website = (
  entries: { url: string; mode: string }[],
  entryPaths?: string[],
) => ({
  ok: true,
  json: async () => ({
    config: { entries },
    ...(entryPaths ? { entry_paths: entryPaths } : {}),
  }),
});

/** A terminal ingest event for the source, as the SSE stream adds it. */
const emitTerminal = (
  type: 'completed' | 'failed' = 'completed',
  taskId?: string,
  extra: Record<string, unknown> = {},
) => {
  bus.events = [
    {
      id: `${Date.now()}-${bus.events.length}`,
      type: `source.ingest.${type}`,
      ts: new Date().toISOString(),
      scope: { kind: 'source', id: 'src-1' },
      payload: { ...(taskId ? { task_id: taskId } : {}), ...extra },
    },
    ...bus.events,
  ];
  for (const listener of Array.from(bus.listeners)) listener();
};

const fakeController = () => ({
  refreshDirectory: vi.fn(async () => true),
  resetPath: vi.fn(),
  reloadFile: vi.fn(),
});

const refused = (status: number, body: unknown) => ({
  ok: false,
  status,
  json: async () => body,
});

describe('WebsiteTree page management', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    bus.events = [];
    bus.listeners.clear();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    service.getWebsite.mockResolvedValue(
      website(
        [
          { url: 'https://docs.x.io/', mode: 'site' },
          { url: 'https://docs.x.io/extra/', mode: 'page' },
        ],
        ['extra.md'],
      ),
    );
    service.removeWebsitePages.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.clearAllMocks();
  });

  /** Renders the tree of source src-1, without its pages. */
  const renderTree = (
    props: Partial<React.ComponentProps<typeof WebsiteTree>> = {},
  ) =>
    act(async () => {
      root.render(
        <WebsiteTree
          docId="src-1"
          sourceName="Docs"
          onBackToDocuments={() => undefined}
          hosts={['docs.x.io']}
          {...props}
        />,
      );
    });

  const loadPages = (structure: Record<string, unknown> = STRUCTURE) =>
    act(async () => {
      captured.props!.onDirectoryDataLoaded!({
        directory_structure: structure,
      });
    });

  /** A weekly-synced source with its pages loaded. */
  const render = async (canEdit = true) => {
    await renderTree({ syncFrequency: 'weekly', canEdit });
    await loadPages();
  };

  const menu = (ctx: Partial<RowMenuContext>): MenuOption[] =>
    captured.props!.getRowMenuOptions!({
      defaultViewOption: view,
      name: '',
      isFile: true,
      itemId: 'row',
      ...ctx,
    });

  const extraMenu = () =>
    menu({ name: 'extra.md', isFile: true, node: STRUCTURE['extra.md'] });

  const text = () => document.body.textContent ?? '';

  const addPagesButton = () =>
    Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('settings.sources.website.addPages'),
    );

  const openAddPages = () => act(async () => addPagesButton()!.click());

  /** Clicks the dialog's button labelled with a website key. */
  const confirm = (label: string) =>
    act(async () =>
      Array.from(document.body.querySelectorAll('button'))
        .find((b) => b.textContent === `settings.sources.website.${label}`)!
        .click(),
    );

  /** Opens Remove on the page added by address and confirms it. */
  const removeEntry = async () => {
    await act(async () => extraMenu().at(-1)!.onClick(new Event('click')));
    await confirm('remove');
  };

  /** Refreshes extra.md, queued as `taskId`; returns the tree's controller. */
  const clickRefresh = async (taskId = 'task-1') => {
    const controller = fakeController();
    captured.props!.controllerRef!.current = controller;
    service.refreshWebsitePage.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, task_id: taskId }),
    });
    const refresh = extraMenu().find(
      (o) => o.label === 'settings.sources.website.refreshPage',
    )!;
    await act(async () => refresh.onClick(new Event('click')));
    return controller;
  };

  const toasted = () =>
    dispatch.mock.calls.map((call) => call[0].payload) as {
      variant: string;
      message: string;
    }[];

  it('gives editors Open, Refresh and Remove; viewers only Open', async () => {
    await render();
    expect(extraMenu().map((o) => o.label)).toEqual([
      'view',
      'settings.sources.website.openPage',
      'settings.sources.website.refreshPage',
      'settings.sources.website.removeFromSource',
    ]);

    await render(false);
    expect(extraMenu().map((o) => o.label)).toEqual([
      'view',
      'settings.sources.website.openPage',
    ]);
    expect(container.textContent).not.toContain(
      'settings.sources.website.addPages',
    );
  });

  const REMOVE_COPIES = [
    'removeEntry',
    'removeCrawled',
    'removeFolder',
    'removeGeneric',
    'removeFolderGeneric',
  ];

  it.each([
    [
      'a page added by its address takes it off the list',
      { name: 'extra.md', node: STRUCTURE['extra.md'] },
      'removeEntry',
      'remove',
      { file_paths: ['extra.md'] },
    ],
    [
      'a crawled page says later syncs skip it',
      {
        folder: ['Deploying'],
        name: 'Docker.md',
        node: STRUCTURE.Deploying['Docker.md'],
      },
      'removeCrawled {"host":"docs.x.io","interpolation":{"escapeValue":false}}',
      'removeAndSkip',
      { file_paths: ['Deploying/Docker.md'] },
    ],
    // The server matches a page to its entry by every address it was added
    // under, a redirected one too; the tree goes by its answer.
    [
      'a page the server lists as an entry, whatever its own address',
      {
        structure: { 'new.md': REDIRECTED },
        entryPaths: ['new.md'],
        name: 'new.md',
        node: REDIRECTED,
      },
      'removeEntry',
      'remove',
      { file_paths: ['new.md'] },
    ],
    [
      'a folder skips its whole address',
      { name: 'Deploying', isFile: false },
      'removeFolder {"address":"docs.x.io/Deploying/","interpolation":{"escapeValue":false}}',
      'removeAndSkip',
      { directory_path: 'Deploying' },
    ],
    // Where an address-less page came from is unknown: the copy says only
    // what holds anyway.
    [
      'a page with no address names no host',
      { structure: LEGACY, name: 'legacy.md', node: LEGACY['legacy.md'] },
      'removeGeneric',
      'remove',
      { file_paths: ['legacy.md'] },
    ],
    [
      'a folder of pages with no address names no address',
      { structure: LEGACY, name: 'Old', isFile: false },
      'removeFolderGeneric',
      'remove',
      { directory_path: 'Old' },
    ],
  ] as const)(
    'removing %s',
    async (_, row: Record<string, unknown>, copy, submit, body) => {
      const { folder, structure, entryPaths, name, node, isFile } = row as {
        folder?: string[];
        structure?: Record<string, unknown>;
        entryPaths?: string[];
        name: string;
        node?: Record<string, unknown>;
        isFile?: boolean;
      };
      if (entryPaths)
        service.getWebsite.mockResolvedValue(
          website([{ url: 'https://docs.x.io/', mode: 'site' }], entryPaths),
        );
      await render();
      if (structure) await loadPages(structure);
      if (folder) captured.props!.onCurrentPathChange!(folder);
      const remove = menu({ name, isFile: isFile ?? true, node }).at(-1)!;
      await act(async () => remove.onClick(new Event('click')));

      expect(text()).toContain(`settings.sources.website.${copy}`);
      for (const other of REMOVE_COPIES.filter(
        (key) => !copy.startsWith(`${key} `) && copy !== key,
      ))
        expect(text()).not.toMatch(
          new RegExp(`settings\\.sources\\.website\\.${other}(?![A-Za-z])`),
        );
      await confirm(submit);
      expect(service.removeWebsitePages).toHaveBeenCalledWith(
        { source_id: 'src-1', ...body },
        'token',
      );
    },
  );

  it('a remove closes the dialog and waits for its task in the header', async () => {
    service.removeWebsitePages.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, task_id: 'task-r' }),
    });
    await render();
    const controller = fakeController();
    captured.props!.controllerRef!.current = controller;
    await removeEntry();

    expect(text()).not.toContain('settings.sources.website.removeEntry');
    expect(captured.props!.statusLabel).toBe(
      'settings.sources.website.removing',
    );
    expect(extraMenu().at(-1)!.disabled).toBe(true);
    expect(controller.refreshDirectory).not.toHaveBeenCalled();

    service.getWebsite.mockClear();
    await act(async () => emitTerminal('completed', 'task-other'));
    expect(controller.refreshDirectory).not.toHaveBeenCalled();
    await act(async () =>
      emitTerminal('completed', 'task-r', { paths: ['extra.md'] }),
    );
    expect(controller.refreshDirectory).toHaveBeenCalled();
    // The source's list of page entries is read again too.
    expect(service.getWebsite).toHaveBeenCalled();
    expect(captured.props!.statusLabel).toBeNull();
    expect(dispatch).not.toHaveBeenCalled();
    // Only the removed page's chunks are stale; it closes by itself.
    expect(controller.reloadFile).toHaveBeenCalledWith(['extra.md']);
  });

  it('a change still running after the wait says so and reads the tree again', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      await render();
      const controller = await clickRefresh();
      service.getWebsite.mockClear();
      await act(async () => {
        vi.advanceTimersByTime(5 * 60_000 + 1);
      });
      expect(captured.props!.statusLabel).toBeNull();
      expect(controller.refreshDirectory).toHaveBeenCalled();
      // Nothing is known to have changed in the open page yet.
      expect(controller.reloadFile).toHaveBeenCalledWith([]);
      expect(service.getWebsite).toHaveBeenCalled();
      expect(toasted()).toEqual([
        { variant: 'info', message: 'settings.sources.website.stillRunning' },
      ]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a change that didn't run because another held the source says to try again", async () => {
    await render();
    const controller = await clickRefresh();
    await act(async () => emitTerminal('failed', 'task-1', { reason: 'busy' }));
    expect(controller.refreshDirectory).not.toHaveBeenCalled();
    expect(toasted()).toEqual([
      { variant: 'warning', message: 'settings.sources.website.changeBusy' },
    ]);
  });

  it('a refreshed page that now leads out of the source says it was removed and reads the tree again', async () => {
    await render();
    const controller = await clickRefresh();
    service.getWebsite.mockClear();
    await act(async () =>
      emitTerminal('failed', 'task-1', { reason: 'out_of_scope' }),
    );
    expect(controller.refreshDirectory).toHaveBeenCalled();
    expect(service.getWebsite).toHaveBeenCalled();
    expect(toasted()).toEqual([
      {
        variant: 'warning',
        message: expect.stringMatching(
          '^settings.sources.website.refreshOutOfScope',
        ),
      },
    ]);
    expect(captured.props!.statusLabel).toBeNull();
  });

  it.each([
    ['wiki', 'settings.sources.website.wikiSource'],
    ['gone', 'settings.sources.website.sourceGone'],
  ])(
    'a change skipped because the source is %s says so',
    async (reason, key) => {
      await render();
      await clickRefresh();
      await act(async () => emitTerminal('failed', 'task-1', { reason }));
      expect(toasted()).toEqual([
        { variant: 'destructive', message: expect.stringMatching(`^${key}`) },
      ]);
    },
  );

  it('tells the host once a page change has finished', async () => {
    const onPagesChanged = vi.fn();
    await renderTree({ onPagesChanged });
    await clickRefresh();
    expect(onPagesChanged).not.toHaveBeenCalled();
    await act(async () => emitTerminal('failed', 'task-1'));
    expect(onPagesChanged).not.toHaveBeenCalled();
    await clickRefresh('task-2');
    await act(async () => emitTerminal('completed', 'task-2'));
    expect(onPagesChanged).toHaveBeenCalledTimes(1);
  });

  it('a remove that fails in the worker toasts it', async () => {
    service.removeWebsitePages.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, task_id: 'task-r' }),
    });
    await render();
    const controller = fakeController();
    captured.props!.controllerRef!.current = controller;
    await removeEntry();
    await act(async () => emitTerminal('failed', 'task-r'));

    expect(controller.refreshDirectory).not.toHaveBeenCalled();
    expect(captured.props!.statusLabel).toBeNull();
    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({
        payload: expect.objectContaining({
          variant: 'destructive',
          message: expect.stringContaining(
            'settings.sources.website.removeFailed',
          ),
        }),
      }),
    );
  });

  it.each([
    [
      400,
      { code: 'wiki', error: 'wiki' },
      'settings.sources.website.wikiSource',
    ],
    [
      400,
      { code: 'chunks_unsupported', error: 'no' },
      'settings.sources.website.chunksUnsupported',
    ],
    [
      400,
      { code: 'last_entry', error: 'last' },
      'settings.sources.website.removeLast',
    ],
    // No code: the server's own message.
    [
      400,
      { success: false, error: 'The skip list holds up to 1000 rules' },
      'The skip list holds up to 1000 rules',
    ],
    [500, { success: false }, 'settings.sources.website.removeFailed'],
  ])(
    'a refused remove (%i %o) says why in the dialog',
    async (status, body, shown) => {
      service.removeWebsitePages.mockResolvedValue(refused(status, body));
      await render();
      await removeEntry();
      expect(text()).toContain(shown);
      expect(text().includes('settings.sources.website.removeFailed')).toBe(
        shown === 'settings.sources.website.removeFailed',
      );
      // The dialog stays open on its refusal.
      expect(text()).toContain('settings.sources.website.removeEntry');
    },
  );

  it('a refused refresh toasts why', async () => {
    service.refreshWebsitePage.mockResolvedValue(
      refused(400, { code: 'chunks_unsupported', error: 'no' }),
    );
    await render();
    const refresh = extraMenu().find(
      (o) => o.label === 'settings.sources.website.refreshPage',
    )!;
    await act(async () => refresh.onClick(new Event('click')));
    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({
        payload: expect.objectContaining({
          variant: 'destructive',
          message: 'settings.sources.website.chunksUnsupported',
        }),
      }),
    );
  });

  it("passes the source's menu to the title row", async () => {
    const headerMenu = <button type="button">source menu</button>;
    await renderTree({ headerMenu });
    expect(captured.props!.headerMenu).toBe(headerMenu);
  });

  it("embedded, it hands the host's header slot and crumbs to the tree", async () => {
    const target = document.createElement('div');
    const onCrumbsChange = vi.fn();
    await renderTree({
      embedded: true,
      actionsTarget: target,
      onCrumbsChange,
      headerAction: <button type="button">Test retrieval</button>,
    });
    expect(captured.props!.embedded).toBe(true);
    expect(captured.props!.actionsTarget).toBe(target);
    expect(captured.props!.onCrumbsChange).toBe(onCrumbsChange);
    // The host draws Test retrieval; Add pages stays.
    expect(container.textContent).not.toContain('Test retrieval');
    expect(container.textContent).toContain(
      'settings.sources.website.addPages',
    );
  });

  it('tells Add pages when the source has a knowledge graph', async () => {
    await renderTree({ graph: true });
    await openAddPages();
    expect(text()).toContain('add-pages-modal graph');
  });

  it('opens Add pages from the header', async () => {
    await render();
    // A primary button is text only.
    expect(addPagesButton()!.querySelector('svg')).toBeNull();
    await openAddPages();
    expect(text()).toContain('add-pages-modal');
  });

  it('warns that hand edits are replaced on a synced source', async () => {
    await render();
    expect(captured.props!.chunksNotice).toBeTruthy();
  });

  it('lists a refreshed page again once its own refresh finishes', async () => {
    await render();
    const controller = await clickRefresh('task-1');
    // The leaf's address goes with its path, so the server refreshes the
    // page the tree shows even when two addresses share a path.
    expect(service.refreshWebsitePage).toHaveBeenCalledWith(
      {
        source_id: 'src-1',
        file_path: 'extra.md',
        url: 'https://docs.x.io/extra',
      },
      'token',
    );

    await act(async () => emitTerminal('completed', 'task-other'));
    expect(controller.refreshDirectory).not.toHaveBeenCalled();
    await act(async () =>
      emitTerminal('completed', 'task-1', { paths: ['extra.md'] }),
    );
    expect(controller.refreshDirectory).toHaveBeenCalled();
    expect(controller.reloadFile).toHaveBeenCalledWith(['extra.md']);
  });

  // The event names the pages the add wrote; one that queued a rebuild
  // instead names none, and any page may have changed.
  it.each([
    ['an append', { paths: ['extra.md', 'new.md'] }, ['extra.md', 'new.md']],
    ['a rebuild', {}, undefined],
  ])(
    'after %s, lists the open page again when it may have changed',
    async (_, payload, reloaded) => {
      await render();
      const controller = fakeController();
      captured.props!.controllerRef!.current = controller;
      await openAddPages();
      await act(async () => captured.onQueued!(Date.now(), 'task-2'));
      await act(async () => emitTerminal('completed', 'task-2', payload));
      expect(controller.refreshDirectory).toHaveBeenCalled();
      expect(controller.reloadFile).toHaveBeenCalledTimes(1);
      expect(controller.reloadFile).toHaveBeenCalledWith(reloaded);
    },
  );

  describe('added pages that could not be fetched', () => {
    const addPages = async (failedPages?: unknown) => {
      await render();
      captured.props!.controllerRef!.current = fakeController();
      await openAddPages();
      await act(async () => captured.onQueued!(Date.now(), 'task-a'));
      await act(async () =>
        emitTerminal(
          'completed',
          'task-a',
          failedPages === undefined ? {} : { failed_pages: failedPages },
        ),
      );
    };

    it('names the one page and says the next sync tries it again', async () => {
      await addPages(['https://docs.x.io/b/']);
      expect(toasted()).toEqual([
        {
          variant: 'warning',
          message: expect.stringMatching(
            /^settings\.sources\.website\.pageNotFetched .*"url":"docs\.x\.io\/b"/,
          ),
        },
      ]);
    });

    it('counts several pages', async () => {
      await addPages(['https://docs.x.io/a', 'https://docs.x.io/b']);
      expect(toasted()).toEqual([
        {
          variant: 'warning',
          message: expect.stringMatching(
            /^settings\.sources\.website\.pagesNotFetched .*"count":2/,
          ),
        },
      ]);
    });

    it('says nothing when every page came in', async () => {
      await addPages();
      await addPages([]);
      expect(toasted()).toEqual([]);
    });
  });

  it('turns the row changes off while a change runs', async () => {
    await render();
    await clickRefresh();

    const byLabel = Object.fromEntries(
      extraMenu().map((o) => [o.label, !!o.disabled]),
    );
    expect(byLabel).toEqual({
      view: false,
      'settings.sources.website.openPage': false,
      'settings.sources.website.refreshPage': true,
      'settings.sources.website.removeFromSource': true,
    });
    expect(container.textContent).not.toContain(
      'settings.sources.website.addPages',
    );

    await act(async () => emitTerminal());
    expect(extraMenu().some((o) => o.disabled)).toBe(false);
  });

  it('offers Open page only for a web address', async () => {
    await render();
    const labels = menu({
      name: 'x.md',
      isFile: true,
      node: { type: 'text/markdown', url: 'javascript:alert(1)' },
    }).map((o) => o.label);
    expect(labels).not.toContain('settings.sources.website.openPage');
  });

  /** Asks to remove a page, and returns the dialog's text and submit label. */
  const askRemovePage = async (name: string, node: Record<string, unknown>) => {
    const remove = menu({ name, isFile: true, node }).at(-1)!;
    await act(async () => remove.onClick(new Event('click')));
    const submit = Array.from(document.body.querySelectorAll('button')).find(
      (b) =>
        b.textContent === 'settings.sources.website.remove' ||
        b.textContent === 'settings.sources.website.removeAndSkip',
    );
    return { text: text(), submit: submit?.textContent };
  };

  it("says only what holds for any page until the source's list has loaded", async () => {
    let answer: (value: unknown) => void = () => undefined;
    service.getWebsite.mockReturnValue(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    await render();
    const { text: shown, submit } = await askRemovePage(
      'extra.md',
      STRUCTURE['extra.md'],
    );
    expect(shown).toContain('settings.sources.website.removeGeneric');
    expect(shown).not.toContain('settings.sources.website.removeEntry');
    expect(shown).not.toContain('settings.sources.website.removeCrawled');
    expect(submit).toBe('settings.sources.website.remove');

    // Once the list arrives, the open dialog says where the page came from.
    await act(async () =>
      answer(
        website(
          [{ url: 'https://docs.x.io/extra', mode: 'page' }],
          ['extra.md'],
        ),
      ),
    );
    expect(text()).toContain('settings.sources.website.removeEntry');
  });

  it.each([
    ['refused', () => ({ ok: false, status: 500, json: async () => ({}) })],
    [
      'broken',
      () => {
        throw new Error('offline');
      },
    ],
    // An older server: its config, but not which pages are its entries.
    [
      'without the entry paths',
      () => website([{ url: 'https://docs.x.io/', mode: 'site' }]),
    ],
  ])(
    'keeps the copy that holds for any page when the list read is %s',
    async (_, reply) => {
      service.getWebsite.mockImplementation(async () => reply());
      await render();
      const { text: shown, submit } = await askRemovePage(
        'Docker.md',
        STRUCTURE.Deploying['Docker.md'],
      );
      expect(shown).toContain('settings.sources.website.removeGeneric');
      expect(shown).not.toContain('settings.sources.website.removeCrawled');
      expect(submit).toBe('settings.sources.website.remove');
    },
  );

  it("reads the source's list again when the host says its settings were saved", async () => {
    await render();
    service.getWebsite.mockResolvedValue(
      website([{ url: 'https://docs.x.io/', mode: 'site' }], []),
    );
    await renderTree({ syncFrequency: 'weekly', settingsVersion: 1 });
    expect(service.getWebsite).toHaveBeenCalledTimes(2);
    const { text: shown } = await askRemovePage(
      'extra.md',
      STRUCTURE['extra.md'],
    );
    expect(shown).toContain('settings.sources.website.removeCrawled');
  });

  it('reads which pages are entries again once a change finishes', async () => {
    service.removeWebsitePages.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, task_id: 'task-r' }),
    });
    await render();
    captured.props!.controllerRef!.current = fakeController();
    await removeEntry();
    // The entry is gone from the config: the page left is now crawled.
    service.getWebsite.mockResolvedValue(
      website([{ url: 'https://docs.x.io/', mode: 'site' }], []),
    );
    await act(async () =>
      emitTerminal('completed', 'task-r', { paths: ['extra.md'] }),
    );
    const { text: shown } = await askRemovePage(
      'extra.md',
      STRUCTURE['extra.md'],
    );
    expect(shown).toContain('settings.sources.website.removeCrawled');
  });

  describe('a sync the host started', () => {
    const renderSyncing = async (
      sync: { startedAt: number; taskId: string | null } | null,
      onPagesChanged = vi.fn(),
    ) => {
      await renderTree({ syncFrequency: 'weekly', sync, onPagesChanged });
      return onPagesChanged;
    };

    it('marks the tree busy, then reads it again once the sync finishes', async () => {
      const controller = fakeController();
      await renderSyncing(null);
      captured.props!.controllerRef!.current = controller;
      const onPagesChanged = await renderSyncing({
        startedAt: Date.now(),
        taskId: 'task-s',
      });
      expect(captured.props!.statusLabel).toBe(
        'settings.sources.website.syncing',
      );
      expect(container.textContent).not.toContain(
        'settings.sources.website.addPages',
      );
      expect(
        extraMenu()
          .filter((o) => o.label !== 'view')
          .filter((o) => o.label !== 'settings.sources.website.openPage')
          .every((o) => o.disabled),
      ).toBe(true);

      await act(async () => emitTerminal('completed', 'task-other'));
      expect(controller.refreshDirectory).not.toHaveBeenCalled();
      await act(async () => emitTerminal('completed', 'task-s'));
      expect(controller.refreshDirectory).toHaveBeenCalled();
      // A sync names no pages: it may change any, the open one too.
      expect(controller.reloadFile).toHaveBeenCalledWith(undefined);
      expect(onPagesChanged).toHaveBeenCalledTimes(1);
      expect(captured.props!.statusLabel).toBeNull();
      expect(container.textContent).toContain(
        'settings.sources.website.addPages',
      );
    });

    it('tells the host when its wait for the sync ends, whatever the outcome', async () => {
      const onSyncSettled = vi.fn();
      const sync = { startedAt: Date.now(), taskId: 'task-s' };
      await renderTree({ sync: null, onSyncSettled });
      captured.props!.controllerRef!.current = fakeController();
      await renderTree({ sync, onSyncSettled });
      expect(onSyncSettled).not.toHaveBeenCalled();
      await act(async () =>
        emitTerminal('failed', 'task-s', { reason: 'busy' }),
      );
      expect(onSyncSettled).toHaveBeenCalledTimes(1);
      expect(onSyncSettled).toHaveBeenCalledWith(sync);
    });

    it('does not tell the host a sync ended when the tree unmounts first', async () => {
      const onSyncSettled = vi.fn();
      await renderTree({
        sync: { startedAt: Date.now(), taskId: 'task-s' },
        onSyncSettled,
      });
      await act(async () => root.render(<></>));
      await act(async () => emitTerminal('completed', 'task-s'));
      expect(onSyncSettled).not.toHaveBeenCalled();
    });

    it('waits for the same sync once, across renders', async () => {
      const controller = fakeController();
      await renderSyncing(null);
      captured.props!.controllerRef!.current = controller;
      const sync = { startedAt: Date.now(), taskId: 'task-s' };
      const onPagesChanged = vi.fn();
      await renderSyncing(sync, onPagesChanged);
      await renderSyncing(sync, onPagesChanged);
      await act(async () => emitTerminal('completed', 'task-s'));
      expect(controller.refreshDirectory).toHaveBeenCalledTimes(1);
      expect(onPagesChanged).toHaveBeenCalledTimes(1);
    });

    it('stays busy until every overlapping change has ended', async () => {
      const onBusyChange = vi.fn();
      const renderWith = (sync: { startedAt: number; taskId: string } | null) =>
        renderTree({ syncFrequency: 'weekly', sync, onBusyChange });
      await renderWith(null);
      await loadPages();
      expect(onBusyChange).toHaveBeenLastCalledWith(false);
      await clickRefresh('task-r');
      expect(onBusyChange).toHaveBeenLastCalledWith(true);
      // The source's ⋯ → Sync now while the refresh runs.
      await renderWith({ startedAt: Date.now(), taskId: 'task-s' });
      expect(captured.props!.statusLabel).toBe(
        'settings.sources.website.syncing',
      );

      // The refresh finishes first: the sync still holds the tree.
      await act(async () => emitTerminal('completed', 'task-r'));
      expect(captured.props!.statusLabel).toBe(
        'settings.sources.website.syncing',
      );
      expect(extraMenu().at(-1)!.disabled).toBe(true);
      expect(container.textContent).not.toContain(
        'settings.sources.website.addPages',
      );
      expect(onBusyChange).toHaveBeenLastCalledWith(true);

      await act(async () => emitTerminal('completed', 'task-s'));
      expect(captured.props!.statusLabel).toBeNull();
      expect(extraMenu().at(-1)!.disabled).toBe(false);
      expect(container.textContent).toContain(
        'settings.sources.website.addPages',
      );
      expect(onBusyChange).toHaveBeenLastCalledWith(false);
    });

    it.each([
      ['busy', 'warning', 'settings.sources.website.changeBusy'],
      ['wiki', 'destructive', 'settings.sources.website.wikiSource'],
      ['gone', 'destructive', 'settings.sources.website.sourceGone'],
      [null, 'destructive', 'settings.sources.website.syncFailed'],
    ])('a sync that failed (%s) says why', async (reason, variant, key) => {
      await renderSyncing(null);
      captured.props!.controllerRef!.current = fakeController();
      await renderSyncing({ startedAt: Date.now(), taskId: 'task-s' });
      await act(async () =>
        emitTerminal('failed', 'task-s', reason ? { reason } : {}),
      );
      expect(toasted()).toEqual([
        { variant, message: expect.stringMatching(`^${key}`) },
      ]);
      expect(captured.props!.statusLabel).toBeNull();
    });
  });

  const QUEUE_FAILED = {
    success: false,
    code: 'queue_failed',
    message:
      "The change was saved, but its task couldn't be queued; the next sync picks it up.",
  };

  it("a remove saved but not queued closes the dialog and warns, in the UI's words", async () => {
    service.removeWebsitePages.mockResolvedValue(refused(500, QUEUE_FAILED));
    await render();
    service.getWebsite.mockClear();
    await removeEntry();
    expect(text()).not.toContain('settings.sources.website.removeEntry');
    expect(toasted()).toEqual([
      { variant: 'warning', message: 'settings.sources.website.queueFailed' },
    ]);
    expect(captured.props!.statusLabel).toBeNull();
    // The list changed: it is read again.
    expect(service.getWebsite).toHaveBeenCalled();
  });

  it("a refresh the server couldn't queue fails in the refresh's own words", async () => {
    // Nothing was saved for a refresh, so "the next sync picks it up" is wrong.
    service.refreshWebsitePage.mockResolvedValue(
      refused(500, {
        success: false,
        code: 'queue_failed',
        error: "The refresh couldn't be queued; try again, or sync the source.",
      }),
    );
    await render();
    const refresh = extraMenu().find(
      (o) => o.label === 'settings.sources.website.refreshPage',
    )!;
    await act(async () => refresh.onClick(new Event('click')));
    expect(toasted()).toEqual([
      {
        variant: 'destructive',
        message: expect.stringMatching(
          '^settings.sources.website.refreshFailed',
        ),
      },
    ]);
    expect(captured.props!.statusLabel).toBeNull();
  });

  it('pages saved but not queued warn and read the list again', async () => {
    await render();
    await openAddPages();
    service.getWebsite.mockClear();
    await act(async () =>
      captured.onQueueFailed!('settings.sources.website.queueFailed'),
    );
    expect(toasted()).toEqual([
      { variant: 'warning', message: 'settings.sources.website.queueFailed' },
    ]);
    expect(service.getWebsite).toHaveBeenCalled();
    expect(captured.props!.statusLabel).toBeNull();
  });

  /** The byline's link, as the tree draws it. */
  const bylineHref = async () => {
    const byline = document.createElement('div');
    const bylineRoot = createRoot(byline);
    await act(async () =>
      bylineRoot.render(
        <>{captured.props!.renderByline!({ files: 1, tokens: 1 })}</>,
      ),
    );
    const href = byline.querySelector('a')?.getAttribute('href');
    act(() => bylineRoot.unmount());
    return href;
  };

  it("links the source's first address by its own origin", async () => {
    service.getWebsite.mockResolvedValue(
      website([{ url: 'http://docs.x.io:8080/guide/', mode: 'site' }], []),
    );
    await render();
    expect(await bylineHref()).toBe('http://docs.x.io:8080');
  });

  it("doesn't link another source by the previous source's first address", async () => {
    service.getWebsite.mockResolvedValue(
      website([{ url: 'http://docs.x.io:8080/guide/', mode: 'site' }], []),
    );
    await render();
    // The same tree, now for a source the caller only reads (no config read).
    await renderTree({
      docId: 'src-2',
      sourceName: 'Blog',
      hosts: ['blog.y.io'],
      canEdit: false,
    });
    await loadPages({
      'a.md': {
        type: 'text/markdown',
        token_count: 1,
        url: 'https://blog.y.io/a',
      },
    });
    expect(await bylineHref()).toBe('https://blog.y.io');
  });
});
