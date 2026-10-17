import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { services?: string; account?: string }) =>
      opts?.services
        ? `${key}(${opts.services})`
        : opts?.account
          ? `${key}(${opts.account})`
          : key,
    i18n: { language: 'en' },
  }),
}));

const connectorsState = vi.hoisted(() => ({
  catalog: [] as Record<string, unknown>[],
  connections: [] as Record<string, unknown>[],
  enabled: true,
}));

vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) => {
    const state = {
      preference: { token: null, selectedDocs: [] },
      connectors: {
        catalog: connectorsState.catalog,
        connections: connectorsState.connections,
        enabled: connectorsState.enabled,
        loaded: true,
        loading: false,
        failed: false,
      },
    };
    try {
      return selector(state);
    } catch {
      return null;
    }
  },
  useDispatch: () => fakeStore.dispatch,
  useStore: () => fakeStore,
}));

// Just enough of the Redux store for Upload's ingest tracking: the upload
// tasks and recent notification events it watches, and a way to notify it.
const fakeStore = vi.hoisted(() => {
  const listeners = new Set<() => void>();
  const state = {
    upload: { tasks: [] as Record<string, unknown>[] },
    notifications: { recentEvents: [] as Record<string, unknown>[] },
    preference: { selectedDocs: [] as { id: string }[] },
  };
  return {
    state,
    getState: () => state,
    // Applies the chat selection; every other action is ignored.
    dispatch: (action: { type?: string; payload?: unknown }) => {
      if (action?.type === 'preference/setSelectedDocs')
        state.preference.selectedDocs = action.payload as { id: string }[];
      return action;
    },
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    notify: () => listeners.forEach((listener) => listener()),
    reset: () => {
      listeners.clear();
      state.upload.tasks = [];
      state.notifications.recentEvents = [];
      state.preference.selectedDocs = [];
    },
  };
});

const getDocs = vi.hoisted(() => vi.fn());
vi.mock('../preferences/preferenceApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../preferences/preferenceApi')>()),
  getDocs,
}));

vi.mock('../api/services/userService', () => ({
  default: {
    getConfig: () => Promise.resolve({ json: () => Promise.resolve({}) }),
  },
}));

const launch = vi.hoisted(() => vi.fn());
// What Upload asked the launcher to report back (B5).
type LauncherOptions = {
  onConnected?: () => void;
  onCancel?: () => void;
  onSynced?: (sourceIds: string[]) => void;
};
const launcher = vi.hoisted(() => ({
  options: undefined as LauncherOptions | undefined,
}));
vi.mock('../connectors/useConnectorLauncher', () => ({
  default: (options?: LauncherOptions) => {
    launcher.options = options;
    return { launch, modals: null };
  },
}));

