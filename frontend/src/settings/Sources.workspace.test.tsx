import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

import type { Folder } from '../components/folders/types';
import type { Doc } from '../models/misc';
import type { WorkspaceState } from '../workspace/workspaceSlice';

const store = vi.hoisted(() => ({
  folders: [] as unknown[],
  workspace: {} as unknown,
}));
const moveCalls = vi.hoisted(() => [] as string[]);

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('react-redux', () => ({
  useDispatch: () => vi.fn(),
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({
      preference: { token: null, sourceDocs: [] },
      upload: { tasks: [] },
      graphBuild: { builds: {} },
      connectors: { connections: [], loaded: true, startedSyncs: [] },
      notifications: { recentEvents: [] },
      folders: {
        tree: {
          items: store.folders,
          loaded: true,
          loading: false,
          failed: false,
          latestRequestId: null,
          removedParents: {},
        },
      },
      workspace: store.workspace,
    }),
}));
vi.mock('../hooks', () => ({
  useDebouncedValue: (value: unknown) => value,
  useLoaderState: (initial: boolean) => useState(initial),
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));
vi.mock('../api/services/userService', () => ({ default: {} }));
vi.mock('../api/services/modelService', () => ({
  default: { getModels: vi.fn(), transformModels: vi.fn(() => []) },
}));
vi.mock('../preferences/preferenceApi', () => ({
  getDocs: vi.fn(async () => []),
  getDocsWithPagination: vi.fn(),
}));
vi.mock('./SourceConfigModal', () => ({ default: () => null }));
vi.mock('./TestRetrievalModal', () => ({ default: () => null }));
vi.mock('./ConvertToWikiModal', () => ({ default: () => null }));
vi.mock('./EnableGraphRAGModal', () => ({ default: () => null }));
vi.mock('./components/useRetrievalAvailability', () => ({
  default: () => ({
    graphRAGAvailable: false,
    hybridAvailable: false,
    availableModels: [],
    decision: null,
  }),
}));
// The Share dialog's props, from its last render.
const share = vi.hoisted(() => ({
  props: null as null | { onMoved?: () => void },
}));
vi.mock('../teams/ShareToTeamModal', () => ({
  default: (props: { onMoved?: () => void }) => {
    share.props = props;
    return null;
  },
}));
vi.mock('../connectors/SignInAgainNotice', () => ({
  useSignInAgain: () => ({ reconnect: vi.fn(), modals: null }),
}));
vi.mock('../upload/Upload', () => ({ default: () => null }));
vi.mock('../workspace/move/useMoveToWorkspace', () => {
  const hook = (kind: string) => {
    moveCalls.push(kind);
    return { menuOption: () => null, dialog: null };
  };
  return { default: hook, useMoveToWorkspace: hook };
});

import { getDocsWithPagination } from '../preferences/preferenceApi';
import Sources from './Sources';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const PERSONAL = { id: 'personal', kind: 'personal', name: 'Personal' };
const inWorkspace = (current: 'personal' | 't1', role = 'editor') => {
  store.workspace = {
    current,
    workspaces: [
      PERSONAL,
      { id: 't1', kind: 'team', name: 'Operations', role, member_count: 4 },
    ],
    loaded: true,
    loading: false,
    epoch: 0,
    lastReason: null,
    latestRequestId: null,
  } as WorkspaceState;
};

const doc = (fields: Partial<Doc>): Doc => ({
  date: '',
  model: '',
  name: '',
  ...fields,
});
const ownDoc = doc({
  id: 'own-1',
  name: 'Customs rules',
  origin: 'own',
  access: 'owner',
  allowed_actions: ['use', 'edit', 'share', 'delete', 'move_folder'],
  created_by: { user_id: 'me', label: 'Me' },
});
const sharedDoc = doc({
  id: 'shared-1',
  name: 'Lane pricing notes',
  origin: 'shared',
  access: 'viewer',
  allowed_actions: ['use'],
  created_by: { user_id: 'priya', label: 'Priya' },
});
const teamDoc = doc({
  id: 'team-1',
  name: 'Carrier onboarding pack',
  origin: 'team',
  access: 'editor',
  allowed_actions: ['use', 'edit'],
  created_by: { user_id: 'dana', label: 'Dana' },
});

// Another team's source shared with this team: read and used, never changed.
const receivedDoc = doc({
  id: 'received-1',
  name: 'Sales playbook',
  origin: 'team_shared',
  ownership: 'team',
  access: 'viewer',
  allowed_actions: ['use'],
  workspace: { kind: 'team', team_id: 't1' },
  shared_from: { team_id: 'sales', name: 'Sales' },
  folder_id: null,
});

type Page = {
  docs: Doc[];
  totalDocuments: number;
  totalPages: number;
  currentPage: number;
  nextCursor: string;
  kindCounts?: Record<string, number>;
  originCounts?: { own: number; shared: number };
};
const page = (docs: Doc[], extra: Partial<Page> = {}): Page => ({
  docs,
  totalDocuments: docs.length,
  totalPages: 1,
  currentPage: 1,
  nextCursor: '',
  ...extra,
});

const fetchPage = vi.mocked(getDocsWithPagination);
/** Answers each request by the origin it names. */
const answer = (byOrigin: Record<string, Page>) =>
  fetchPage.mockImplementation(async (...args) => {
    const options = (args[6] ?? {}) as { origin?: string };
    return (byOrigin[options.origin ?? 'all'] ?? page([])) as never;
  });
const origins = () =>
  fetchPage.mock.calls.map(
    (call) => (call[6] as { origin?: string } | undefined)?.origin,
  );

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  localStorage.clear();
  fetchPage.mockReset();
  moveCalls.length = 0;
  store.folders = [];
  inWorkspace('personal');
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = '';
});

