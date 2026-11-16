import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

import type { Doc } from '../models/misc';
import type { SourceSyncPaused } from '../payer/types';

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
      preference: { token: null, sourceDocs: [] },
      upload: { tasks: [] },
      graphBuild: { builds: {} },
      connectors: { connections: [], loaded: true, startedSyncs: [] },
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
          { id: 't1', kind: 'team', name: 'Operations', role: 'editor' },
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
  useSignInAgain: () => ({ reconnect: vi.fn(), modals: null }),
}));
vi.mock('../upload/Upload', () => ({ default: () => null }));
vi.mock('../workspace/move/useMoveToWorkspace', () => {
  const hook = () => ({ menuOption: () => null, dialog: null });
  return { default: hook, useMoveToWorkspace: hook };
});
// The source's own view is tested on its own; here it only has to open.
vi.mock('../components/Chunks', () => ({
  default: () => <div data-testid="chunks" />,
}));

import { getDocsWithPagination } from '../preferences/preferenceApi';
import Sources from './Sources';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const THIS_YEAR = new Date().getFullYear();

const teamDoc = (syncPaused: SourceSyncPaused | null): Doc =>
  ({
    id: 'team-1',
    name: 'Carrier onboarding pack',
    date: '',
    model: '',
    type: 'remote',
    syncFrequency: 'daily',
    origin: 'team',
    access: 'editor',
    allowed_actions: ['use', 'edit'],
    workspace: { kind: 'team', team_id: 't1' },
    created_by: { user_id: 'dana', label: 'Dana' },
    sync_paused: syncPaused,
  }) as Doc;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  localStorage.clear();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = '';
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

describe('a team source whose scheduled sync nobody can pay for', () => {
  it('says so on its card, in the warning tone', async () => {
    await mount(teamDoc({ reason: 'sync_no_payer', since: null }));
    const line = card()?.querySelector('[data-sync-paused]');
    expect(line?.textContent).toBe('settings.sources.syncPaused.noPayer');
    expect(line?.className).toContain('text-warning');
  });

  it('adds since when', async () => {
    await mount(
      teamDoc({
        reason: 'sync_no_payer',
        since: `${THIS_YEAR}-11-12T08:00:00Z`,
      }),
    );
    expect(card()?.querySelector('[data-sync-paused]')?.textContent).toMatch(
      /^settings\.sources\.syncPaused\.noPayerSince\(date=.+\)$/,
    );
  });

  it('words a reason it does not know plainly', async () => {
    await mount(teamDoc({ reason: 'sync_something_else', since: null }));
    expect(card()?.querySelector('[data-sync-paused]')?.textContent).toBe(
      'settings.sources.syncPaused.other',
    );
  });

  it('says nothing when the sync runs', async () => {
    await mount(teamDoc(null));
    expect(card()).toBeTruthy();
    expect(container.querySelector('[data-sync-paused]')).toBeNull();
  });

  it('says so above the opened source', async () => {
    await mount(teamDoc({ reason: 'sync_no_payer', since: null }));
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>(
          'button[aria-label="Carrier onboarding pack"]',
        )!
        .click(),
    );
    expect(container.querySelector('[data-testid="chunks"]')).not.toBeNull();
    const alert = container.querySelector('[data-variant="warning"]');
    expect(alert?.textContent).toContain('settings.sources.syncPaused.noPayer');
  });
});
