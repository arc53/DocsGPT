import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && key === 'settings.sources.wiki.byline'
        ? `${opts.pages} pages · ${opts.tokens} tokens`
        : key,
  }),
}));

const auth = vi.hoisted(() => ({ token: null as string | null }));

vi.mock('react-redux', () => ({
  useSelector: () => auth.token,
  useDispatch: () => vi.fn(),
}));

vi.mock('../hooks', () => ({
  useDarkTheme: () => [false],
  useDebouncedValue: (value: unknown) => value,
  useLoaderState: (initial: boolean) => useState(initial),
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
  useOutsideAlerter: () => undefined,
}));

const PAGES = [
  { path: 'company/meeting-types.md', title: null, token_count: 1000 },
  { path: 'index.md', title: null, token_count: 200 },
  { path: 'company/async_by-default.md', title: null, token_count: 34 },
];

const ok = (body: unknown) => ({
  ok: true,
  status: 200,
  json: async () => body,
});

vi.mock('../api/services/userService', () => ({
  default: {
    getWikiPages: vi.fn(),
    getWikiPage: vi.fn(),
    updateWikiPage: vi.fn(),
  },
}));

import i18next from 'i18next';

import userService from '../api/services/userService';
import { TooltipProvider } from './ui/tooltip';
import WikiViewer from './WikiViewer';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const service = userService as unknown as {
  getWikiPages: ReturnType<typeof vi.fn>;
  getWikiPage: ReturnType<typeof vi.fn>;
  updateWikiPage: ReturnType<typeof vi.fn>;
};

