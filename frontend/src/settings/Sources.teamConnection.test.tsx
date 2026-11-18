import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

import type { Connection } from '../connectors/types';
import type { Doc } from '../models/misc';

// A team source that syncs through an account connected for the team: its
// card and view read that account from the team's list, not the reader's
// own, and only whoever may manage it (an Admin) gets Reconnect.

const store = vi.hoisted(() => ({
  personal: [] as unknown[],
  team: [] as unknown[],
  knowledge: [] as unknown[],
}));
const reconnect = vi.hoisted(() => vi.fn());

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => {
      if (!options) return key;
      const params = Object.entries(options)
        .filter(([name]) => name !== 'interpolation')
        .map(([name, value]) => `${name}=${value}`)
        .join(',');
      return `${key}(${params})`;
    },
    i18n: { language: 'en' },
  }),
}));
vi.mock('react-redux', () => ({
  useDispatch: () => vi.fn(),
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({
      preference: { token: null, sourceDocs: store.knowledge },
      upload: { tasks: [] },
      graphBuild: { builds: {} },
      connectors: {
        connections: store.personal,
        catalog: [],
        loaded: true,
        startedSyncs: [],
        teams: {
          t1: {
            catalog: [],
            connections: store.team,
            loaded: true,
            loading: false,
            failed: false,
            latestRequestId: null,
          },
        },
      },
      notifications: { recentEvents: [] },
      folders: {
        tree: {
          items: [],
          loaded: true,
          loading: false,
          failed: false,
          latestRequestId: null,
          removedParents: {},
        },
      },
      workspace: {
        current: 't1',
        workspaces: [
          { id: 'personal', kind: 'personal', name: 'Personal' },
          { id: 't1', kind: 'team', name: 'Operations', role: 'admin' },
        ],
        loaded: true,
        loading: false,
        epoch: 0,
        lastReason: null,
        latestRequestId: null,
      },
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
vi.mock('../teams/ShareToTeamModal', () => ({ default: () => null }));
vi.mock('../connectors/SignInAgainNotice', () => ({
  useSignInAgain: () => ({ reconnect, modals: null }),
}));
vi.mock('../upload/Upload', () => ({ default: () => null }));
vi.mock('../workspace/move/useMoveToWorkspace', () => {
  const hook = () => ({ menuOption: () => null, dialog: null });
  return { default: hook, useMoveToWorkspace: hook };
});
// The opened source's view only has to show the badge it was given.
vi.mock('../components/ConnectorTree', () => ({
  default: ({ connection }: { connection?: { name: string } }) => (
    <div data-testid="connector-tree">{connection?.name ?? 'no-badge'}</div>
  ),
}));
vi.mock('../components/Chunks', () => ({
  default: () => <div data-testid="chunks" />,
}));

import { getDocsWithPagination } from '../preferences/preferenceApi';
import Sources from './Sources';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const ADMIN = ['view', 'sync', 'manage'];
const EDITOR = ['view', 'sync'];

const teamConnection = (
  status: string,
  allowed: string[],
  extra: Partial<Connection> = {},
): Connection =>
  ({
    id: 'team-conn',
    connector_key: 'google_drive',
    name: 'Team Drive',
    icon: 'google_drive',
    status,
    owner: 'team',
    team_id: 't1',
    connected_by: { user_id: 'lena', label: 'Lena' },
    allowed_actions: allowed,
    ...extra,
  }) as unknown as Connection;

const teamDoc = (fields: Partial<Doc> = {}): Doc =>
  ({
    id: 'team-1',
    name: 'Carrier onboarding pack',
    date: '',
    model: '',
    type: 'connector:file',
    isNested: true,
    connectionId: 'team-conn',
    origin: 'team',
    access: 'editor',
    allowed_actions: ['use', 'edit'],
    workspace: { kind: 'team', team_id: 't1' },
    created_by: { user_id: 'dana', label: 'Dana' },
    sync_paused: null,
    ...fields,
  }) as Doc;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  localStorage.clear();
  reconnect.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = '';
  store.personal = [];
  store.team = [];
  store.knowledge = [];
  vi.mocked(getDocsWithPagination).mockReset();
});

const mount = async (doc: Doc) => {
  vi.mocked(getDocsWithPagination).mockResolvedValue({
    docs: [doc],
    totalDocuments: 1,
    totalPages: 1,
    currentPage: 1,
    nextCursor: '',
  } as never);
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={['/settings/knowledge']}>
        <Sources paginatedDocuments={[doc]} handleDeleteDocument={vi.fn()} />
      </MemoryRouter>,
    );
  });
  await act(async () => undefined);
};

const card = () =>
  container
    .querySelector<HTMLElement>('button[aria-label="Carrier onboarding pack"]')
    ?.closest<HTMLElement>('[data-slot="card"]');
