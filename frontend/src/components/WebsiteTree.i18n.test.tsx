import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { TreeBrowserProps } from './tree/TreeBrowser';
import type { MenuOption } from './ui/dropdown-menu';

const { captured } = vi.hoisted(() => ({
  captured: { props: null as TreeBrowserProps | null },
}));

vi.mock('react-redux', () => {
  const store = {
    getState: () => ({ notifications: { recentEvents: [] } }),
    subscribe: () => () => undefined,
  };
  return {
    useSelector: () => 'token',
    useDispatch: () => vi.fn(),
    useStore: () => store,
  };
});

vi.mock('../api/services/userService', () => ({
  default: {
    getWebsite: vi.fn(async () => ({
      ok: true,
      json: async () => ({
        config: { entries: [{ url: 'https://docs.x.io/', mode: 'site' }] },
        entry_paths: [],
      }),
    })),
  },
}));

vi.mock('./tree/TreeBrowser', () => ({
  default: (props: TreeBrowserProps) => {
    captured.props = props;
    return <div>{props.extraContent}</div>;
  },
}));

import i18n from '../locale/i18n';
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
};

// With the real i18next (escaping on), an address must reach the screen
// with its slashes, not as `&#x2F;`.
describe('WebsiteTree remove copy', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    await i18n.changeLanguage('en');
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const askRemove = async (name: string, isFile: boolean) => {
    await act(async () => {
      root.render(
        <WebsiteTree
          docId="src-1"
          sourceName="Docs"
          onBackToDocuments={() => undefined}
          hosts={['docs.x.io']}
        />,
      );
    });
    await act(async () => {
      captured.props!.onDirectoryDataLoaded!({
        directory_structure: STRUCTURE,
      });
    });
    if (isFile) captured.props!.onCurrentPathChange!(['Deploying']);
    const view: MenuOption = { label: 'view', onClick: vi.fn() };
    const remove = captured.props!.getRowMenuOptions!({
      defaultViewOption: view,
      name,
      isFile,
      itemId: 'row',
      node: isFile ? STRUCTURE.Deploying['Docker.md'] : undefined,
    }).at(-1)!;
    await act(async () => remove.onClick(new Event('click')));
  };

  it("shows a folder's address with its slashes", async () => {
    await askRemove('Deploying', false);
    expect(document.body.textContent).toContain('under docs.x.io/Deploying/.');
    expect(document.body.textContent).not.toContain('&#x2F;');
  });

  it("shows a crawled page's host as is", async () => {
    await askRemove('Docker.md', true);
    expect(document.body.textContent).toContain('crawling docs.x.io.');
  });
});