describe('WikiViewer', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    auth.token = null;
    service.getWikiPages.mockReset();
    service.getWikiPage.mockReset();
    service.updateWikiPage.mockReset();
    service.getWikiPages.mockResolvedValue(ok({ pages: PAGES }));
    service.getWikiPage.mockImplementation(async (_id: string, path: string) =>
      ok({ page: { path, content: '# Hello\n\nBody text', version: 1 } }),
    );
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = async (canEdit = false, initialPath?: string) => {
    await act(async () => {
      root.render(
        <TooltipProvider>
          <WikiViewer
            docId="doc"
            sourceName="Handbook"
            canEdit={canEdit}
            onBackToDocuments={vi.fn()}
            initialPath={initialPath}
          />
        </TooltipProvider>,
      );
    });
  };

  const buttonByText = (text: string) =>
    Array.from(document.body.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === text,
    );

  const sheet = () =>
    document.body.querySelector<HTMLElement>('[data-slot="sheet-content"]');

  const editor = () =>
    sheet()?.querySelector<HTMLTextAreaElement>('textarea') ?? null;

  const typeDraft = async (value: string) => {
    const field = editor()!;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      'value',
    )!.set!;
    await act(async () => {
      setter.call(field, value);
      field.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };

  const openEditor = async () => {
    await act(async () => buttonByText('settings.sources.wiki.edit')!.click());
  };

  const save = async () => {
    await act(async () => buttonByText('settings.sources.wiki.save')!.click());
  };

  // Bugs row 8: the app language's separators, not the browser's.
  it('formats the byline counts in the app language', async () => {
    const language = i18next.language;
    i18next.language = 'de';
    try {
      await render();
      expect(container.textContent).toContain('3 pages · 1.234 tokens');
    } finally {
      i18next.language = language;
    }
  });

  it('renders the living wiki badge and the page and token counts', async () => {
    await render();
    const text = container.textContent ?? '';
    expect(text).toContain('Handbook');
    expect(text).toContain('settings.sources.wiki.badge');
    expect(text).toContain(
      `3 pages · ${(1234).toLocaleString()} tokens · settings.sources.wiki.explainer`,
    );
    expect(text).not.toContain('settings.sources.wiki.livingTitle');
  });

  it('uses the editable explainer when the wiki can be edited', async () => {
    await render(true);
    expect(container.textContent).toContain(
      'settings.sources.wiki.explainerEditable',
    );
  });

  it('groups pages under their folder with readable labels', async () => {
    await render();
    const nav = container.querySelector(
      'nav[aria-label="settings.sources.wiki.pagesTitle"]',
    )!;
    const text = nav.textContent ?? '';
    expect(text).toContain('settings.sources.wiki.home');
    expect(text).toContain('company');
    expect(text).toContain('Meeting types');
    expect(text).toContain('Async by default');
    // The home page leads, before the folder group.
    expect(text.indexOf('settings.sources.wiki.home')).toBeLessThan(
      text.indexOf('company'),
    );
    // The first page in the list opens, its path in the reader meta.
    expect(service.getWikiPage).toHaveBeenCalledWith(
      'doc',
      'company/meeting-types.md',
      null,
    );
    expect(container.textContent).toContain('Body text');
  });

  it('opens the page a citation names instead of the first one', async () => {
    await render(false, '/company/async_by-default.md');
    expect(service.getWikiPage).toHaveBeenLastCalledWith(
      'doc',
      'company/async_by-default.md',
      null,
    );
  });

  it('opens the first page when the cited one is gone', async () => {
    await render(false, 'company/removed.md');
    expect(service.getWikiPage.mock.calls.at(-1)?.[1]).toBe(PAGES[0].path);
  });

  it('hides Edit without canEdit', async () => {
    await render(false);
    expect(buttonByText('settings.sources.wiki.edit')).toBeUndefined();
    expect(sheet()).toBeNull();
  });

  // The chunk reader's actions: Edit, then the toolbar ⋯ with Copy text. A
  // viewer who can't edit still gets the menu.
  it('puts a toolbar ⋯ menu after Edit, for editors and viewers alike', async () => {
    const menu = () =>
      container.querySelector<HTMLButtonElement>(
        'button[aria-label="settings.sources.menuAlt"]',
      );
    await render(true);
    const edit = buttonByText('settings.sources.wiki.edit')!;
    expect(menu()).not.toBeNull();
    expect(
      edit.compareDocumentPosition(menu()!) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    await render(false);
    expect(menu()).not.toBeNull();
  });

  it('renders the page body as markdown through SourceMarkdown, tables included', async () => {
    service.getWikiPage.mockImplementation(async (_id: string, path: string) =>
      ok({
        page: {
          path,
          content: '# Hello\n\n| Name | Role |\n| --- | --- |\n| Ana | Lead |',
          version: 1,
        },
      }),
    );
    await render();
    const table = container.querySelector('table');
    expect(table).not.toBeNull();
    expect(table?.textContent).toContain('Ana');
    expect(container.querySelector('h1, h2, h3')?.textContent).toBe('Hello');
    expect(container.querySelector('textarea')).toBeNull();
  });

  it('opens the edit drawer with the page content as the draft', async () => {
    await render(true);
    expect(sheet()).toBeNull();
    await openEditor();
    expect(sheet()).not.toBeNull();
    expect(sheet()!.textContent).toContain('settings.sources.wiki.editTitle');
    expect(sheet()!.textContent).toContain('company/meeting-types.md');
    expect(editor()?.value).toBe('# Hello\n\nBody text');
    // The path is the drawer's description; the field is named by a label.
    expect(editor()?.getAttribute('aria-label')).toBe('modals.chunk.bodyText');
    // The panel itself never swaps to an editor.
    expect(container.querySelector('textarea')).toBeNull();
  });

  it('closes the drawer and shows the new content when the save succeeds', async () => {
    service.updateWikiPage.mockResolvedValue(
      ok({
        page: {
          path: 'company/meeting-types.md',
          content: '# Hello\n\nNew body',
          version: 2,
        },
      }),
    );
    await render(true);
    await openEditor();
    await typeDraft('# Hello\n\nNew body');
    await save();
    expect(service.updateWikiPage).toHaveBeenCalled();
    expect(sheet()).toBeNull();
    expect(container.textContent).toContain('New body');
    expect(container.textContent).not.toContain('Body text');
  });

  it('a token refresh keeps the open drawer and its draft', async () => {
    auth.token = 'old';
    await render(true);
    await openEditor();
    await typeDraft('# Hello\n\nHalf-written');
    service.getWikiPages.mockClear();
    service.getWikiPage.mockClear();
    // SSE 401 recovery dispatches a fresh token for the same user.
    auth.token = 'new';
    await render(true);
    expect(sheet()).not.toBeNull();
    expect(editor()?.value).toBe('# Hello\n\nHalf-written');
    expect(service.getWikiPage).not.toHaveBeenCalled();
    expect(service.getWikiPages).not.toHaveBeenCalled();
    // Later requests carry the fresh token.
    service.updateWikiPage.mockResolvedValue(ok({ page: null }));
    await save();
    expect(service.updateWikiPage.mock.calls[0]).toContain('new');
  });

  it('a saved page updates the byline token total', async () => {
    service.updateWikiPage.mockResolvedValue(
      ok({
        page: {
          path: 'company/meeting-types.md',
          content: '# Hello\n\nLonger body',
          token_count: 1500,
          version: 2,
        },
      }),
    );
    await render(true);
    await openEditor();
    await typeDraft('# Hello\n\nLonger body');
    await save();
    expect(container.textContent).toContain(
      `3 pages · ${(1734).toLocaleString()} tokens`,
    );
  });

  it('keeps the drawer open with a warning and the draft when the save conflicts', async () => {
    service.updateWikiPage.mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({}),
    });
    await render(true);
    await openEditor();
    await typeDraft('My edit');
    await save();
    expect(sheet()).not.toBeNull();
    const alert = sheet()!.querySelector('[data-slot="alert"]');
    expect(alert?.getAttribute('data-variant')).toBe('warning');
    expect(alert?.textContent).toContain('settings.sources.wiki.conflict');
    expect(editor()?.value).toBe('My edit');
  });

  it('shows a destructive Alert in the drawer when the save is forbidden', async () => {
    service.updateWikiPage.mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({}),
    });
    await render(true);
    await openEditor();
    await typeDraft('My edit');
    await save();
    expect(sheet()).not.toBeNull();
    const alert = sheet()!.querySelector('[data-slot="alert"]');
    expect(alert?.getAttribute('data-variant')).toBe('destructive');
    expect(alert?.textContent).toContain('settings.sources.wiki.forbidden');
    expect(editor()?.value).toBe('My edit');
  });

  // PATTERNS.md › Source views: the navigator shows only when there is more
  // than one thing to open; a one-page wiki reads full width, like a
  // one-file source.
  it('hides the navigator for a one-page wiki and opens that page', async () => {
    service.getWikiPages.mockResolvedValue(
      ok({ pages: [{ path: 'index.md', title: null, token_count: 5 }] }),
    );
    await render();
    expect(
      container.querySelector(
        'nav[aria-label="settings.sources.wiki.pagesTitle"]',
      ),
    ).toBeNull();
    expect(service.getWikiPage).toHaveBeenCalledWith('doc', 'index.md', null);
    expect(container.textContent).toContain('index.md');
    expect(container.textContent).toContain('Body text');
  });

  it('shows the empty state when the wiki has no pages', async () => {
    service.getWikiPages.mockResolvedValue(ok({ pages: [] }));
    await render();
    expect(container.textContent).toContain('settings.sources.wiki.empty');
    expect(
      container.querySelector(
        'nav[aria-label="settings.sources.wiki.pagesTitle"]',
      ),
    ).toBeNull();
  });

  it('offers Retry when the pages fail to load', async () => {
    service.getWikiPages.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({}),
    });
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    await render();
    expect(container.textContent).toContain('settings.sources.wiki.loadFailed');
    await act(async () => buttonByText('retry')!.click());
    expect(service.getWikiPages).toHaveBeenCalledTimes(2);
    expect(
      container.querySelector(
        'nav[aria-label="settings.sources.wiki.pagesTitle"]',
      ),
    ).not.toBeNull();
    spy.mockRestore();
  });

  // Bug: a failed page switch kept the previous page's "Edited by · vN".
  it("drops the previous page's stamp when the next page fails to load", async () => {
    service.getWikiPage.mockImplementation(async (_id: string, path: string) =>
      path === 'index.md'
        ? { ok: false, status: 500, json: async () => ({}) }
        : ok({ page: { path, content: 'Body text', version: 3 } }),
    );
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    await render();
    expect(container.textContent).toContain(
      'settings.sources.wiki.stamp.editedBy',
    );
    const home = Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="command-item"]'),
    ).find((el) => el.textContent?.includes('settings.sources.wiki.home'))!;
    await act(async () => home.click());
    expect(container.textContent).toContain(
      'settings.sources.wiki.pageLoadFailed',
    );
    expect(container.textContent).not.toContain(
      'settings.sources.wiki.stamp.editedBy',
    );
    expect(container.textContent).not.toContain('Body text');
    spy.mockRestore();
  });
});
