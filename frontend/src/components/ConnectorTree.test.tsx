import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { tree } = vi.hoisted(() => ({
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
  useDispatch: () => vi.fn(),
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
    getDocumentChunks: vi.fn(async () => ({
      ok: true,
      json: async () => ({ page: 1, per_page: 12, total: 0, chunks: [] }),
    })),
  },
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

  const badge = () => container.querySelector('[data-slot="badge"]');
  const retrieval = <button type="button">retrieval</button>;

  it('ConnectorTree shows the provider badge, headerAction and Sync', async () => {
    await render(
      <ConnectorTree
        docId="doc"
        sourceName="Drive"
        onBackToDocuments={vi.fn()}
        headerAction={retrieval}
      />,
    );
    expect(badge()!.textContent).toBe('Google Drive');
    expect(badge()!.getAttribute('data-variant')).toBe('neutral');
    expect(container.textContent).toContain('retrieval');
    expect(container.textContent).toContain('settings.sources.sync');
  });

  it('embedded ConnectorTree drops the badge and headerAction, keeps Sync', async () => {
    await render(
      <ConnectorTree
        embedded
        docId="doc"
        sourceName="Drive"
        onBackToDocuments={vi.fn()}
        headerAction={retrieval}
      />,
    );
    expect(badge()).toBeNull();
    expect(container.textContent).not.toContain('retrieval');
    expect(container.textContent).toContain('settings.sources.sync');
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
    await render(
      <ConnectorTree
        docId="doc"
        sourceName="Drive"
        onBackToDocuments={vi.fn()}
        initialPath="b.docx"
      />,
    );
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

  it('read-only ConnectorTree hides Sync, keeps headerAction', async () => {
    await render(
      <ConnectorTree
        docId="doc"
        sourceName="Drive"
        onBackToDocuments={vi.fn()}
        headerAction={retrieval}
        canEdit={false}
      />,
    );
    expect(container.textContent).toContain('retrieval');
    expect(container.textContent).not.toContain('settings.sources.sync');
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
