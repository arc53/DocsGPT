import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // A row's address is part of its buttons' names.
    t: (key: string, opts?: { address?: string }) =>
      opts?.address ? `${key} ${opts.address}` : key,
  }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => null,
  useDispatch: () => vi.fn(),
}));

const { updateSourceConfig, service } = vi.hoisted(() => {
  const updateSourceConfig = vi.fn();
  return {
    updateSourceConfig,
    service: {
      updateSourceConfig,
      manageSync: vi.fn(),
      getWebsite: vi.fn(),
      saveWebsite: vi.fn(),
    },
  };
});
vi.mock('../api/services/userService', () => ({ default: service }));

import type { Doc } from '../models/misc';
import type { DecisionFeatures } from './components/RetrievalOptions';
import SourceConfigModal from './SourceConfigModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const doc = (fields: Partial<Doc>): Doc => ({
  id: 'src-1',
  name: 'Contracts',
  date: '',
  model: '',
  ...fields,
});

describe('SourceConfigModal access', () => {
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
    document.body.innerHTML = '';
  });

  const render = async (document: Doc, decision?: DecisionFeatures) => {
    await act(async () => {
      root.render(
        <SourceConfigModal
          modalState="ACTIVE"
          setModalState={vi.fn()}
          document={document}
          onReingest={vi.fn()}
          onEnableGraphRAG={vi.fn()}
          decision={decision}
        />,
      );
    });
  };

  const readOnlyNotice = () =>
    document.body.textContent?.includes('common.viewOnlyNotice');

  const buttonLabels = () =>
    Array.from(document.body.querySelectorAll('button')).map(
      (b) => b.textContent,
    );

  it('a viewer with view_config only sees the read-only notice', async () => {
    await render(
      doc({
        access: 'viewer',
        ownership: 'team',
        team_access: 'viewer',
        allowed_actions: ['use', 'view_config'],
      }),
    );
    expect(readOnlyNotice()).toBe(true);
    const note = document.body.querySelector('[data-slot="alert"]');
    expect(note?.getAttribute('role')).toBe('note');
    // View-only: no Save, and Cancel becomes a lone Close.
    expect(buttonLabels()).not.toContain('settings.sources.configModal.save');
    expect(buttonLabels()).not.toContain('cancel');
    expect(buttonLabels()).toContain('common.close');
  });

  it('an editor can edit (no read-only notice)', async () => {
    await render(
      doc({
        access: 'editor',
        ownership: 'team',
        team_access: 'editor',
        allowed_actions: ['edit', 'use', 'view_config'],
      }),
    );
    expect(readOnlyNotice()).toBe(false);
    expect(buttonLabels()).toContain('settings.sources.configModal.save');
    expect(buttonLabels()).toContain('cancel');
  });

  it('follows allowed_actions over the legacy team_access', async () => {
    await render(
      doc({
        access: 'viewer',
        ownership: 'team',
        team_access: 'editor',
        allowed_actions: ['use', 'view_config'],
      }),
    );
    expect(readOnlyNotice()).toBe(true);
  });

  it('an owned source without access fields is editable', async () => {
    await render(doc({}));
    expect(readOnlyNotice()).toBe(false);
  });

  it('saves a strictness picked in the Relevance section', async () => {
    updateSourceConfig.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, requires_reingest: false }),
    });
    await render(
      doc({
        config: {
          retrieval: {
            reranker: { type: 'decision', min_relevance: 0.3 },
          },
        },
      }),
      { relevance: true },
    );
    const strict = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>(
        '#retrieval-relevance-strictness [data-slot="toggle-group-item"]',
      ),
    ).find(
      (b) =>
        b.textContent ===
        'settings.sources.retrievalOptions.relevance.presets.strict',
    )!;
    await act(async () => strict.click());
    const save = Array.from(document.body.querySelectorAll('button')).find(
      (b) => b.textContent === 'settings.sources.configModal.save',
    )!;
    await act(async () => save.click());
    const config = updateSourceConfig.mock.calls[0][1];
    expect(config.retrieval.reranker).toEqual({
      type: 'decision',
      min_relevance: 0.5,
      candidate_k: null,
    });
    expect(config.retrieval.prescreen).toBe(null);
  });
});