/** Renders the page at `entry`; `listed` is the own list the store holds. */
const mount = async (listed: Doc[], entry = '/settings/knowledge') => {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[entry]}>
        <Sources paginatedDocuments={listed} handleDeleteDocument={vi.fn()} />
      </MemoryRouter>,
    );
  });
  // Let the second request (Shared with you) answer.
  await act(async () => undefined);
};

const sharedSection = () =>
  container.querySelector<HTMLElement>('[data-section="shared-with-you"]');
const cardFor = (name: string) =>
  container
    .querySelector<HTMLElement>(`button[aria-label="${name}"]`)
    ?.closest<HTMLElement>('[data-slot="card"]');

describe('Knowledge in Personal', () => {
  it('lists own sources, then asks for the shared ones apart', async () => {
    answer({
      own: page([ownDoc], { originCounts: { own: 1, shared: 1 } }),
      shared: page([sharedDoc]),
    });
    await mount([ownDoc]);
    expect(origins()).toEqual(['own', 'shared']);
    const section = sharedSection();
    expect(section?.textContent).toContain('workspace.page.sharedWithYou');
    expect(section?.textContent).toContain('Lane pricing notes');
    expect(section?.textContent).not.toContain('Customs rules');
  });

  it("names a shared source's owner and the reader's role", async () => {
    answer({
      own: page([ownDoc], { originCounts: { own: 1, shared: 1 } }),
      shared: page([sharedDoc]),
    });
    await mount([ownDoc]);
    const shared = cardFor('Lane pricing notes')!;
    expect(
      shared.querySelector('[data-testid="creator-meta"]')?.textContent,
    ).toBe('Priya');
    expect(shared.querySelector('[data-testid="role-meta"]')).not.toBeNull();
    const mine = cardFor('Customs rules')!;
    expect(mine.querySelector('[data-testid="creator-meta"]')).toBeNull();
    expect(mine.querySelector('[data-testid="role-meta"]')).toBeNull();
  });

  it('asks for nothing shared when nothing is', async () => {
    answer({ own: page([ownDoc], { originCounts: { own: 1, shared: 0 } }) });
    await mount([ownDoc]);
    expect(origins()).toEqual(['own']);
    expect(sharedSection()).toBeNull();
  });

  it('has no Shared kind chip, and counts shared sources in the kinds', async () => {
    answer({
      own: page([ownDoc], {
        originCounts: { own: 1, shared: 1 },
        kindCounts: {
          all: 1,
          files: 1,
          websites: 0,
          synced: 0,
          wikis: 0,
          shared: 0,
        },
      }),
      shared: page([sharedDoc], {
        kindCounts: {
          all: 1,
          files: 0,
          websites: 1,
          synced: 0,
          wikis: 0,
          shared: 1,
        },
      }),
    });
    await mount([ownDoc]);
    const chips = Array.from(
      container.querySelectorAll('[data-slot="toggle-group-item"]'),
    ).map((item) => [
      item.firstChild?.textContent,
      item.querySelector('[data-slot="count"]')?.textContent,
    ]);
    expect(chips).toEqual([
      ['settings.sources.kinds.all', '2'],
      ['settings.sources.kinds.files', '1'],
      ['settings.sources.kinds.websites', '1'],
    ]);
  });

  it('lists everything filed in an open folder, and nothing apart', async () => {
    store.folders = [
      {
        id: 'f1',
        name: 'Carriers',
        parent_id: null,
        counts: { source: 2 },
      } as Folder,
    ];
    answer({ all: page([ownDoc, sharedDoc]) });
    await mount([ownDoc, sharedDoc], '/settings/knowledge?folder=f1');
    expect(origins()).toEqual([undefined]);
    expect(sharedSection()).toBeNull();
  });

  it('offers Move to team in the source menus', async () => {
    answer({ own: page([ownDoc]) });
    await mount([ownDoc]);
    expect(moveCalls).toContain('source');
  });

  it('shows the workspace line under the intro', async () => {
    answer({ own: page([ownDoc]) });
    await mount([ownDoc]);
    expect(
      container.querySelector('[data-testid="workspace-line"]'),
    ).not.toBeNull();
  });
});