const reconnectBadge = () =>
  Array.from(card()?.querySelectorAll('[data-slot="badge"]') ?? []).find(
    (b) => b.textContent === 'settings.connectors.status.reconnect',
  );
const reconnectButton = () =>
  Array.from(card()?.querySelectorAll('button') ?? []).find(
    (b) => b.textContent === 'settings.connectors.status.reconnect',
  );
const pausedLine = () =>
  card()?.querySelector('[data-sync-paused]')?.textContent ?? null;

describe("a team source on the team's account", () => {
  it("names the team's account on its card and in its view", async () => {
    store.team = [teamConnection('connected', EDITOR)];
    await mount(teamDoc());
    expect(card()?.textContent).toContain(
      'settings.sources.viaConnection(name=Team Drive)',
    );
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>(
          'button[aria-label="Carrier onboarding pack"]',
        )!
        .click(),
    );
    expect(
      container.querySelector('[data-testid="connector-tree"]')?.textContent,
    ).toBe('Team Drive');
  });

  // A team source never reads through a personal account, so one with the
  // same id in the reader's own list is not its account.
  it("does not look in the reader's own list in a team", async () => {
    store.personal = [
      { ...teamConnection('reconnect_needed', ADMIN), owner: 'user' },
    ];
    await mount(teamDoc());
    expect(card()?.textContent).not.toContain('settings.sources.viaConnection');
    expect(reconnectBadge()).toBeUndefined();
    expect(reconnectButton()).toBeUndefined();
  });

  it('offers an Admin Reconnect when it needs signing in again', async () => {
    const connection = teamConnection('reconnect_needed', ADMIN);
    store.team = [connection];
    await mount(teamDoc());
    expect(reconnectBadge()?.getAttribute('data-variant')).toBe('warning');
    const button = reconnectButton();
    expect(button).toBeDefined();
    await act(async () => button!.click());
    // The team's row, so the wizard reconnects it as the team's.
    expect(reconnect).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'team-conn', owner: 'team' }),
    );
  });

  it('shows an Editor that it needs signing in again, without Reconnect', async () => {
    store.team = [teamConnection('reconnect_needed', EDITOR)];
    await mount(teamDoc());
    expect(reconnectBadge()).toBeDefined();
    expect(reconnectButton()).toBeUndefined();
  });

  it('shows a paused account as paused, not as needing a sign-in', async () => {
    store.team = [
      teamConnection('paused', EDITOR, {
        paused_for: { reason: 'payer_left', until: null, left_team: true },
      }),
    ];
    await mount(teamDoc());
    expect(pausedLine()).toBe(
      'settings.connectors.team.paused(reason=payer.common.pause.payerLeftTeam(name=Lena,team=Operations))',
    );
    expect(reconnectBadge()).toBeUndefined();
    expect(reconnectButton()).toBeUndefined();
  });

  it("keeps the source's own pause line when the server sent one", async () => {
    store.team = [
      teamConnection('paused', EDITOR, {
        paused_for: { reason: 'payer_left', until: null, left_team: true },
      }),
    ];
    await mount(
      teamDoc({
        sync_paused: {
          reason: 'payer_left',
          until: null,
          left_team: true,
          connection_id: 'team-conn',
        },
      } as Partial<Doc>),
    );
    expect(pausedLine()).toBe(
      'settings.sources.syncPaused.account(reason=payer.common.pause.payerLeftTeam(name=Lena,team=Operations))',
    );
  });

  it('lets an Admin reconnect a paused account with their own', async () => {
    store.team = [
      teamConnection('paused', ADMIN, {
        paused_for: { reason: 'payer_left', until: null, left_team: true },
      }),
    ];
    await mount(teamDoc());
    expect(reconnectBadge()).toBeUndefined();
    const button = reconnectButton();
    expect(button).toBeDefined();
    await act(async () => button!.click());
    expect(reconnect).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'team-conn', owner: 'team' }),
    );
  });
});

describe('needs attention in a team', () => {
  /** The first section's eyebrow, when it is Needs attention. */
  const attention = () =>
    Array.from(container.querySelectorAll('section h2')).some((h) =>
      h.textContent?.startsWith('settings.sources.needsAttention'),
    );

  it.each([
    ['an Admin, signed out', 'reconnect_needed', ADMIN, true],
    ['an Admin, paused', 'paused', ADMIN, true],
    ['an Editor, signed out', 'reconnect_needed', EDITOR, false],
    ['an Editor, paused', 'paused', EDITOR, false],
    ['an Admin, connected', 'connected', ADMIN, false],
  ])('lists the source for %s: %s', async (_, status, allowed, shown) => {
    store.team = [teamConnection(status, allowed)];
    const doc = teamDoc();
    store.knowledge = [doc];
    await mount(doc);
    expect(attention()).toBe(shown);
  });
});
