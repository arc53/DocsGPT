import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { WebsiteDraft } from '../upload/website';

const { service } = vi.hoisted(() => ({
  service: { addWebsitePages: vi.fn(), getConfig: vi.fn() },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key} ${JSON.stringify(opts)}` : key,
  }),
}));

vi.mock('react-redux', () => ({ useSelector: () => 'token' }));

vi.mock('../api/services/userService', () => ({ default: service }));

// The form is covered on its own; here it only needs to hold an address,
// or a whole site with the page limit it shows or one the user typed.
vi.mock('../upload/WebsiteFields', () => ({
  default: ({
    draft,
    onChange,
  }: {
    draft: WebsiteDraft;
    onChange: (draft: WebsiteDraft) => void;
  }) => (
    <>
      <button
        type="button"
        onClick={() => onChange({ ...draft, urls: ['https://docs.x.io/new'] })}
      >
        fill
      </button>
      <button
        type="button"
        onClick={() =>
          onChange({ ...draft, mode: 'site', urls: ['https://docs.x.io/'] })
        }
      >
        fill site
      </button>
      <button
        type="button"
        onClick={() => onChange({ ...draft, maxPages: 30 })}
      >
        type 30
      </button>
    </>
  ),
}));

import AddWebsitePagesModal from './AddWebsitePagesModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const reply = (status: number, body: unknown) => ({
  ok: status < 400,
  status,
  json: async () => body,
});

describe('AddWebsitePagesModal', () => {
  let container: HTMLDivElement;
  let root: Root;
  const onQueued = vi.fn();
  const onQueueFailed = vi.fn();
  const onClose = vi.fn();

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    service.getConfig.mockResolvedValue(reply(200, {}));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.clearAllMocks();
  });

  const buttons = () => Array.from(document.body.querySelectorAll('button'));
  const click = (label: string) =>
    act(async () =>
      buttons()
        .find((b) => b.textContent === label)!
        .click(),
    );

  const open = (graph?: boolean) =>
    act(async () => {
      root.render(
        <AddWebsitePagesModal
          sourceId="src-1"
          sourceName="Docs"
          graph={graph}
          onClose={onClose}
          onQueued={onQueued}
          onQueueFailed={onQueueFailed}
        />,
      );
    });

  it("says a graph source's new pages are extracted with an LLM", async () => {
    await open(true);
    const note = document.body.querySelector('[role="note"]');
    expect(note?.textContent).toBe('settings.sources.website.graphCost');
    expect(note?.getAttribute('data-variant')).toBe('info');

    await open(false);
    expect(document.body.textContent).not.toContain(
      'settings.sources.website.graphCost',
    );
  });

  it('says a whole site rebuilds the graph of the whole source', async () => {
    await open(true);
    await click('fill site');
    const note = document.body.querySelector('[role="note"]');
    expect(note?.textContent).toBe('settings.sources.website.graphCostRebuild');
  });

  const submit = async (fill = 'fill') => {
    await open();
    await click(fill);
    await click('settings.sources.website.addPages');
  };

  const sentEntries = () =>
    service.addWebsitePages.mock.calls.at(-1)![0].entries as Record<
      string,
      unknown
    >[];

  it.each([
    [{ web_default_pages: 20, web_max_pages: 50 }, 20],
    // WEB_MAX_PAGES set below WEB_DEFAULT_PAGES: the form still opens valid.
    [{ web_default_pages: 200, web_max_pages: 50 }, 50],
  ])(
    "starts a site's page limit at the admin's default (%o), within the cap",
    async (config, sent) => {
      service.getConfig.mockResolvedValue(reply(200, config));
      service.addWebsitePages.mockResolvedValue(
        reply(200, { success: true, mode: 'sync', task_id: 'task-9' }),
      );
      await submit('fill site');

      expect(sentEntries()[0].max_pages).toBe(sent);
      expect(onQueued).toHaveBeenCalledWith(expect.any(Number), 'task-9');
    },
  );

  it('keeps a page limit the user typed before config answered', async () => {
    let answer: (value: unknown) => void = () => undefined;
    service.getConfig.mockReturnValue(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    service.addWebsitePages.mockResolvedValue(
      reply(200, { success: true, mode: 'sync' }),
    );
    await open();
    await click('fill site');
    await click('type 30');
    await act(async () =>
      answer(reply(200, { web_default_pages: 20, web_max_pages: 50 })),
    );
    await click('settings.sources.website.addPages');

    expect(sentEntries()[0].max_pages).toBe(30);
  });

  // `sync`: the server rebuilds the source instead; its task ends the wait
  // the same way.
  it.each(['append', 'sync'])(
    'queues the pages and closes (%s)',
    async (mode) => {
      service.addWebsitePages.mockResolvedValue(
        reply(200, { success: true, mode, task_id: 'task-3' }),
      );
      await submit();

      expect(service.addWebsitePages).toHaveBeenCalledWith(
        {
          source_id: 'src-1',
          entries: [{ url: 'https://docs.x.io/new', mode: 'page' }],
        },
        'token',
      );
      expect(onQueued).toHaveBeenCalledWith(expect.any(Number), 'task-3');
      expect(onClose).toHaveBeenCalled();
    },
  );

  it.each([
    [
      400,
      { success: false, code: 'page_limit', max_pages: 100 },
      'settings.sources.website.pageLimit {"count":100}',
    ],
    [
      400,
      { success: false, code: 'wiki', error: 'A wiki…' },
      'settings.sources.website.wikiSource',
    ],
    [
      400,
      {
        success: false,
        code: 'already_listed',
        error: 'These pages and sites are already in this source.',
      },
      'settings.sources.website.alreadyListed',
    ],
    // A refusal without a code: the server's own message.
    [
      400,
      { success: false, error: 'A source holds up to 20 sites' },
      'A source holds up to 20 sites',
    ],
    // A server error: never its message.
    [
      500,
      { success: false, error: 'Traceback' },
      'settings.sources.website.addFailed',
    ],
  ])(
    'keeps the dialog open on a refusal (%i %o) and says why',
    async (status, body, shown) => {
      service.addWebsitePages.mockResolvedValue(reply(status, body));
      await submit();

      expect(document.body.textContent).toContain(shown);
      expect(document.body.textContent).not.toContain('Traceback');
      expect(onQueued).not.toHaveBeenCalled();
      expect(onClose).not.toHaveBeenCalled();
    },
  );

  it('pages saved but not queued close the dialog with a warning, in its own words', async () => {
    service.addWebsitePages.mockResolvedValue(
      reply(500, {
        success: false,
        code: 'queue_failed',
        message:
          "The change was saved, but its task couldn't be queued; the next sync picks it up.",
      }),
    );
    await submit();

    expect(onQueueFailed).toHaveBeenCalledWith(
      'settings.sources.website.queueFailed',
    );
    expect(onQueued).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
    expect(document.body.textContent).not.toContain(
      'settings.sources.website.addFailed',
    );
  });

  it('keeps the dialog open while the add is in flight: Cancel and Esc wait for it', async () => {
    let resolve!: (value: unknown) => void;
    service.addWebsitePages.mockReturnValue(new Promise((r) => (resolve = r)));
    await submit();
    const cancel = buttons().find((b) => b.textContent === 'cancel')!;
    expect(cancel.disabled).toBe(true);
    await act(async () => {
      (document.activeElement ?? document.body).dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }),
      );
    });
    expect(onClose).not.toHaveBeenCalled();

    // A refusal still lands in the open dialog.
    await act(async () =>
      resolve(
        reply(400, { success: false, code: 'page_limit', max_pages: 100 }),
      ),
    );
    expect(document.body.textContent).toContain(
      'settings.sources.website.pageLimit {"count":100}',
    );
    expect(onQueued).not.toHaveBeenCalled();
    expect(buttons().find((b) => b.textContent === 'cancel')!.disabled).toBe(
      false,
    );
  });
});
