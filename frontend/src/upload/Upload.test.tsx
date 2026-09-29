import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { services?: string }) =>
      opts?.services ? `${key}(${opts.services})` : key,
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
const navigate = vi.hoisted(() => vi.fn());
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }));
vi.mock('../connectors/useConnectorLauncher', () => ({
  default: () => ({ launch, modals: null }),
}));

// The file picker reports its default account and a pick as it mounts.
vi.mock('../components/FilePicker', async () => {
  const { useEffect } = await import('react');
  return {
    FilePicker: function Picker(props: {
      onConnectionChange: (id: string | null) => void;
      onSelectionChange: (files: string[], folders?: string[]) => void;
      onFirstPickName: (name: string) => void;
    }) {
      useEffect(() => {
        props.onConnectionChange('drive-1');
        props.onSelectionChange(['file-1'], []);
        props.onFirstPickName('Handbook');
      }, []);
      return null;
    },
  };
});

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
  const render = async () => {
    await act(async () => {
      root.render(
        <Upload
          receivedFile={[]}
          setModalState={vi.fn()}
          isOnboarding={false}
          renderTab={null}
          close={close}
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

  it('names three syncing services, then the rest as more', async () => {
    connectorsState.catalog = [
      DRIVE,
      { ...DRIVE, key: 'share_point', name: 'SharePoint' },
      { ...DRIVE, key: 'confluence', name: 'Confluence' },
      { ...DRIVE, key: 's3', name: 'Amazon S3' },
      { ...DRIVE, key: 'off', name: 'Needs setup', available: false },
      { key: 'telegram', name: 'Telegram', capabilities: ['write'] },
    ];
    await render();
    expect(connectTile()!.textContent).toContain(
      'modals.uploadDoc.connectData.description(Google Drive, SharePoint, Confluence, and modals.uploadDoc.connectData.more)',
    );
    connectorsState.catalog = [];
  });

  it('opens the Connectors page on the syncing services', async () => {
    connectorsState.catalog = [DRIVE];
    navigate.mockClear();
    close.mockClear();
    await render();
    await act(async () => connectTile()!.click());
    expect(close).toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith(
      '/settings/connectors?capability=sync',
    );
    expect(launch).not.toHaveBeenCalled();
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

  it('picks the saved account once connections finish loading', async () => {
    connectorsState.catalog = [
      {
        key: 's3',
        icon: 's3',
        sync_ingestor: 's3',
        auth_kind: 'api_key',
        available: true,
        missing_settings: [],
        credential_fields: [
          { key: 'aws_access_key_id', label: 'Access key ID', secret: false },
        ],
      },
    ];
    const props = {
      receivedFile: [],
      setModalState: vi.fn(),
      isOnboarding: false,
      renderTab: null,
      close: vi.fn(),
      initialIngestor: 's3' as const,
    };
    await act(async () => root.render(<Upload {...props} />));
    const triggers = () =>
      Array.from(
        document.body.querySelectorAll('[data-slot="select-trigger"]'),
      ).map((el) => el.textContent);
    expect(triggers()).not.toContain('modals.uploadDoc.newCredentials');
    connectorsState.connections = [
      {
        id: 'k1',
        connector_key: 's3',
        status: 'connected',
        account_label: '…WXYZ',
      },
    ];
    await act(async () => root.render(<Upload {...props} />));
    expect(triggers()).toContain('settings.connectors.detail.keyEnding');
    connectorsState.catalog = [];
    connectorsState.connections = [];
  });

  it("sends the picker's account, not one cleared by the type change", async () => {
    connectorsState.catalog = [
      {
        key: 'google_drive',
        icon: 'drive',
        sync_ingestor: 'google_drive',
        auth_kind: 'oauth',
        available: true,
        missing_settings: [],
      },
    ];
    const sent: FormData[] = [];
    class FakeXhr {
      upload = { addEventListener() {} };
      addEventListener() {}
      open() {}
      setRequestHeader() {}
      send(body: FormData) {
        sent.push(body);
      }
    }
    vi.stubGlobal('XMLHttpRequest', FakeXhr);
    await act(async () =>
      root.render(
        <Upload
          receivedFile={[]}
          setModalState={vi.fn()}
          isOnboarding={false}
          renderTab={null}
          close={vi.fn()}
          initialIngestor="google_drive"
        />,
      ),
    );
    const train = Array.from(document.body.querySelectorAll('button')).find(
      (b) => b.textContent === 'modals.uploadDoc.train',
    )!;
    await act(async () => train.click());
    expect(sent).toHaveLength(1);
    expect(JSON.parse(String(sent[0].get('data'))).connection_id).toBe(
      'drive-1',
    );
    vi.unstubAllGlobals();
    connectorsState.catalog = [];
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