import Upload from './Upload';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('Upload source-type tiles', () => {
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

  const close = vi.fn();
  const render = async (onBrowseConnectors?: () => void) => {
    await act(async () => {
      root.render(
        <Upload
          receivedFile={[]}
          setModalState={vi.fn()}
          isOnboarding={false}
          renderTab={null}
          close={close}
          onBrowseConnectors={onBrowseConnectors}
        />,
      );
    });
  };

  const tiles = () =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>(
        '[data-slot="option-card"]',
      ),
    );

  it('renders each source type as a button tile with a lucide icon', async () => {
    await render();
    const found = tiles();
    expect(found.length).toBeGreaterThan(0);
    for (const tile of found) {
      expect(tile.tagName).toBe('BUTTON');
      expect(tile.getAttribute('type')).toBe('button');
    }
    const crawler = found.find((tile) =>
      tile.textContent?.includes('modals.uploadDoc.ingestors.crawler.label'),
    );
    expect(crawler).toBeDefined();
    expect(crawler!.querySelector('img')).toBeNull();
    expect(crawler!.querySelector('svg')?.getAttribute('class')).toContain(
      'lucide-globe',
    );
  });

  const dialogTitle = () =>
    document.body.querySelector('[data-slot="dialog-title"]');

  it('titles the first step in the modal header', async () => {
    await render();
    expect(dialogTitle()?.textContent).toBe('modals.uploadDoc.selectSource');
    expect(dialogTitle()?.closest('[data-slot="modal-header"]')).not.toBeNull();
    // No second, hand-drawn heading in the body.
    expect(document.body.querySelectorAll('h2')).toHaveLength(1);
    expect(backButton()).toBeUndefined();
  });

  it('selects the clicked source type', async () => {
    await render();
    const crawler = tiles().find((tile) =>
      tile.textContent?.includes('modals.uploadDoc.ingestors.crawler.label'),
    )!;
    await act(async () => crawler.click());
    expect(tiles()).toHaveLength(0);
    expect(dialogTitle()?.textContent).toBe(
      'modals.uploadDoc.ingestors.crawler.heading',
    );
  });

  const backButton = () =>
    document.body.querySelector<HTMLButtonElement>(
      '[data-slot="modal-header"] button[aria-label="sidePanel.back"]',
    ) ?? undefined;

  it('goes back with the header Back arrow', async () => {
    await render();
    const crawler = tiles().find((tile) =>
      tile.textContent?.includes('modals.uploadDoc.ingestors.crawler.label'),
    )!;
    await act(async () => crawler.click());
    const back = backButton()!;
    expect(back.getAttribute('data-variant')).toBe('ghost-muted');
    expect(back.querySelector('svg')?.getAttribute('class')).toContain(
      'lucide-arrow-left',
    );
    expect(document.body.textContent).not.toContain('modals.uploadDoc.back');
    await act(async () => back.click());
    expect(tiles().length).toBeGreaterThan(0);
  });

  const DRIVE = {
    key: 'google_drive',
    name: 'Google Drive',
    state: 'available',
    icon: 'drive',
    sync_ingestor: 'google_drive',
    capabilities: ['sync'],
    available: true,
    missing_settings: [],
  };

  // Like the Connectors page: connected services first, and a part (a
  // service's sync half) listed under its parent.
  const CATALOG = [
    DRIVE,
    { ...DRIVE, key: 'share_point', name: 'SharePoint' },
    {
      ...DRIVE,
      key: 'github',
      name: 'GitHub',
      icon: 'github',
      state: 'connected',
    },
    { ...DRIVE, key: 's3', name: 'Amazon S3', state: 'connected' },
    {
      key: 'mcp:atlassian',
      name: 'Atlassian',
      capabilities: ['read', 'write'],
      available: true,
      state: 'available',
    },
    {
      ...DRIVE,
      key: 'confluence',
      name: 'Confluence',
      part_of: 'mcp:atlassian',
    },
    { ...DRIVE, key: 'off', name: 'Needs setup', available: false },
    { key: 'telegram', name: 'Telegram', capabilities: ['write'] },
  ];

  const section = () =>
    Array.from(document.body.querySelectorAll('section')).find((el) =>
      el
        .querySelector('h3')
        ?.textContent?.includes('modals.uploadDoc.fromService'),
    );
  const serviceTiles = () =>
    Array.from(
      section()?.querySelectorAll<HTMLButtonElement>(
        '[data-slot="option-card"]',
      ) ?? [],
    );
  const serviceNames = () =>
    serviceTiles().map(
      (tile) => tile.querySelector('[data-slot="card-title"]')?.textContent,
    );
  const serviceTile = (name: string) =>
    serviceTiles().find(
      (t) => t.querySelector('[data-slot="card-title"]')?.textContent === name,
    )!;
  const statusLine = (name: string) =>
    serviceTile(name).querySelector('[data-slot="card-description"]')
      ?.textContent;

  afterEach(() => {
    connectorsState.catalog = [];
    connectorsState.connections = [];
    connectorsState.enabled = true;
  });

  // One view: what needs no account, then the services that sync, listed
  // directly (no "Connect your data" step).
  it('lists the no-account types, then the syncing services in one view', async () => {
    connectorsState.catalog = CATALOG;
    close.mockClear();
    await render();
    const noAccount = tiles()
      .filter((tile) => !section()?.contains(tile))
      .map((tile) => tile.textContent ?? '');
    expect(noAccount).toEqual([
      'modals.uploadDoc.ingestors.local_file.label',
      'modals.uploadDoc.ingestors.url.label',
      'modals.uploadDoc.ingestors.crawler.label',
      'modals.uploadDoc.ingestors.wiki.label',
    ]);
    expect(document.body.textContent).not.toContain('connectData');
    const header = section()!.querySelector('[data-slot="section-header"]');
    expect(header).not.toBeNull();
    // GitHub once, in the service section.
    expect(serviceNames()).toEqual([
      'GitHub',
      'Amazon S3',
      'Google Drive',
      'SharePoint',
      'Atlassian',
    ]);
    expect(close).not.toHaveBeenCalled();
  });

  it('draws the services as compact cards, logos in the tile colour', async () => {
    connectorsState.catalog = CATALOG;
    await render();
    const grid = serviceTile('Google Drive').parentElement!;
    expect(grid.className).toContain('md:grid-cols-3');
    const logo = serviceTile('Google Drive').querySelector(
      '[data-slot="option-card-icon"] svg',
    );
    // Same colour as the source-type glyphs: the icon square's.
    expect(logo?.getAttribute('class')).toContain('text-current');
    expect(logo?.getAttribute('class')).not.toContain('text-foreground');
    // No status, no line.
    expect(statusLine('Google Drive')).toBeUndefined();
  });

  it('says Connected, without the account, and syncs from the one account', async () => {
    connectorsState.catalog = CATALOG;
    connectorsState.connections = [
      {
        id: 'k1',
        connector_key: 's3',
        status: 'connected',
        account_label: 'bucket-reader',
      },
    ];
    launch.mockClear();
    await render();
    expect(statusLine('Amazon S3')).toBe(
      'settings.connectors.status.connected',
    );
    expect(serviceTile('Amazon S3').textContent).not.toContain('bucket-reader');
    await act(async () => serviceTile('Amazon S3').click());
    expect(launch).toHaveBeenLastCalledWith(
      expect.objectContaining({ key: 's3' }),
      { mode: 'sync', connectionId: 'k1', purpose: 'knowledge' },
    );
  });

  // B9: with two accounts the wizard asks which one; none is picked here.
  it('leaves the account to the wizard when there are several', async () => {
    connectorsState.catalog = CATALOG;
    connectorsState.connections = [
      { id: 'k1', connector_key: 's3', status: 'connected' },
      { id: 'k2', connector_key: 's3', status: 'connected' },
    ];
    launch.mockClear();
    await render();
    expect(statusLine('Amazon S3')).toBe(
      'settings.connectors.status.connected',
    );
    await act(async () => serviceTile('Amazon S3').click());
    expect(launch).toHaveBeenLastCalledWith(
      expect.objectContaining({ key: 's3' }),
      { mode: 'sync', purpose: 'knowledge' },
    );
  });

  // B10: an account that needs signing in again is repaired, not duplicated.
  it('reconnects a service whose only account needs signing in again', async () => {
    connectorsState.catalog = CATALOG;
    connectorsState.connections = [
      { id: 'd1', connector_key: 'google_drive', status: 'reconnect_needed' },
    ];
    launch.mockClear();
    await render();
    expect(statusLine('Google Drive')).toBe(
      'settings.connectors.status.reconnect',
    );
    await act(async () => serviceTile('Google Drive').click());
    expect(launch).toHaveBeenLastCalledWith(
      expect.objectContaining({ key: 'google_drive' }),
      { mode: 'reconnect', connectionId: 'd1', purpose: 'knowledge' },
    );
  });

  it('connects a service with no account, for Knowledge', async () => {
    connectorsState.catalog = CATALOG;
    launch.mockClear();
    await render();
    await act(async () => serviceTile('Google Drive').click());
    expect(launch).toHaveBeenLastCalledWith(
      expect.objectContaining({ key: 'google_drive' }),
      { purpose: 'knowledge' },
    );
  });

  it('connects the sync part of a service listed under its parent', async () => {
    connectorsState.catalog = CATALOG;
    launch.mockClear();
    await render();
    await act(async () => serviceTile('Atlassian').click());
    expect(launch).toHaveBeenLastCalledWith(
      expect.objectContaining({ key: 'confluence' }),
      { purpose: 'knowledge' },
    );
  });

  // B5: the wizard steps in for this modal; cancelling it brings the modal
  // back where it was, and only a connect closes both.
  it('comes back when the wizard is cancelled, and closes on a connect', async () => {
    connectorsState.catalog = CATALOG;
    close.mockClear();
    await render();
    await act(async () => serviceTile('Google Drive').click());
    expect(section()).toBeUndefined();
    await act(async () => launcher.options?.onCancel?.());
    expect(close).not.toHaveBeenCalled();
    expect(serviceNames()).toContain('Google Drive');
    await act(async () => serviceTile('Google Drive').click());
    await act(async () => launcher.options?.onConnected?.());
    expect(close).toHaveBeenCalled();
  });

  // Two rows at most: services with an account always, then the rest.
  it('shows at most six services, keeping every one with an account', async () => {
    const many = Array.from({ length: 9 }, (_, i) => ({
      ...DRIVE,
      key: `svc${i}`,
      name: `Service ${i}`,
    }));
    connectorsState.catalog = [
      ...many,
      { ...DRIVE, key: 'github', name: 'GitHub', icon: 'github' },
    ];
    await render();
    expect(serviceNames()).toEqual([
      'Service 0',
      'Service 1',
      'Service 2',
      'Service 3',
      'Service 4',
      'Service 5',
    ]);

    connectorsState.connections = [
      { id: 'a', connector_key: 'svc7', status: 'connected' },
      { id: 'b', connector_key: 'svc8', status: 'reconnect_needed' },
    ];
    await render();
    expect(serviceNames()).toEqual([
      'Service 0',
      'Service 1',
      'Service 2',
      'Service 3',
      'Service 7',
      'Service 8',
    ]);
  });

  const browseLink = () =>
    Array.from(document.body.querySelectorAll('button')).find(
      (b) => b.textContent === 'settings.connectors.browseAll',
    );

  it('browses all connectors under the services, only when the opener offers it', async () => {
    connectorsState.catalog = CATALOG;
    await render();
    expect(browseLink()).toBeUndefined();

    const browse = vi.fn();
    close.mockClear();
    await render(browse);
    const link = browseLink()!;
    expect(section()!.contains(link)).toBe(true);
    // A trailing link icon: 12px from Button's link size, not its own class.
    expect(link.className).toContain("[&_svg:not([class*='size-'])]:size-3");
    expect(link.querySelector('svg')?.getAttribute('class')).not.toContain(
      'size-',
    );
    await act(async () => link.click());
    expect(close).toHaveBeenCalled();
    expect(browse).toHaveBeenCalled();
  });

  // GitHub reads a public repository by URL with no account, so it stays
  // even where no connector can sync.
  it('keeps only GitHub, by URL, when no connector can sync', async () => {
    connectorsState.catalog = [
      { key: 'telegram', capabilities: ['write'], available: true },
      { ...DRIVE, available: false },
    ];
    await render();
    expect(serviceNames()).toEqual(['modals.uploadDoc.ingestors.github.label']);
  });

  it('keeps only GitHub, by URL, when connectors are off', async () => {
    connectorsState.catalog = [DRIVE];
    connectorsState.enabled = false;
    await render();
    expect(serviceNames()).toEqual(['modals.uploadDoc.ingestors.github.label']);
  });

  describe('GitHub', () => {
    const githubConnector = {
      key: 'github',
      name: 'GitHub',
      icon: 'github',
      sync_ingestor: 'github',
      auth_kind: 'api_key',
      capabilities: ['sync'],
      state: 'available',
      available: true,
      missing_settings: [],
    };
    const handOver = () =>
      Array.from(document.body.querySelectorAll('button')).find((b) =>
        b.textContent?.includes('modals.uploadDoc.github.'),
      );

    it('opens the repository URL form, with a way to private ones', async () => {
      launch.mockClear();
      connectorsState.catalog = [githubConnector];
      await render();
      expect(serviceNames()).toEqual(['GitHub']);
      await act(async () => serviceTile('GitHub').click());
      expect(launch).not.toHaveBeenCalled();
      // The repository URL form still works without an account.
      expect(document.body.textContent).toContain(
        'modals.uploadDoc.ingestors.github.heading',
      );
      expect(document.body.textContent).toContain(
        'modals.uploadDoc.github.privateHint',
      );
      await act(async () => handOver()!.click());
      expect(launch).toHaveBeenCalledWith(githubConnector, {
        purpose: 'knowledge',
      });
    });

    it('comes back to the form when Connect GitHub is cancelled', async () => {
      connectorsState.catalog = [githubConnector];
      close.mockClear();
      await render();
      await act(async () => serviceTile('GitHub').click());
      await act(async () => handOver()!.click());
      await act(async () => launcher.options?.onCancel?.());
      expect(close).not.toHaveBeenCalled();
      expect(document.body.textContent).toContain(
        'modals.uploadDoc.ingestors.github.heading',
      );
    });

    it('goes straight to picking a repository with a connected account', async () => {
      launch.mockClear();
      connectorsState.catalog = [githubConnector];
      connectorsState.connections = [
        {
          id: 'gh-1',
          connector_key: 'github',
          status: 'connected',
          account_label: 'octocat',
        },
      ];
      await render();
      expect(statusLine('GitHub')).toBe('settings.connectors.status.connected');
      await act(async () => serviceTile('GitHub').click());
      expect(launch).toHaveBeenCalledWith(githubConnector, {
        mode: 'sync',
        connectionId: 'gh-1',
        purpose: 'knowledge',
      });
    });

    it('offers no hand-over when GitHub connections are off', async () => {
      connectorsState.catalog = [];
      await render();
      await act(async () =>
        serviceTile('modals.uploadDoc.ingestors.github.label').click(),
      );
      expect(document.body.textContent).toContain(
        'modals.uploadDoc.ingestors.github.heading',
      );
      expect(handOver()).toBeUndefined();
    });
  });

  it('sends a crawler source to the remote ingest with its URL', async () => {
    const sent: { url: string; body: FormData }[] = [];
    class FakeXhr {
      upload = { addEventListener() {} };
      url = '';
      addEventListener() {}
      open(_method: string, url: string) {
        this.url = url;
      }
      setRequestHeader() {}
      send(body: FormData) {
        sent.push({ url: this.url, body });
      }
    }
    vi.stubGlobal('XMLHttpRequest', FakeXhr);
    await render();
    const crawler = tiles().find((tile) =>
      tile.textContent?.includes('modals.uploadDoc.ingestors.crawler.label'),
    )!;
    await act(async () => crawler.click());
    const type = async (input: HTMLInputElement, value: string) => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!;
      await act(async () => {
        setter.call(input, value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
      });
    };
    const inputs = Array.from(
      document.body.querySelectorAll<HTMLInputElement>('input[type="text"]'),
    );
    // The source's name first, then the crawler's URL field.
    await type(inputs[0], 'Docs site');
    await type(
      document.body.querySelector<HTMLInputElement>('input[name="url"]')!,
      'https://docs.example',
    );
    const train = Array.from(document.body.querySelectorAll('button')).find(
      (b) => b.textContent === 'modals.uploadDoc.train',
    )!;
    expect(train.disabled).toBe(false);
    await act(async () => train.click());
    expect(sent).toHaveLength(1);
    expect(sent[0].url).toContain('/api/remote');
    expect(sent[0].body.get('source')).toBe('crawler');
    expect(JSON.parse(String(sent[0].body.get('data')))).toEqual({
      url: 'https://docs.example',
    });
    vi.unstubAllGlobals();
  });

  it('leaves the disabled Train button on the default variant', async () => {
    await render();
    const crawler = tiles().find((tile) =>
      tile.textContent?.includes('modals.uploadDoc.ingestors.crawler.label'),
    )!;
    await act(async () => crawler.click());
    const train = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent === 'modals.uploadDoc.train');
    expect(train).toBeDefined();
    expect(train!.disabled).toBe(true);
    expect(train!.className).not.toContain('bg-gray-300');
    expect(train!.className).toContain('bg-primary');
  });
});

