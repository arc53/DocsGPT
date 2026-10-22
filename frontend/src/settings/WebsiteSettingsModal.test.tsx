import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { service } = vi.hoisted(() => ({
  service: { getWebsite: vi.fn(), saveWebsite: vi.fn() },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key} ${JSON.stringify(opts)}` : key,
  }),
}));

vi.mock('react-redux', () => ({ useSelector: () => 'token' }));

vi.mock('../api/services/userService', () => ({ default: service }));

import WebsiteSettingsModal from './WebsiteSettingsModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const CONFIG = {
  entries: [
    {
      url: 'https://docs.x.io/',
      mode: 'site',
      max_pages: 100,
      discovery: 'auto',
    },
    { url: 'https://github.com/a/b', mode: 'page' },
  ],
  skip: ['https://docs.x.io/changelog', 'https://docs.x.io/Deploying/*'],
  keep_links: false,
};

describe('WebsiteSettingsModal', () => {
  let container: HTMLDivElement;
  let root: Root;
  const onSaved = vi.fn();
  const onClose = vi.fn();

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    service.getWebsite.mockResolvedValue({
      ok: true,
      json: async () => ({
        config: CONFIG,
        sync_frequency: 'weekly',
        report: {
          sites: [{ url: 'https://docs.x.io/', limit_reached: true }],
        },
      }),
    });
    service.saveWebsite.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.clearAllMocks();
  });

  const render = async () => {
    await act(async () => {
      root.render(
        <WebsiteSettingsModal
          document={{ id: 'src-1', name: 'Docs', date: '', model: '' }}
          onClose={onClose}
          onSaved={onSaved}
          onSyncNow={vi.fn()}
        />,
      );
    });
  };
  const buttons = () => Array.from(document.body.querySelectorAll('button'));

  it('lists what the source fetches and what it skips', async () => {
    await render();
    const text = document.body.textContent ?? '';

    expect(text).toContain('docs.x.io');
    expect(text).toContain('github.com/a/b');
    expect(text).toContain('settings.sources.website.limitReached');
    expect(text).toContain('docs.x.io/changelog');
    expect(text).toContain('docs.x.io/Deploying/*');
  });

  it('saves removed entries, restored skips and the schedule', async () => {
    await render();
    const removeEntry = buttons().filter(
      (b) =>
        b.getAttribute('aria-label') ===
        'settings.sources.website.removeFromList',
    );
    await act(async () => removeEntry[1].click());
    // The last entry left can't be removed.
    expect(
      buttons()
        .filter(
          (b) =>
            b.getAttribute('aria-label') ===
            'settings.sources.website.removeFromList',
        )
        .every((b) => b.disabled),
    ).toBe(true);
    const restore = buttons().find(
      (b) => b.textContent === 'settings.sources.website.restore',
    )!;
    await act(async () => restore.click());
    const save = buttons().find(
      (b) => b.textContent === 'settings.sources.website.save',
    )!;
    await act(async () => save.click());

    expect(service.saveWebsite).toHaveBeenCalledWith(
      {
        source_id: 'src-1',
        entries: [CONFIG.entries[0]],
        skip: ['https://docs.x.io/Deploying/*'],
        keep_links: false,
        sync_frequency: 'weekly',
      },
      'token',
    );
    expect(onSaved).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});
