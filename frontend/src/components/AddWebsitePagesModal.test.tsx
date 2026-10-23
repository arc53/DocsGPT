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

  const open = () =>
    act(async () => {
      root.render(
        <AddWebsitePagesModal
          sourceId="src-1"
          sourceName="Docs"
          onClose={onClose}
          onQueued={onQueued}
        />,
      );
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

  it("starts a site's page limit at the admin's default once config answers", async () => {
    service.getConfig.mockResolvedValue(
      reply(200, { web_default_pages: 20, web_max_pages: 50 }),
    );
    service.addWebsitePages.mockResolvedValue(
      reply(200, { success: true, mode: 'sync', task_id: 'task-9' }),
    );
    await submit('fill site');

    expect(sentEntries()[0].max_pages).toBe(20);
    expect(onQueued).toHaveBeenCalledWith(expect.any(Number), 'task-9');
  });

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

  it('queues the pages and closes', async () => {
    service.addWebsitePages.mockResolvedValue(
      reply(200, { success: true, mode: 'append' }),
    );
    await submit();

    expect(service.addWebsitePages).toHaveBeenCalledWith(
      {
        source_id: 'src-1',
        entries: [{ url: 'https://docs.x.io/new', mode: 'page' }],
      },
      'token',
    );
    expect(onQueued).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('says how many pages a source can hold when it is full', async () => {
    service.addWebsitePages.mockResolvedValue(
      reply(400, { success: false, code: 'page_limit', max_pages: 100 }),
    );
    await submit();

    expect(document.body.textContent).toContain(
      'settings.sources.website.pageLimit {"count":100}',
    );
    expect(onClose).not.toHaveBeenCalled();
  });
});
