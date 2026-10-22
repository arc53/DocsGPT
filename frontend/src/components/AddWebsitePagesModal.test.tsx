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

// The form is covered on its own; here it only needs to hold one address.
vi.mock('../upload/WebsiteFields', () => ({
  default: ({
    draft,
    onChange,
  }: {
    draft: WebsiteDraft;
    onChange: (draft: WebsiteDraft) => void;
  }) => (
    <button
      type="button"
      onClick={() => onChange({ ...draft, urls: ['https://docs.x.io/new'] })}
    >
      fill
    </button>
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

  const submit = async () => {
    await act(async () => {
      root.render(
        <AddWebsitePagesModal
          sourceId="src-1"
          sourceName="Docs"
          onClose={onClose}
          onQueued={onQueued}
        />,
      );
    });
    const buttons = () => Array.from(document.body.querySelectorAll('button'));
    await act(async () =>
      buttons()
        .find((b) => b.textContent === 'fill')!
        .click(),
    );
    await act(async () =>
      buttons()
        .find((b) => b.textContent === 'settings.sources.website.addPages')!
        .click(),
    );
  };

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