describe('SourceConfigModal first section, by kind', () => {
  let container: HTMLDivElement;
  let root: Root;
  const onSaved = vi.fn();
  const onSyncNow = vi.fn();
  const setModalState = vi.fn();

  const WEBSITE = {
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

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    service.getWebsite.mockResolvedValue({
      ok: true,
      json: async () => ({
        config: WEBSITE,
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
    service.manageSync.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
    });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document.body.innerHTML = '';
    vi.clearAllMocks();
  });

  const render = async (document: Doc) => {
    await act(async () => {
      root.render(
        <SourceConfigModal
          modalState="ACTIVE"
          setModalState={setModalState}
          document={document}
          onReingest={vi.fn()}
          onEnableGraphRAG={vi.fn()}
          onSaved={onSaved}
          onSyncNow={onSyncNow}
        />,
      );
    });
  };

  const buttons = () => Array.from(document.body.querySelectorAll('button'));
  const button = (label: string) =>
    buttons().find((b) => b.textContent === label);
  const scheduleTrigger = () =>
    document.body.querySelector<HTMLButtonElement>(
      'button[role="combobox"][data-testid="source-schedule"]',
    );

  const pickSchedule = async (value: string) => {
    await act(async () => {
      scheduleTrigger()!.dispatchEvent(
        new PointerEvent('pointerdown', {
          bubbles: true,
          button: 0,
          pointerType: 'mouse',
        }),
      );
    });
    const option = Array.from(
      document.body.querySelectorAll<HTMLElement>('[role="option"]'),
    ).find((o) => o.textContent === `settings.sources.syncFrequency.${value}`)!;
    await act(async () => option.click());
  };

  it.each<[string, Partial<Doc>]>([
    ['an upload', {}],
    [
      'a viewer',
      {
        type: 's3',
        connectionId: 'conn-1',
        syncFrequency: 'daily',
        access: 'viewer',
        allowed_actions: ['use', 'view_config'],
      },
    ],
    [
      'a wiki, even with a leftover schedule',
      { type: 'url', syncFrequency: 'weekly', config: { kind: 'wiki' } },
    ],
  ])('%s: no schedule and no Sync now', async (_, fields) => {
    await render(doc(fields));
    expect(scheduleTrigger()).toBeNull();
    expect(button('settings.sources.syncNow')).toBeUndefined();
  });

  it('a synced source keeps its schedule here and saves it', async () => {
    await render(
      doc({ type: 's3', connectionId: 'conn-1', syncFrequency: 'daily' }),
    );
    expect(scheduleTrigger()?.textContent).toBe(
      'settings.sources.syncFrequency.daily',
    );
    await pickSchedule('weekly');
    await act(async () => button('settings.sources.configModal.save')!.click());
    expect(service.manageSync).toHaveBeenCalledWith(
      { source_id: 'src-1', sync_frequency: 'weekly' },
      null,
    );
    // Only the schedule changed: the config isn't written.
    expect(updateSourceConfig).not.toHaveBeenCalled();
    expect(onSaved).toHaveBeenCalledWith({ syncFrequency: 'weekly' });
    expect(setModalState).toHaveBeenCalledWith('INACTIVE');
  });

  it.each([
    [400, 'wiki', 'settings.sources.website.wikiSource'],
    [400, 'bad_sync_frequency', 'settings.sources.website.badSyncFrequency'],
    [500, undefined, 'settings.sources.errors.syncFrequency'],
  ])(
    'keeps a refused schedule change in the dialog, saying why (%s %s)',
    async (status, code, key) => {
      service.manageSync.mockResolvedValue({
        ok: false,
        status,
        json: async () => ({ success: false, code, error: 'English' }),
      });
      await render(doc({ type: 'github', syncFrequency: 'daily' }));
      await pickSchedule('monthly');
      await act(async () =>
        button('settings.sources.configModal.save')!.click(),
      );
      expect(document.body.textContent).toContain(key);
      expect(document.body.textContent).not.toContain('English');
      expect(onSaved).not.toHaveBeenCalled();
      expect(setModalState).not.toHaveBeenCalledWith('INACTIVE');
    },
  );

  it('runs Sync now from the footer of a synced source', async () => {
    await render(doc({ type: 'connector:file', syncFrequency: 'never' }));
    await act(async () => button('settings.sources.syncNow')!.click());
    expect(onSyncNow).toHaveBeenCalled();
    expect(setModalState).toHaveBeenCalledWith('INACTIVE');
  });

  it('turns Sync now off while a sync of the source is still running', async () => {
    await act(async () => {
      root.render(
        <SourceConfigModal
          modalState="ACTIVE"
          setModalState={setModalState}
          document={doc({ type: 'connector:file', syncFrequency: 'never' })}
          onReingest={vi.fn()}
          onEnableGraphRAG={vi.fn()}
          onSaved={onSaved}
          onSyncNow={onSyncNow}
          syncing
        />,
      );
    });
    const sync = button('settings.sources.syncNow')!;
    expect(sync.disabled).toBe(true);
    await act(async () => sync.click());
    expect(onSyncNow).not.toHaveBeenCalled();
  });

  it('turns Sync now off while there are unsaved changes, and says why', async () => {
    await render(
      doc({ type: 's3', connectionId: 'conn-1', syncFrequency: 'daily' }),
    );
    expect(button('settings.sources.syncNow')!.disabled).toBe(false);
    await pickSchedule('weekly');
    const sync = button('settings.sources.syncNow')!;
    expect(sync.disabled).toBe(true);
    await act(async () => sync.click());
    expect(onSyncNow).not.toHaveBeenCalled();
    // The hint shows on the wrapper, which a disabled button can't be.
    await act(async () => sync.parentElement!.focus());
    expect(document.body.textContent).toContain(
      'settings.sources.configModal.syncAfterSave',
    );
  });

  it('a website lists what it fetches and what it skips', async () => {
    await render(
      doc({
        website: { hosts: ['docs.x.io'], pages: 9 },
        syncFrequency: 'weekly',
      }),
    );
    const text = document.body.textContent ?? '';
    expect(text).toContain('docs.x.io');
    expect(text).toContain('github.com/a/b');
    expect(text).toContain('settings.sources.website.limitReached');
    expect(text).toContain('docs.x.io/changelog');
    expect(text).toContain('docs.x.io/Deploying/*');
    expect(button('settings.sources.syncNow')).toBeDefined();
  });

  it('a website saves removed entries, restored skips and the schedule', async () => {
    await render(
      doc({
        website: { hosts: ['docs.x.io'], pages: 9 },
        syncFrequency: 'weekly',
      }),
    );
    const removeButtons = () =>
      buttons().filter((b) =>
        b
          .getAttribute('aria-label')
          ?.startsWith('settings.sources.website.removeFromList'),
      );
    await act(async () => removeButtons()[1].click());
    // The last entry left can't be removed.
    expect(removeButtons().every((b) => b.disabled)).toBe(true);
    await act(async () => button('settings.sources.website.restore')!.click());
    await act(async () => button('settings.sources.configModal.save')!.click());
    expect(service.saveWebsite).toHaveBeenCalledWith(
      {
        source_id: 'src-1',
        entries: [WEBSITE.entries[0]],
        skip: ['https://docs.x.io/Deploying/*'],
        keep_links: false,
        sync_frequency: 'weekly',
      },
      null,
    );
    expect(service.manageSync).not.toHaveBeenCalled();
    expect(updateSourceConfig).not.toHaveBeenCalled();
    expect(onSaved).toHaveBeenCalledWith({ syncFrequency: 'weekly' });
    expect(setModalState).toHaveBeenCalledWith('INACTIVE');
  });

  it("names each row's buttons by its address", async () => {
    await render(
      doc({
        website: { hosts: ['docs.x.io'], pages: 9 },
        syncFrequency: 'weekly',
      }),
    );
    const labels = buttons().map((b) => b.getAttribute('aria-label'));
    expect(labels).toContain(
      'settings.sources.website.removeFromList docs.x.io',
    );
    expect(labels).toContain(
      'settings.sources.website.removeFromList github.com/a/b',
    );
    expect(labels).toContain(
      'settings.sources.website.restoreAddress docs.x.io/changelog',
    );
    expect(labels).toContain(
      'settings.sources.website.restoreAddress docs.x.io/Deploying/*',
    );
  });

  it('draws an entry listed twice as two rows without a key clash', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    service.getWebsite.mockResolvedValue({
      ok: true,
      json: async () => ({
        config: {
          ...WEBSITE,
          entries: [...WEBSITE.entries, WEBSITE.entries[1]],
          skip: [...WEBSITE.skip, WEBSITE.skip[0]],
        },
        sync_frequency: 'weekly',
      }),
    });
    await render(
      doc({
        website: { hosts: ['docs.x.io'], pages: 9 },
        syncFrequency: 'weekly',
      }),
    );
    const removes = buttons().filter((b) =>
      b
        .getAttribute('aria-label')
        ?.startsWith('settings.sources.website.removeFromList'),
    );
    expect(removes).toHaveLength(3);
    expect(
      error.mock.calls.some((call) => String(call[0]).includes('same key')),
    ).toBe(false);
    error.mockRestore();
  });

  const saveEdited = async () => {
    await render(
      doc({
        website: { hosts: ['docs.x.io'], pages: 9 },
        syncFrequency: 'weekly',
      }),
    );
    await act(async () => button('settings.sources.website.restore')!.click());
    await act(async () => button('settings.sources.configModal.save')!.click());
  };

  const SAVE_FAILED = 'settings.sources.website.saveFailed';

  it.each([
    [
      400,
      { code: 'wiki', error: 'A wiki…' },
      'settings.sources.website.wikiSource',
    ],
    // A new address with credentials or a host the server won't fetch.
    [
      400,
      {
        code: 'invalid_address',
        url: 'https://user:pw@docs.x.io/',
        error: "Entry 'https://user:pw@docs.x.io/' is not a web address",
      },
      'settings.sources.website.invalidAddress',
    ],
    [
      400,
      { success: false, error: 'A source fetches from up to 20 sites' },
      'A source fetches from up to 20 sites',
    ],
    // A save that breaks says only that it failed.
    [500, { success: false }, SAVE_FAILED],
  ])(
    'a refused website save says why (%s %o)',
    async (status, body, message) => {
      service.saveWebsite.mockResolvedValue({
        ok: false,
        status,
        json: async () => body,
      });
      await saveEdited();
      const text = document.body.textContent;
      expect(text).toContain(message);
      if (message !== SAVE_FAILED) expect(text).not.toContain(SAVE_FAILED);
      expect(setModalState).not.toHaveBeenCalledWith('INACTIVE');
    },
  );
});
