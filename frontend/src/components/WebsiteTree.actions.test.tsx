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
      | ((
          startedAt: number,
          taskId?: string | null,
          change?: { mode?: string; urls: string[] },
        ) => void)
      | null,
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

const view: MenuOption = { label: 'view', onClick: vi.fn() };

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

describe('WebsiteTree page management', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    bus.events = [];
    bus.listeners.clear();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    service.getWebsite.mockResolvedValue({
      ok: true,
      json: async () => ({
        config: {
          entries: [
            { url: 'https://docs.x.io/', mode: 'site' },
            { url: 'https://docs.x.io/extra/', mode: 'page' },
          ],
        },
      }),
    });
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

  const render = async (canEdit = true) => {
    await act(async () => {
      root.render(
        <WebsiteTree
          docId="src-1"
          sourceName="Docs"
          onBackToDocuments={() => undefined}
          hosts={['docs.x.io']}
          syncFrequency="weekly"
          canEdit={canEdit}
        />,
      );
    });
    await act(async () => {
      captured.props!.onDirectoryDataLoaded!({
        directory_structure: STRUCTURE,
      });
    });
  };

  const menu = (ctx: Partial<RowMenuContext>): MenuOption[] =>
    captured.props!.getRowMenuOptions!({
      defaultViewOption: view,
      name: '',
      isFile: true,
      itemId: 'row',
      ...ctx,
    });

  it('gives editors Open, Refresh and Remove; viewers only Open', async () => {
    await render();
    const page = STRUCTURE['extra.md'];
    expect(
      menu({ name: 'extra.md', isFile: true, node: page }).map((o) => o.label),
    ).toEqual([
      'view',
      'settings.sources.website.openPage',
      'settings.sources.website.refreshPage',
      'settings.sources.website.removeFromSource',
    ]);

    await render(false);
    expect(
      menu({ name: 'extra.md', isFile: true, node: page }).map((o) => o.label),
    ).toEqual(['view', 'settings.sources.website.openPage']);
    expect(container.textContent).not.toContain(
      'settings.sources.website.addPages',
    );
  });

  it('removing a page added by its address takes it off the list', async () => {
    await render();
    const remove = menu({
      name: 'extra.md',
      isFile: true,
      node: STRUCTURE['extra.md'],
    }).at(-1)!;
    await act(async () => remove.onClick(new Event('click')));

    expect(document.body.textContent).toContain(
      'settings.sources.website.removeEntry',
    );
    const submit = Array.from(document.body.querySelectorAll('button')).find(
      (b) => b.textContent === 'settings.sources.website.remove',
    )!;
    await act(async () => submit.click());
    expect(service.removeWebsitePages).toHaveBeenCalledWith(
      { source_id: 'src-1', file_paths: ['extra.md'] },
      'token',
    );
  });

  it('removing a crawled page says later syncs skip it', async () => {
    await render();
    captured.props!.onCurrentPathChange!(['Deploying']);
    const remove = menu({
      name: 'Docker.md',
      isFile: true,
      node: STRUCTURE.Deploying['Docker.md'],
    }).at(-1)!;
    await act(async () => remove.onClick(new Event('click')));

    expect(document.body.textContent).toContain(
      'settings.sources.website.removeCrawled {"host":"docs.x.io","interpolation":{"escapeValue":false}}',
    );
    const submit = Array.from(document.body.querySelectorAll('button')).find(
      (b) => b.textContent === 'settings.sources.website.removeAndSkip',
    )!;
    await act(async () => submit.click());
    expect(service.removeWebsitePages).toHaveBeenCalledWith(
      { source_id: 'src-1', file_paths: ['Deploying/Docker.md'] },
      'token',
    );
  });

  it('removing a folder skips its whole address', async () => {
    await render();
    const remove = menu({ name: 'Deploying', isFile: false }).at(-1)!;
    await act(async () => remove.onClick(new Event('click')));

    expect(document.body.textContent).toContain(
      'settings.sources.website.removeFolder {"address":"docs.x.io/Deploying/","interpolation":{"escapeValue":false}}',
    );
    const submit = Array.from(document.body.querySelectorAll('button')).find(
      (b) => b.textContent === 'settings.sources.website.removeAndSkip',
    )!;
    await act(async () => submit.click());
    expect(service.removeWebsitePages).toHaveBeenCalledWith(
      { source_id: 'src-1', directory_path: 'Deploying' },
      'token',
    );
  });

  /** Opens Remove on the page added by address and confirms it. */
  const removeEntry = async () => {
    const remove = menu({
      name: 'extra.md',
      isFile: true,
      node: STRUCTURE['extra.md'],
    }).at(-1)!;
    await act(async () => remove.onClick(new Event('click')));
    const submit = Array.from(document.body.querySelectorAll('button')).find(
      (b) => b.textContent === 'settings.sources.website.remove',
    )!;
    await act(async () => submit.click());
  };

  const refused = (status: number, body: unknown) => ({
    ok: false,
    status,
    json: async () => body,
  });

  it('a remove closes the dialog and waits for its task in the header', async () => {
    service.removeWebsitePages.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, task_id: 'task-r' }),
    });
    await render();
    const controller = fakeController();
    captured.props!.controllerRef!.current = controller;
    await removeEntry();

    expect(document.body.textContent).not.toContain(
      'settings.sources.website.removeEntry',
    );
    expect(captured.props!.statusLabel).toBe(
      'settings.sources.website.removing',
    );
    const page = STRUCTURE['extra.md'];
    expect(
      menu({ name: 'extra.md', isFile: true, node: page }).at(-1)!.disabled,
    ).toBe(true);
    expect(controller.refreshDirectory).not.toHaveBeenCalled();

    service.getWebsite.mockClear();
    await act(async () => emitTerminal('completed', 'task-other'));
    expect(controller.refreshDirectory).not.toHaveBeenCalled();
    await act(async () => emitTerminal('completed', 'task-r'));
    expect(controller.refreshDirectory).toHaveBeenCalled();
    // The source's list of page entries is read again too.
    expect(service.getWebsite).toHaveBeenCalled();
    expect(captured.props!.statusLabel).toBeNull();
    expect(dispatch).not.toHaveBeenCalled();
    // The pages left keep their chunks; a removed open page closes itself.
    expect(controller.reloadFile).not.toHaveBeenCalled();
  });

  const startRefresh = async (taskId = 'task-1') => {
    const controller = fakeController();
    captured.props!.controllerRef!.current = controller;
    service.refreshWebsitePage.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, task_id: taskId }),
    });
    const page = STRUCTURE['extra.md'];
    const refresh = menu({ name: 'extra.md', isFile: true, node: page }).find(
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

  it('a change still running after the wait says so and reads the tree again', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      await render();
      const controller = await startRefresh();
      service.getWebsite.mockClear();
      await act(async () => {
        vi.advanceTimersByTime(5 * 60_000 + 1);
      });
      expect(captured.props!.statusLabel).toBeNull();
      expect(controller.refreshDirectory).toHaveBeenCalled();
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
    const controller = await startRefresh();
    await act(async () => emitTerminal('failed', 'task-1', { reason: 'busy' }));
    expect(controller.refreshDirectory).not.toHaveBeenCalled();
    expect(toasted()).toEqual([
      { variant: 'warning', message: 'settings.sources.website.changeBusy' },
    ]);
  });

  it.each([
    ['wiki', 'settings.sources.website.wikiSource'],
    ['gone', 'settings.sources.website.sourceGone'],
  ])(
    'a change skipped because the source is %s says so',
    async (reason, key) => {
      await render();
      await startRefresh();
      await act(async () => emitTerminal('failed', 'task-1', { reason }));
      expect(toasted()).toEqual([
        { variant: 'destructive', message: expect.stringMatching(`^${key}`) },
      ]);
    },
  );

  it('tells the host once a page change has finished', async () => {
    const onPagesChanged = vi.fn();
    await act(async () => {
      root.render(
        <WebsiteTree
          docId="src-1"
          sourceName="Docs"
          onBackToDocuments={() => undefined}
          hosts={['docs.x.io']}
          onPagesChanged={onPagesChanged}
        />,
      );
    });
    await startRefresh();
    expect(onPagesChanged).not.toHaveBeenCalled();
    await act(async () => emitTerminal('failed', 'task-1'));
    expect(onPagesChanged).not.toHaveBeenCalled();
    await startRefresh('task-2');
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
    [400, { code: 'wiki', error: 'wiki' }, 'wikiSource'],
    [400, { code: 'chunks_unsupported', error: 'no' }, 'chunksUnsupported'],
    [400, { code: 'last_entry', error: 'last' }, 'removeLast'],
  ])('a refused remove (%i %o) says why', async (status, body, key) => {
    service.removeWebsitePages.mockResolvedValue(refused(status, body));
    await render();
    await removeEntry();
    expect(document.body.textContent).toContain(
      `settings.sources.website.${key}`,
    );
    expect(document.body.textContent).not.toContain(
      'settings.sources.website.removeFailed',
    );
  });

  it("a remove refused without a code shows the server's message", async () => {
    service.removeWebsitePages.mockResolvedValue(
      refused(400, {
        success: false,
        error: 'The skip list holds up to 1000 rules',
      }),
    );
    await render();
    await removeEntry();
    expect(document.body.textContent).toContain(
      'The skip list holds up to 1000 rules',
    );
  });

  it('a remove that fails otherwise says it failed', async () => {
    service.removeWebsitePages.mockResolvedValue(
      refused(500, { success: false }),
    );
    await render();
    await removeEntry();
    expect(document.body.textContent).toContain(
      'settings.sources.website.removeFailed',
    );
  });

  it('a refused refresh toasts why', async () => {
    service.refreshWebsitePage.mockResolvedValue(
      refused(400, { code: 'chunks_unsupported', error: 'no' }),
    );
    await render();
    const refresh = menu({
      name: 'extra.md',
      isFile: true,
      node: STRUCTURE['extra.md'],
    }).find((o) => o.label === 'settings.sources.website.refreshPage')!;
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

  it('a refresh waits for its own task', async () => {
    await render();
    const controller = fakeController();
    captured.props!.controllerRef!.current = controller;
    service.refreshWebsitePage.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, task_id: 'task-1' }),
    });
    const refresh = menu({
      name: 'extra.md',
      isFile: true,
      node: STRUCTURE['extra.md'],
    }).find((o) => o.label === 'settings.sources.website.refreshPage')!;
    await act(async () => refresh.onClick(new Event('click')));

    await act(async () => emitTerminal('completed', 'task-other'));
    expect(controller.refreshDirectory).not.toHaveBeenCalled();
    await act(async () => emitTerminal('completed', 'task-1'));
    expect(controller.refreshDirectory).toHaveBeenCalled();
  });

  it("passes the source's menu to the title row", async () => {
    const headerMenu = <button type="button">source menu</button>;
    await act(async () => {
      root.render(
        <WebsiteTree
          docId="src-1"
          sourceName="Docs"
          onBackToDocuments={() => undefined}
          hosts={['docs.x.io']}
          headerMenu={headerMenu}
        />,
      );
    });
    expect(captured.props!.headerMenu).toBe(headerMenu);
  });

  it("embedded, it hands the host's header slot and crumbs to the tree", async () => {
    const target = document.createElement('div');
    const onCrumbsChange = vi.fn();
    await act(async () => {
      root.render(
        <WebsiteTree
          docId="src-1"
          sourceName="Docs"
          onBackToDocuments={() => undefined}
          hosts={['docs.x.io']}
          embedded
          actionsTarget={target}
          onCrumbsChange={onCrumbsChange}
          headerAction={<button type="button">Test retrieval</button>}
        />,
      );
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
    await act(async () => {
      root.render(
        <WebsiteTree
          docId="src-1"
          sourceName="Docs"
          onBackToDocuments={() => undefined}
          hosts={['docs.x.io']}
          graph
        />,
      );
    });
    const add = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('settings.sources.website.addPages'),
    )!;
    await act(async () => add.click());
    expect(document.body.textContent).toContain('add-pages-modal graph');
  });

  it('opens Add pages from the header', async () => {
    await render();
    const add = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('settings.sources.website.addPages'),
    )!;
    // A primary button is text only.
    expect(add.querySelector('svg')).toBeNull();
    await act(async () => add.click());
    expect(document.body.textContent).toContain('add-pages-modal');
  });

  it('warns that hand edits are replaced on a synced source', async () => {
    await render();
    expect(captured.props!.chunksNotice).toBeTruthy();
  });

  it('lists a refreshed page again once its refresh finishes', async () => {
    await render();
    const controller = fakeController();
    captured.props!.controllerRef!.current = controller;
    service.refreshWebsitePage.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, task_id: 'task-1' }),
    });
    const page = STRUCTURE['extra.md'];
    const refresh = menu({ name: 'extra.md', isFile: true, node: page }).find(
      (o) => o.label === 'settings.sources.website.refreshPage',
    )!;
    await act(async () => refresh.onClick(new Event('click')));
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

    await act(async () => emitTerminal());
    expect(controller.refreshDirectory).toHaveBeenCalled();
    expect(controller.reloadFile).toHaveBeenCalledWith('extra.md');
  });

  it('lists the open page again after added pages finish', async () => {
    await render();
    const controller = fakeController();
    captured.props!.controllerRef!.current = controller;
    const add = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('settings.sources.website.addPages'),
    )!;
    await act(async () => add.click());
    await act(async () =>
      captured.onQueued!(Date.now(), 'task-2', { mode: 'sync', urls: [] }),
    );
    await act(async () => emitTerminal());
    expect(controller.refreshDirectory).toHaveBeenCalled();
    expect(controller.reloadFile).toHaveBeenCalledWith();
  });

  it('after appended pages, lists the open page again only when it was one of them', async () => {
    await render();
    const controller = fakeController();
    captured.props!.controllerRef!.current = controller;
    const add = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('settings.sources.website.addPages'),
    )!;
    await act(async () => add.click());
    await act(async () =>
      captured.onQueued!(Date.now(), 'task-2', {
        mode: 'append',
        urls: ['https://docs.x.io/extra/', 'https://docs.x.io/new'],
      }),
    );
    await act(async () => emitTerminal());
    expect(controller.reloadFile).toHaveBeenCalledTimes(1);
    const affects = controller.reloadFile.mock.calls[0][0] as (
      path: string,
    ) => boolean;
    expect(affects('extra.md')).toBe(true);
    expect(affects('Deploying/Docker.md')).toBe(false);
  });

  it('turns the row changes off while a change runs', async () => {
    await render();
    captured.props!.controllerRef!.current = fakeController();
    service.refreshWebsitePage.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, task_id: 'task-1' }),
    });
    const page = STRUCTURE['extra.md'];
    const options = () => menu({ name: 'extra.md', isFile: true, node: page });
    const refresh = options().find(
      (o) => o.label === 'settings.sources.website.refreshPage',
    )!;
    await act(async () => refresh.onClick(new Event('click')));

    const byLabel = Object.fromEntries(
      options().map((o) => [o.label, !!o.disabled]),
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
    expect(options().some((o) => o.disabled)).toBe(false);
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
    return {
      text: document.body.textContent ?? '',
      submit: submit?.textContent,
    };
  };

  it('a page added by an address that redirected is still an entry', async () => {
    service.getWebsite.mockResolvedValue({
      ok: true,
      json: async () => ({
        config: {
          entries: [
            { url: 'https://docs.x.io/', mode: 'site' },
            { url: 'https://docs.x.io/old', mode: 'page' },
          ],
        },
      }),
    });
    await render();
    const { text, submit } = await askRemovePage('new.md', {
      type: 'text/markdown',
      url: 'https://docs.x.io/new',
      requested_url: 'https://docs.x.io/old/',
    });
    expect(text).toContain('settings.sources.website.removeEntry');
    expect(text).not.toContain('settings.sources.website.removeCrawled');
    expect(submit).toBe('settings.sources.website.remove');
  });

  it("says only what holds for any page until the source's list has loaded", async () => {
    let answer: (value: unknown) => void = () => undefined;
    service.getWebsite.mockReturnValue(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    await render();
    const { text, submit } = await askRemovePage(
      'extra.md',
      STRUCTURE['extra.md'],
    );
    expect(text).toContain('settings.sources.website.removeGeneric');
    expect(text).not.toContain('settings.sources.website.removeEntry');
    expect(text).not.toContain('settings.sources.website.removeCrawled');
    expect(submit).toBe('settings.sources.website.remove');

    // Once the list arrives, the open dialog says where the page came from.
    await act(async () =>
      answer({
        ok: true,
        json: async () => ({
          config: {
            entries: [{ url: 'https://docs.x.io/extra', mode: 'page' }],
          },
        }),
      }),
    );
    expect(document.body.textContent).toContain(
      'settings.sources.website.removeEntry',
    );
  });

  it.each([
    ['refused', () => ({ ok: false, status: 500, json: async () => ({}) })],
    [
      'broken',
      () => {
        throw new Error('offline');
      },
    ],
  ])(
    'keeps the copy that holds for any page when the list read is %s',
    async (_, reply) => {
      service.getWebsite.mockImplementation(async () => reply());
      await render();
      const { text, submit } = await askRemovePage(
        'Docker.md',
        STRUCTURE.Deploying['Docker.md'],
      );
      expect(text).toContain('settings.sources.website.removeGeneric');
      expect(text).not.toContain('settings.sources.website.removeCrawled');
      expect(submit).toBe('settings.sources.website.remove');
    },
  );

  it('after appended pages, an open page added under a redirected address counts too', async () => {
    await render();
    await act(async () => {
      captured.props!.onDirectoryDataLoaded!({
        directory_structure: {
          'new.md': {
            type: 'text/markdown',
            token_count: 1,
            url: 'https://docs.x.io/new',
            requested_url: 'https://docs.x.io/old',
          },
          'extra.md': STRUCTURE['extra.md'],
        },
      });
    });
    const controller = fakeController();
    captured.props!.controllerRef!.current = controller;
    const add = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('settings.sources.website.addPages'),
    )!;
    await act(async () => add.click());
    await act(async () =>
      captured.onQueued!(Date.now(), 'task-2', {
        mode: 'append',
        urls: ['https://docs.x.io/old'],
      }),
    );
    await act(async () => emitTerminal('completed', 'task-2'));
    const affects = controller.reloadFile.mock.calls[0][0] as (
      path: string,
    ) => boolean;
    expect(affects('new.md')).toBe(true);
    expect(affects('extra.md')).toBe(false);
  });

  describe('a sync the host started', () => {
    const renderSyncing = async (
      sync: { startedAt: number; taskId: string | null } | null,
      onPagesChanged = vi.fn(),
    ) => {
      await act(async () => {
        root.render(
          <WebsiteTree
            docId="src-1"
            sourceName="Docs"
            onBackToDocuments={() => undefined}
            hosts={['docs.x.io']}
            syncFrequency="weekly"
            sync={sync}
            onPagesChanged={onPagesChanged}
          />,
        );
      });
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
        menu({ name: 'extra.md', isFile: true, node: STRUCTURE['extra.md'] })
          .filter((o) => o.label !== 'view')
          .filter((o) => o.label !== 'settings.sources.website.openPage')
          .every((o) => o.disabled),
      ).toBe(true);

      await act(async () => emitTerminal('completed', 'task-other'));
      expect(controller.refreshDirectory).not.toHaveBeenCalled();
      await act(async () => emitTerminal('completed', 'task-s'));
      expect(controller.refreshDirectory).toHaveBeenCalled();
      // A sync may change any page, the open one too.
      expect(controller.reloadFile).toHaveBeenCalledWith();
      expect(onPagesChanged).toHaveBeenCalledTimes(1);
      expect(captured.props!.statusLabel).toBeNull();
      expect(container.textContent).toContain(
        'settings.sources.website.addPages',
      );
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
    expect(document.body.textContent).not.toContain(
      'settings.sources.website.removeEntry',
    );
    expect(toasted()).toEqual([
      { variant: 'warning', message: 'settings.sources.website.queueFailed' },
    ]);
    expect(captured.props!.statusLabel).toBeNull();
    // The list changed: it is read again.
    expect(service.getWebsite).toHaveBeenCalled();
  });

  it('a refresh saved but not queued warns instead of failing', async () => {
    service.refreshWebsitePage.mockResolvedValue(refused(500, QUEUE_FAILED));
    await render();
    const refresh = menu({
      name: 'extra.md',
      isFile: true,
      node: STRUCTURE['extra.md'],
    }).find((o) => o.label === 'settings.sources.website.refreshPage')!;
    await act(async () => refresh.onClick(new Event('click')));
    expect(toasted()).toEqual([
      { variant: 'warning', message: 'settings.sources.website.queueFailed' },
    ]);
    expect(captured.props!.statusLabel).toBeNull();
  });

  it('pages saved but not queued warn and read the list again', async () => {
    await render();
    const add = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('settings.sources.website.addPages'),
    )!;
    await act(async () => add.click());
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

  it("links the source's first address by its own origin", async () => {
    service.getWebsite.mockResolvedValue({
      ok: true,
      json: async () => ({
        config: {
          entries: [{ url: 'http://docs.x.io:8080/guide/', mode: 'site' }],
        },
      }),
    });
    await render();
    const byline = document.createElement('div');
    const bylineRoot = createRoot(byline);
    await act(async () =>
      bylineRoot.render(
        <>{captured.props!.renderByline!({ files: 1, tokens: 1 })}</>,
      ),
    );
    expect(byline.querySelector('a')?.getAttribute('href')).toBe(
      'http://docs.x.io:8080',
    );
    act(() => bylineRoot.unmount());
  });
});