describe('Knowledge in a team', () => {
  it("asks for other teams' sources apart and lists them as Shared with this team", async () => {
    inWorkspace('t1');
    answer({
      own: page([teamDoc], { originCounts: { own: 1, shared: 1 } }),
      shared: page([receivedDoc]),
    });
    await mount([teamDoc]);
    expect(origins()).toEqual(['own', 'shared']);
    const section = sharedSection();
    expect(section?.textContent).toContain(
      'workspace.page.sharedFromTeams.title',
    );
    expect(section?.textContent).not.toContain('workspace.page.sharedWithYou');
    expect(section?.textContent).toContain('Sales playbook');
    const tile = cardFor('Sales playbook')!;
    expect(
      tile.querySelector('[data-testid="shared-from-meta"]'),
    ).not.toBeNull();
    expect(tile.querySelector('[data-testid="role-meta"]')).toBeNull();
    // It is read and used; nothing edits, files, moves or deletes it.
    const labels = (await openSourceMenu('received-1')).map(
      (i) => i.textContent,
    );
    for (const refused of [
      'settings.sources.editConfig',
      'folders.moveToFolder',
      'settings.sources.delete',
    ])
      expect(labels).not.toContain(refused);
  });

  it('asks for nothing apart while no other team shares a source', async () => {
    inWorkspace('t1');
    answer({ own: page([teamDoc], { originCounts: { own: 1, shared: 0 } }) });
    await mount([teamDoc]);
    expect(origins()).toEqual(['own']);
    expect(sharedSection()).toBeNull();
  });

  it('names who added a team source, with no role', async () => {
    inWorkspace('t1');
    answer({ own: page([teamDoc]) });
    await mount([teamDoc]);
    const tile = cardFor('Carrier onboarding pack')!;
    expect(
      tile.querySelector('[data-testid="creator-meta"]')?.textContent,
    ).toBe('Dana');
    expect(tile.querySelector('[data-testid="role-meta"]')).toBeNull();
  });

  it('gives a Viewer no Add knowledge or New folder', async () => {
    inWorkspace('t1', 'viewer');
    answer({ own: page([]) });
    await mount([]);
    const labels = Array.from(container.querySelectorAll('button')).map(
      (b) => b.textContent,
    );
    expect(labels).not.toContain('settings.sources.addSource');
    expect(labels).not.toContain('folders.newFolder');
  });

  it('gives an Editor Add knowledge', async () => {
    inWorkspace('t1', 'editor');
    answer({ own: page([teamDoc]) });
    await mount([teamDoc]);
    const labels = Array.from(container.querySelectorAll('button')).map(
      (b) => b.textContent,
    );
    expect(labels).toContain('settings.sources.addSource');
  });
});

/** Opens a source's ⋯; returns its items. */
const openSourceMenu = async (id: string) => {
  const trigger = document.querySelector<HTMLButtonElement>(
    `[data-testid="menu-button-${id}"]`,
  )!;
  await act(async () => {
    trigger.dispatchEvent(
      new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
    );
    trigger.click();
  });
  return Array.from(
    document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
  );
};

describe('Share on a source', () => {
  it("is offered on a team's source to a Viewer, to see who has access", async () => {
    inWorkspace('t1', 'viewer');
    const viewed = { ...teamDoc, access: 'viewer', allowed_actions: ['use'] };
    answer({ own: page([viewed as Doc]) });
    await mount([viewed as Doc]);
    const labels = (await openSourceMenu('team-1')).map((i) => i.textContent);
    expect(labels).toContain('settings.sources.shareWithTeam');
  });

  it("reloads the list when the dialog's offer moves the source", async () => {
    // Not a plain assignment, which would narrow `props` to null below.
    Object.assign(share, { props: null });
    answer({ own: page([ownDoc]) });
    await mount([ownDoc]);
    const item = (await openSourceMenu('own-1')).find(
      (i) => i.textContent === 'settings.sources.shareWithTeam',
    )!;
    await act(async () => item.click());
    expect(share.props?.onMoved).toBeTypeOf('function');
    const loads = fetchPage.mock.calls.length;
    await act(async () => share.props!.onMoved!());
    expect(fetchPage.mock.calls.length).toBeGreaterThan(loads);
  });
});

describe('Knowledge folders by kind', () => {
  it('shows folders holding sources or nothing, not prompt-only ones', async () => {
    store.folders = [
      { id: 'f1', name: 'Carriers', parent_id: null, counts: { source: 2 } },
      { id: 'f2', name: 'Intake', parent_id: null, counts: { prompt: 1 } },
      { id: 'f3', name: 'New', parent_id: null, counts: {} },
    ] as Folder[];
    answer({ own: page([ownDoc]) });
    await mount([ownDoc]);
    const tiles = Array.from(
      container.querySelectorAll<HTMLElement>('[data-folder-tile]'),
    ).map((el) => el.dataset.folderTile);
    expect(tiles).toEqual(['f1', 'f3']);
  });
});
