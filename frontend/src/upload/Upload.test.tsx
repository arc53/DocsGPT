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
  useDispatch: () => vi.fn(),
  useStore: () => ({ getState: () => ({}) }),
}));

vi.mock('../api/services/userService', () => ({
  default: {
    getConfig: () => Promise.resolve({ json: () => Promise.resolve({}) }),
  },
}));

const launch = vi.hoisted(() => vi.fn());
vi.mock('../connectors/useConnectorLauncher', () => ({
  default: () => ({ launch, modals: null }),
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

  it('renders each source type as a button tile', async () => {
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
    expect(crawler!.querySelector('img')?.className).toContain('size-6');
  });

  it('selects the clicked source type', async () => {
    await render();
    const crawler = tiles().find((tile) =>
      tile.textContent?.includes('modals.uploadDoc.ingestors.crawler.label'),
    )!;
    await act(async () => crawler.click());
    expect(tiles()).toHaveLength(0);
    expect(document.body.textContent).toContain(
      'modals.uploadDoc.ingestors.crawler.heading',
    );
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
  const connectTile = () =>
    tiles().find((tile) =>
      tile.textContent?.includes('modals.uploadDoc.connectData.title'),
    );

  // One list of what needs no account, then one tile that sends the user to
  // connect a service; connected services sync from the Connectors page.
  it('lists the no-account types and one Connect your data tile', async () => {
    connectorsState.catalog = [DRIVE];
    await render();
    const labels = tiles().map((tile) => tile.textContent ?? '');
    for (const type of ['local_file', 'url', 'crawler', 'github', 'wiki'])
      expect(labels.some((l) => l.includes(`ingestors.${type}.label`))).toBe(
        true,
      );
    for (const type of [
      'google_drive',
      'share_point',
      'confluence',
      's3',
      'reddit',
    ])
      expect(labels.some((l) => l.includes(`ingestors.${type}.label`))).toBe(
        false,
      );
    expect(labels.at(-1)).toContain('modals.uploadDoc.connectData.title');
    // Named after what this instance can sync.
    expect(labels.at(-1)).toContain(
      'modals.uploadDoc.connectData.description(Google Drive)',
    );
    expect(document.body.querySelector('h3')).toBeNull();
    connectorsState.catalog = [];
  });

  // Like the Connectors page: connected services first, and a part (a
  // service's sync half) listed under its parent. GitHub has its own tile.
  const CATALOG = [
    DRIVE,
    { ...DRIVE, key: 'share_point', name: 'SharePoint' },
    { ...DRIVE, key: 'github', name: 'GitHub', state: 'connected' },
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

  it('names three syncing services, then the rest as more', async () => {
    connectorsState.catalog = CATALOG;
    await render();
    expect(connectTile()!.textContent).toContain(
      'modals.uploadDoc.connectData.description(Amazon S3, Google Drive, SharePoint, and modals.uploadDoc.connectData.more)',
    );
    connectorsState.catalog = [];
  });

  const serviceTiles = () =>
    tiles().map(
      (tile) => tile.querySelector('[data-slot="card-title"]')?.textContent,
    );

  it('lists the services that sync in place of the tiles, with a way back', async () => {
    connectorsState.catalog = CATALOG;
    close.mockClear();
    await render();
    await act(async () => connectTile()!.click());
    expect(close).not.toHaveBeenCalled();
    expect(serviceTiles()).toEqual([
      'GitHub',
      'Amazon S3',
      'Google Drive',
      'SharePoint',
      'Atlassian',
    ]);
    const back = Array.from(document.body.querySelectorAll('button')).find(
      (b) => b.textContent === 'modals.uploadDoc.back',
    )!;
    await act(async () => back.click());
    expect(connectTile()).toBeDefined();
    connectorsState.catalog = [];
  });

  it('connects a service in place, for Knowledge', async () => {
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
    await act(async () => connectTile()!.click());
    const tile = (name: string) =>
      tiles().find(
        (t) =>
          t.querySelector('[data-slot="card-title"]')?.textContent === name,
      )!;
    expect(tile('Amazon S3').textContent).toContain(
      'modals.uploadDoc.connectData.connectedAs(bucket-reader)',
    );
    // An account already connected goes straight to choosing what to sync.
    await act(async () => tile('Amazon S3').click());
    expect(launch).toHaveBeenLastCalledWith(
      expect.objectContaining({ key: 's3' }),
      { mode: 'sync', connectionId: 'k1', purpose: 'knowledge' },
    );
    connectorsState.connections = [];
    connectorsState.catalog = [];
  });

  it('connects the sync part of a service listed under its parent', async () => {
    connectorsState.catalog = CATALOG;
    launch.mockClear();
    await render();
    await act(async () => connectTile()!.click());
    const atlassian = tiles().find(
      (t) =>
        t.querySelector('[data-slot="card-title"]')?.textContent ===
        'Atlassian',
    )!;
    await act(async () => atlassian.click());
    expect(launch).toHaveBeenLastCalledWith(
      expect.objectContaining({ key: 'confluence' }),
      { purpose: 'knowledge' },
    );
    connectorsState.catalog = [];
  });

  it('browses all connectors only when the opener offers it', async () => {
    connectorsState.catalog = CATALOG;
    const browseLink = () =>
      Array.from(document.body.querySelectorAll('button')).find(
        (b) => b.textContent === 'modals.uploadDoc.connectData.browseAll',
      );
    await render();
    await act(async () => connectTile()!.click());
    expect(browseLink()).toBeUndefined();

    const browse = vi.fn();
    close.mockClear();
    await render(browse);
    expect(browseLink()).toBeDefined();
    await act(async () => browseLink()!.click());
    expect(close).toHaveBeenCalled();
    expect(browse).toHaveBeenCalled();
    connectorsState.catalog = [];
  });

  it('offers no Connect tile when no service can sync', async () => {
    connectorsState.catalog = [
      { key: 'telegram', capabilities: ['write'], available: true },
      { ...DRIVE, available: false },
    ];
    await render();
    expect(connectTile()).toBeUndefined();
    connectorsState.catalog = [];
  });

  it('offers no Connect tile when connectors are off', async () => {
    connectorsState.catalog = [DRIVE];
    connectorsState.enabled = false;
    await render();
    expect(connectTile()).toBeUndefined();
    connectorsState.enabled = true;
    connectorsState.catalog = [];
  });

  describe('GitHub', () => {
    const githubConnector = {
      key: 'github',
      icon: 'github',
      sync_ingestor: 'github',
      auth_kind: 'api_key',
      available: true,
      missing_settings: [],
    };
    const openGitHub = async () => {
      await render();
      const tile = tiles().find((t) =>
        t.textContent?.includes('modals.uploadDoc.ingestors.github.label'),
      )!;
      await act(async () => tile.click());
    };
    const handOver = () =>
      Array.from(document.body.querySelectorAll('button')).find((b) =>
        b.textContent?.includes('modals.uploadDoc.github.'),
      );

    afterEach(() => {
      connectorsState.catalog = [];
      connectorsState.connections = [];
    });

    it('stays one public-repository tile, with a way to private ones', async () => {
      launch.mockClear();
      connectorsState.catalog = [githubConnector];
      await render();
      const githubTiles = tiles().filter((t) =>
        t.textContent?.includes('modals.uploadDoc.ingestors.github.label'),
      );
      expect(githubTiles).toHaveLength(1);
      await openGitHub();
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
      await openGitHub();
      expect(document.body.textContent).toContain(
        'modals.uploadDoc.github.connectedHint',
      );
      await act(async () => handOver()!.click());
      expect(launch).toHaveBeenCalledWith(githubConnector, {
        mode: 'sync',
        connectionId: 'gh-1',
        purpose: 'knowledge',
      });
    });

    it('offers no hand-over when GitHub connections are off', async () => {
      connectorsState.catalog = [];
      await openGitHub();
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
