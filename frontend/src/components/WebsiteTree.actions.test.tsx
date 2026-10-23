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
    onQueued: null as ((startedAt: number, taskId?: string) => void) | null,
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
    onQueued: (startedAt: number, taskId?: string) => void;
  }) => {
    captured.onQueued = props.onQueued;
    return <div>add-pages-modal</div>;
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
) => {
  bus.events = [
    {
      id: `${Date.now()}-${bus.events.length}`,
      type: `source.ingest.${type}`,
      ts: new Date().toISOString(),
      scope: { kind: 'source', id: 'src-1' },
      payload: taskId ? { task_id: taskId } : {},
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

  it.each([
    [409, { code: 'source_busy', error: 'busy' }, 'sourceBusy'],
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
    expect(service.refreshWebsitePage).toHaveBeenCalledWith(
      { source_id: 'src-1', file_path: 'extra.md' },
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
    await act(async () => captured.onQueued!(Date.now(), 'task-2'));
    await act(async () => emitTerminal());
    expect(controller.refreshDirectory).toHaveBeenCalled();
    expect(controller.reloadFile).toHaveBeenCalledWith();
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