// A service connected from Connect your data syncs its content like an upload
// ingests: the Knowledge list is re-read once the synced source is ingested.
describe('Upload connected-service sync', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    fakeStore.reset();
    getDocs.mockReset();
    getDocs.mockResolvedValue([{ id: 'src-1', name: 'Espresso One docs' }]);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    fakeStore.reset();
  });

  const render = async (onSuccessfulUpload: (id?: string) => void) => {
    await act(async () => {
      root.render(
        <Upload
          receivedFile={[]}
          setModalState={vi.fn()}
          isOnboarding={false}
          renderTab={null}
          close={vi.fn()}
          onSuccessfulUpload={onSuccessfulUpload}
        />,
      );
    });
  };

  it('refreshes the Knowledge list once a synced source finishes ingesting', async () => {
    const onSuccessfulUpload = vi.fn();
    await render(onSuccessfulUpload);
    expect(launcher.options?.onSynced).toBeTypeOf('function');
    await act(async () => launcher.options!.onSynced!(['src-1']));
    // Still ingesting: nothing to show yet.
    fakeStore.state.upload.tasks = [
      { id: 'src-1', sourceId: 'src-1', status: 'training', progress: 40 },
    ];
    await act(async () => fakeStore.notify());
    expect(getDocs).not.toHaveBeenCalled();
    fakeStore.state.upload.tasks = [
      { id: 'src-1', sourceId: 'src-1', status: 'completed', progress: 100 },
    ];
    await act(async () => fakeStore.notify());
    expect(getDocs).toHaveBeenCalledTimes(1);
    expect(onSuccessfulUpload).toHaveBeenCalledWith('src-1');
  });

  it('refreshes when the completion arrived before any progress', async () => {
    const onSuccessfulUpload = vi.fn();
    await render(onSuccessfulUpload);
    // The slice makes no task from a lone completion event.
    fakeStore.state.notifications.recentEvents = [
      { type: 'source.ingest.completed', scope: { id: 'src-1' } },
    ];
    await act(async () => launcher.options!.onSynced!(['src-1']));
    expect(getDocs).toHaveBeenCalledTimes(1);
    expect(onSuccessfulUpload).toHaveBeenCalledWith('src-1');
  });

  const complete = async (ids: string[]) => {
    fakeStore.state.upload.tasks = ids.map((id) => ({
      id,
      sourceId: id,
      status: 'completed',
      progress: 100,
    }));
    await act(async () => fakeStore.notify());
  };

  it('selects every source one sync started, as each finishes', async () => {
    getDocs.mockResolvedValue([
      { id: 'src-1', name: 'Handbook' },
      { id: 'src-2', name: 'FAQ' },
    ]);
    await render(vi.fn());
    await act(async () => launcher.options!.onSynced!(['src-1', 'src-2']));
    await complete(['src-1']);
    await complete(['src-1', 'src-2']);
    expect(fakeStore.state.preference.selectedDocs.map((d) => d.id)).toEqual([
      'src-1',
      'src-2',
    ]);
  });

  it('still replaces a single earlier selection with the new source', async () => {
    fakeStore.state.preference.selectedDocs = [{ id: 'old' }];
    await render(vi.fn());
    await act(async () => launcher.options!.onSynced!(['src-1']));
    await complete(['src-1']);
    expect(fakeStore.state.preference.selectedDocs.map((d) => d.id)).toEqual([
      'src-1',
    ]);
  });

  it('does not refresh for a sync that failed', async () => {
    const onSuccessfulUpload = vi.fn();
    await render(onSuccessfulUpload);
    await act(async () => launcher.options!.onSynced!(['src-1']));
    fakeStore.state.upload.tasks = [
      { id: 'src-1', sourceId: 'src-1', status: 'failed', progress: 0 },
    ];
    await act(async () => fakeStore.notify());
    expect(getDocs).not.toHaveBeenCalled();
    expect(onSuccessfulUpload).not.toHaveBeenCalled();
  });
});

