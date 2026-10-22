import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { TreeBrowserProps } from './tree/TreeBrowser';
import type { RowMenuContext } from './tree/types';
import type { MenuOption } from './ui/dropdown-menu';

const { captured, service } = vi.hoisted(() => ({
  captured: { props: null as TreeBrowserProps | null },
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

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
  useDispatch: () => vi.fn(),
  useStore: () => ({
    getState: () => ({ notifications: { recentEvents: [] } }),
    subscribe: () => () => undefined,
  }),
}));

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
  default: () => <div>add-pages-modal</div>,
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

describe('WebsiteTree page management', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
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
      'settings.sources.website.removeCrawled {"host":"docs.x.io"}',
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
      'settings.sources.website.removeFolder {"address":"docs.x.io/Deploying/"}',
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

  it('opens Add pages from the header', async () => {
    await render();
    const add = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('settings.sources.website.addPages'),
    )!;
    await act(async () => add.click());
    expect(document.body.textContent).toContain('add-pages-modal');
  });

  it('warns that hand edits are replaced on a synced source', async () => {
    await render();
    expect(captured.props!.chunksNotice).toBeTruthy();
  });
});