function makeFile(name: string, type: string, bytes = 10): File {
  return new File([new Uint8Array(bytes)], name, { type });
}

describe('Upload local file step', () => {
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

  const openLocalFile = async () => {
    await act(async () => {
      root.render(
        <Upload
          receivedFile={[]}
          setModalState={vi.fn()}
          isOnboarding={false}
          renderTab={null}
          close={vi.fn()}
        />,
      );
    });
    const tile = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>(
        '[data-slot="option-card"]',
      ),
    ).find((el) =>
      el.textContent?.includes('modals.uploadDoc.ingestors.local_file.label'),
    )!;
    await act(async () => tile.click());
  };

  const pick = async (files: File[]) => {
    const input = document.body.querySelector(
      '[data-slot="dropzone"] input[type="file"]',
    );
    if (!input) throw new Error('no dropzone input');
    Object.defineProperty(input, 'files', { value: files, configurable: true });
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    // react-dropzone resolves the selected files asynchronously.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  };

  it('renders the file field as a default-size Dropzone', async () => {
    await openLocalFile();
    const zone = document.body.querySelector('[data-slot="dropzone"]');
    expect(zone).not.toBeNull();
    expect(zone!.getAttribute('data-size')).toBe('default');
    expect(zone!.textContent).toContain('modals.uploadDoc.dropzoneText');
    expect(zone!.textContent).toContain('modals.uploadDoc.dropzoneHint');
    expect(document.body.textContent).not.toContain('modals.uploadDoc.choose');
    expect(document.body.textContent).not.toContain(
      'modals.uploadDoc.selectedFiles',
    );
    // No list until something is picked.
    expect(document.body.querySelector('[data-slot="list-rows"]')).toBeNull();
  });

  it('lists picked files as rows with their size and fills the name', async () => {
    await openLocalFile();
    await pick([
      makeFile('rates.pdf', 'application/pdf', 2048),
      makeFile('notes.md', 'text/x-markdown', 10),
    ]);
    const rows = Array.from(
      document.body.querySelectorAll('[data-slot="list-row"]'),
    );
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain('rates.pdf');
    expect(rows[0].textContent).toContain('2 KB');
    expect(rows[1].textContent).toContain('notes.md');
    const card = rows[0].closest('[data-slot="card"]');
    expect(card).not.toBeNull();
    expect(card!.getAttribute('data-variant')).toBe('outline');
    const textInputs = Array.from(
      document.body.querySelectorAll<HTMLInputElement>('input[type="text"]'),
    );
    expect(textInputs.some((el) => el.value === 'rates.pdf')).toBe(true);
    const train = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent === 'modals.uploadDoc.train');
    expect(train!.disabled).toBe(false);
  });

  it('replaces the selection on a new drop', async () => {
    await openLocalFile();
    await pick([makeFile('a.pdf', 'application/pdf')]);
    await pick([makeFile('b.pdf', 'application/pdf')]);
    const rows = document.body.querySelectorAll('[data-slot="list-row"]');
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain('b.pdf');
  });

  it('reports files that are too large or of an unsupported type', async () => {
    await openLocalFile();
    const big = makeFile('huge.pdf', 'application/pdf');
    Object.defineProperty(big, 'size', { value: 26_000_000 });
    await pick([
      big,
      makeFile('setup.exe', 'application/x-msdownload'),
      makeFile('ok.pdf', 'application/pdf'),
    ]);
    const rows = document.body.querySelectorAll('[data-slot="list-row"]');
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain('ok.pdf');
    const zone = document.body.querySelector('[data-slot="dropzone"]')!;
    expect(zone.parentElement!.querySelector('p')?.textContent).toBe(
      'modals.uploadDoc.filesRejected',
    );
    // A clean drop clears the message.
    await pick([makeFile('next.pdf', 'application/pdf')]);
    expect(zone.parentElement!.querySelector('p')).toBeNull();
  });
});
