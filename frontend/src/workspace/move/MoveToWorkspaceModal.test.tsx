import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../hooks')>()),
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));
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
  }),
}));

const api = vi.hoisted(() => ({
  list: vi.fn(),
  planMove: vi.fn(),
  applyMove: vi.fn(),
}));
vi.mock('../../api/services/workspacesService', () => ({ default: api }));

const userApi = vi.hoisted(() => ({ getFolders: vi.fn(), getDocs: vi.fn() }));
vi.mock('../../api/services/userService', () => ({ default: userApi }));

import type {
  CannotMoveReason,
  MovePlan,
} from '../../api/services/workspacesService';
import foldersReducer from '../../components/folders/foldersSlice';
import type { MenuOption } from '../../components/ui/dropdown-menu';
import actionToastReducer from '../../notifications/actionToastSlice';
import workspaceReducer, {
  PERSONAL_ROW,
  type WorkspaceRole,
} from '../workspaceSlice';
import MoveToWorkspaceModal from './MoveToWorkspaceModal';
import { moveDirection } from './moveTargets';
import useMoveToWorkspace, { type MovableItem } from './useMoveToWorkspace';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const REASONS: CannotMoveReason[] = [
  'connection_account',
  'connector_synced',
  'custom_model',
  'remote_device',
  'not_yours',
  'in_knowledge_folder',
  'credentials_unreadable',
];

const fullPlan = (over: Partial<MovePlan> = {}): MovePlan => ({
  to: {
    workspace: { kind: 'team', team_id: 't1', name: 'Operations' },
    folder: null,
  },
  items: [{ type: 'agent', id: 'a1', name: 'Carrier rate desk' }],
  moves_with: [
    {
      type: 'source',
      id: 's1',
      name: 'Carrier rate sheets Q4',
      via: { type: 'agent', id: 'a1' },
      reason: 'used_by_agent',
    },
    {
      type: 'agent',
      id: 'a2',
      name: 'Tender helper',
      via: { type: 'agent', id: 'a1' },
      reason: 'same_workflow',
    },
    {
      type: 'folder',
      id: 'f1',
      name: 'Lanes',
      via: { type: 'agent', id: 'a1' },
      reason: 'used_by_agent',
    },
    {
      type: 'source',
      id: 's2',
      name: 'Lane sheet',
      via: { type: 'folder', id: 'f1' },
      reason: 'in_folder',
    },
  ],
  cannot_move: REASONS.map((reason, index) => ({
    type: reason === 'custom_model' ? 'model' : 'tool',
    id: `c${index}`,
    name: `Blocked ${reason}`,
    reason,
    effect: index % 2 ? 'stays' : 'removed_from_holder',
  })),
  access: {
    gains: { total: 12, viewers: 5, editors: 5, admins: 2 },
    loses: [{ user_id: 'u9', label: 'priya@meridian.example', via: 'Sales' }],
  },
  kept: {
    schedules: [
      {
        id: 'sc1',
        agent_id: 'a1',
        paid_by: { user_id: 'u2', label: 'dana@meridian.example' },
      },
    ],
    outside_access: {
      api_key: true,
      public_link: false,
      webhook: false,
      paid_by: { user_id: 'u2', label: 'dana@meridian.example' },
    },
  },
  borrowing_agents: [],
  borrowing_others: 0,
  needs_admin: [],
  conversations_switched: 3,
  renames: [
    { type: 'folder', id: 'f1', from: 'Lanes', to: 'Lanes (2)' },
    {
      type: 'agent',
      id: 'a1',
      field: 'slug',
      from: 'rate-desk',
      to: 'rate-desk-2',
    },
  ],
  fingerprint: 'fp1',
  ...over,
});

const json = (body: unknown, ok = true, status = 200) =>
  Promise.resolve({ ok, status, json: () => Promise.resolve(body) });

const workspaceState = (
  current = 'personal',
  role: WorkspaceRole = 'admin',
) => ({
  current,
  workspaces: [
    PERSONAL_ROW,
    { id: 't1', kind: 'team' as const, name: 'Operations', role },
    { id: 't2', kind: 'team' as const, name: 'Sales', role: 'viewer' as const },
  ],
  loaded: true,
  loading: false,
  epoch: 0,
  lastReason: null,
  latestRequestId: null,
});

const makeStore = (current = 'personal', role: WorkspaceRole = 'admin') =>
  configureStore({
    reducer: {
      preference: () => ({ token: 'tok' }),
      folders: foldersReducer,
      actionToast: actionToastReducer,
      workspace: workspaceReducer,
    },
    preloadedState: { workspace: workspaceState(current, role) },
  });

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  userApi.getFolders.mockReset();
  userApi.getFolders.mockImplementation(() =>
    json({ folders: [{ id: 'tf1', name: 'Carriers', parent_id: null }] }),
  );
  userApi.getDocs.mockReset();
  userApi.getDocs.mockImplementation(() => json([]));
  api.planMove.mockResolvedValue({ ok: true, status: 200, plan: fullPlan() });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  document.body.innerHTML = '';
});

const flush = async () => {
  for (let i = 0; i < 8; i += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
};

const text = () => document.body.textContent ?? '';
const submit = () =>
  Array.from(document.body.querySelectorAll('button')).find((b) =>
    b.textContent?.startsWith('workspace.move.submit'),
  ) as HTMLButtonElement | undefined;

const render = async (
  props: Partial<React.ComponentProps<typeof MoveToWorkspaceModal>> = {},
  store = makeStore(),
) => {
  const onClose = vi.fn();
  const onMoved = vi.fn();
  act(() => {
    root.render(
      <Provider store={store}>
        <MemoryRouter>
          <MoveToWorkspaceModal
            subject={{ type: 'agent', id: 'a1', name: 'Carrier rate desk' }}
            onClose={onClose}
            onMoved={onMoved}
            {...props}
          />
        </MemoryRouter>
      </Provider>,
    );
  });
  await flush();
  return { onClose, onMoved, store };
};

describe('MoveToWorkspaceModal', () => {
  it('plans a move into the first team the caller can add to', async () => {
    await render();
    expect(api.planMove).toHaveBeenCalledWith(
      {
        to: { workspace: 't1', folder_id: null },
        items: [{ type: 'agent', id: 'a1' }],
      },
      { token: 'tok' },
    );
    // The target folder list is the team's own tree.
    expect(userApi.getFolders).toHaveBeenCalledWith('tok', {
      workspace: 't1',
    });
  });

  it('moves out to Personal from a team item', async () => {
    await render(
      { from: { kind: 'team', team_id: 't1' } },
      makeStore('t1', 'admin'),
    );
    expect(api.planMove).toHaveBeenCalledWith(
      {
        to: { workspace: 'personal', folder_id: null },
        items: [{ type: 'agent', id: 'a1' }],
      },
      { token: 'tok' },
    );
    expect(userApi.getFolders).toHaveBeenCalledWith('tok', {
      workspace: 'personal',
    });
  });

  it('starts at the team the share dialog offered', async () => {
    const store = makeStore();
    await render({ initialTeamId: 't1' }, store);
    expect(api.planMove.mock.calls[0][0].to.workspace).toBe('t1');
  });

  it('renders every part of the plan', async () => {
    await render();
    const page = text();
    expect(page).toContain('workspace.move.access.gains(count=12');
    expect(page).toContain('workspace.move.access.gainsDetail');
    expect(page).toContain('priya@meridian.example');
    expect(page).toContain('workspace.move.owner.team');
    expect(page).toContain('workspace.move.pays.title');
    expect(page).toContain('workspace.move.pays.schedules');
    expect(page).toContain('dana@meridian.example');
    expect(page).toContain('workspace.move.pays.outside');
    expect(page).toContain('workspace.move.outside.apiKey');
    // What comes along, grouped by what brings it.
    expect(page).toContain('workspace.move.comesWith(name=Carrier rate desk)');
    expect(page).toContain('workspace.move.comesWith(name=Lanes)');
    expect(page).toContain('Carrier rate sheets Q4');
    expect(page).toContain('Lane sheet');
    expect(page).toContain('workspace.move.withReasons.used_by_agent');
    expect(page).toContain('workspace.move.withReasons.same_workflow');
    expect(page).toContain('workspace.move.withReasons.in_folder');
    REASONS.forEach((reason) => {
      expect(page).toContain(`Blocked ${reason}`);
      expect(page).toContain(`workspace.move.reasons.${reason}`);
    });
    expect(page).toContain('workspace.move.effects.removed_from_holder');
    expect(page).toContain('workspace.move.effects.stays');
    expect(page).toContain('workspace.move.kinds.model');
    expect(page).toContain('workspace.move.renames.folder');
    expect(page).toContain('workspace.move.renames.slug');
    expect(page).toContain('workspace.move.chats.in(count=3');
    expect(submit()?.disabled).toBe(false);
  });

  it('names an item it can only count', async () => {
    api.planMove.mockResolvedValue({
      ok: true,
      status: 200,
      plan: fullPlan({
        cannot_move: [
          {
            type: 'tool',
            id: 'x',
            name: null as unknown as string,
            reason: 'not_yours',
            effect: 'removed_from_holder',
          },
        ],
      }),
    });
    await render();
    expect(text()).toContain('workspace.move.unnamed');
  });

  it('confirms with the plan fingerprint', async () => {
    api.applyMove.mockResolvedValue({
      ok: true,
      status: 200,
      plan: fullPlan(),
    });
    await render();
    act(() => submit()!.click());
    await flush();
    expect(api.applyMove).toHaveBeenCalledWith(
      {
        to: { workspace: 't1', folder_id: null },
        items: [{ type: 'agent', id: 'a1' }],
        fingerprint: 'fp1',
      },
      { token: 'tok' },
    );
  });

  it('after a move reloads the folder tree, tells the page and offers the team', async () => {
    api.applyMove.mockResolvedValue({
      ok: true,
      status: 200,
      plan: fullPlan(),
    });
    const { onMoved } = await render();
    userApi.getFolders.mockClear();
    act(() => submit()!.click());
    await flush();
    expect(onMoved).toHaveBeenCalledTimes(1);
    // The current workspace's tree, without a header override.
    expect(userApi.getFolders).toHaveBeenCalledWith('tok');
    expect(text()).toContain('workspace.move.done.team');
    expect(text()).toContain('workspace.move.openIn(name=Operations)');
  });

  it("after a move reads the app's knowledge list again, without what left", async () => {
    api.applyMove.mockResolvedValue({
      ok: true,
      status: 200,
      plan: fullPlan(),
    });
    const store = configureStore({
      reducer: {
        preference: (
          state: { token: string; sourceDocs: unknown } = {
            token: 'tok',
            sourceDocs: [{ id: 's1' }],
          },
          action: { type: string; payload?: unknown },
        ) =>
          action.type === 'preference/setSourceDocs'
            ? { ...state, sourceDocs: action.payload }
            : state,
        folders: foldersReducer,
        actionToast: actionToastReducer,
        workspace: workspaceReducer,
      },
      preloadedState: { workspace: workspaceState('personal', 'admin') },
    });
    await render({}, store as never);
    userApi.getDocs.mockImplementation(() => json([{ id: 's2' }]));
    act(() => submit()!.click());
    await flush();
    // The agent's source went with it: the pickers stop offering it here.
    expect(userApi.getDocs).toHaveBeenCalledWith('tok');
    expect(
      (store.getState().preference as { sourceDocs: unknown }).sourceDocs,
    ).toEqual([{ id: 's2' }]);
  });

  it('swaps in the fresh plan when it changed', async () => {
    api.applyMove
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        error: 'move_plan_changed',
        message: '',
        body: {
          plan: fullPlan({
            fingerprint: 'fp2',
            items: [{ type: 'agent', id: 'a1', name: 'Carrier desk v2' }],
            conversations_switched: 7,
          }),
        },
      })
      .mockResolvedValueOnce({ ok: true, status: 200, plan: fullPlan() });
    await render();
    act(() => submit()!.click());
    await flush();
    expect(text()).toContain('workspace.move.planChanged');
    expect(text()).toContain('workspace.move.chats.in(count=7');
    act(() => submit()!.click());
    await flush();
    expect(api.applyMove.mock.calls[1][0].fingerprint).toBe('fp2');
  });

  it('disables the move while an agent needs an Admin, and says why', async () => {
    api.planMove.mockResolvedValue({
      ok: true,
      status: 200,
      plan: fullPlan({
        needs_admin: [{ id: 'a1', name: 'Carrier rate desk' }],
      }),
    });
    await render();
    expect(submit()?.disabled).toBe(true);
    expect(text()).toContain('workspace.move.needsAdmin');
  });

  it('disables the move into a locked team while an agent has outside access, and says why', async () => {
    api.planMove.mockResolvedValue({
      ok: true,
      status: 200,
      plan: fullPlan({
        team_locked_agents: [{ id: 'a1', name: 'Carrier rate desk' }],
      }),
    });
    await render();
    expect(submit()?.disabled).toBe(true);
    expect(text()).toContain('workspace.move.teamLocked');
    expect(text()).toContain('Carrier rate desk');
  });

  it("lists what the agent keeps through another team's share", async () => {
    api.planMove.mockResolvedValue({
      ok: true,
      status: 200,
      plan: fullPlan({
        shared_refs: [
          {
            type: 'source',
            id: 's9',
            name: 'Sales playbook',
            shared_from: { team_id: 't2', name: 'Sales' },
          },
        ],
      }),
    });
    await render();
    expect(text()).toContain('workspace.move.sharedRefs.title');
    expect(text()).toContain('Sales playbook');
    expect(text()).toContain('workspace.move.sharedRefs.from(team=Sales)');
    expect(submit()?.disabled).toBe(false);
  });

  it("says which custom model the team's match replaces, and how to keep one without a match", async () => {
    api.planMove.mockResolvedValue({
      ok: true,
      status: 200,
      plan: fullPlan({
        model_remaps: [
          {
            from_id: 'm1',
            from_name: 'Mistral',
            to_id: 'm2',
            to_name: 'Ops Mistral',
          },
        ],
      }),
    });
    await render();
    expect(text()).toContain('workspace.move.modelRemaps.title');
    expect(text()).toContain(
      'workspace.move.modelRemaps.in(from=Mistral,to=Ops Mistral)',
    );
    expect(text()).toContain('workspace.move.customModelHint');
  });

  it("names a team's custom model without a match going out, with no hint", async () => {
    api.planMove.mockResolvedValue({
      ok: true,
      status: 200,
      plan: fullPlan({
        to: {
          workspace: { kind: 'personal', team_id: null, name: 'Personal' },
          folder: null,
        },
      }),
    });
    await render(
      { from: { kind: 'team', team_id: 't1' } },
      makeStore('t1', 'admin'),
    );
    expect(text()).toContain('workspace.move.reasons.custom_model_out');
    expect(text()).not.toContain('workspace.move.customModelHint');
    expect(text()).not.toContain('workspace.move.modelRemaps.title');
  });

  it('lists the shares with other teams a move out ends', async () => {
    api.planMove.mockResolvedValue({
      ok: true,
      status: 200,
      plan: fullPlan({
        to: {
          workspace: { kind: 'personal', team_id: null, name: 'Personal' },
          folder: null,
        },
        dropped_shares: [
          {
            type: 'agent',
            id: 'a1',
            name: 'Carrier rate desk',
            team_id: 't2',
            team_name: 'Sales',
          },
        ],
      }),
    });
    await render(
      { from: { kind: 'team', team_id: 't1' } },
      makeStore('t1', 'admin'),
    );
    expect(text()).toContain('workspace.move.droppedShares.title');
    expect(text()).toContain('workspace.move.droppedShares.with(team=Sales)');
  });

  it('says a locked team keeps its items in when the plan is refused', async () => {
    api.planMove.mockResolvedValue({
      ok: false,
      status: 403,
      error: 'team_locked',
      message: '',
      body: {},
    });
    await render(
      { from: { kind: 'team', team_id: 't1' } },
      makeStore('t1', 'admin'),
    );
    expect(text()).toContain(
      'workspace.move.errors.team_locked(team=Operations)',
    );
    expect(submit()?.disabled).toBe(true);
  });

  it('disables the move while a published agent would borrow, and says why', async () => {
    api.planMove.mockResolvedValue({
      ok: true,
      status: 200,
      plan: fullPlan({
        borrowing_agents: [{ id: 'a9', name: 'Public bot', published: true }],
      }),
    });
    await render();
    expect(submit()?.disabled).toBe(true);
    expect(text()).toContain('workspace.move.borrow.in');
    expect(text()).toContain('Public bot');
  });

  it('disables the move while agents the caller can not open would borrow', async () => {
    api.planMove.mockResolvedValue({
      ok: true,
      status: 200,
      plan: fullPlan({ borrowing_others: 2 }),
    });
    await render();
    expect(submit()?.disabled).toBe(true);
    expect(text()).toContain('workspace.move.othersYouCantOpen(count=2');
  });

  it('lets a move in go ahead when the borrowing agents are not published', async () => {
    api.planMove.mockResolvedValue({
      ok: true,
      status: 200,
      plan: fullPlan({
        borrowing_agents: [{ id: 'a9', name: 'My helper', published: false }],
      }),
    });
    await render();
    expect(submit()?.disabled).toBe(false);
    expect(text()).toContain('workspace.move.borrow.keeps');
  });

  it('blocks a move out while a team agent still uses what leaves', async () => {
    api.planMove.mockResolvedValue({
      ok: true,
      status: 200,
      plan: fullPlan({
        to: {
          workspace: { kind: 'personal', team_id: null, name: 'Personal' },
          folder: null,
        },
        borrowing_agents: [{ id: 'a9', name: 'Team bot', published: false }],
      }),
    });
    await render(
      { from: { kind: 'team', team_id: 't1' } },
      makeStore('t1', 'admin'),
    );
    expect(submit()?.disabled).toBe(true);
    expect(text()).toContain('workspace.move.borrow.out');
  });

  it('shows a failed move in an Alert and stays open', async () => {
    api.applyMove.mockResolvedValue({
      ok: false,
      status: 500,
      error: 'move_failed',
      message: 'The move failed; nothing changed',
      body: {},
    });
    const { onMoved, onClose } = await render();
    act(() => submit()!.click());
    await flush();
    const alert = Array.from(
      document.body.querySelectorAll('[role="alert"]'),
    ).find((node) =>
      node.textContent?.includes('workspace.move.errors.move_failed'),
    );
    expect(alert).toBeTruthy();
    expect(onMoved).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('shows a refused plan in place of the plan', async () => {
    api.planMove.mockResolvedValue({
      ok: false,
      status: 400,
      error: 'folder_too_deep',
      message: '',
      body: {},
    });
    await render();
    expect(text()).toContain('workspace.move.errors.folder_too_deep');
    expect(submit()?.disabled).toBe(true);
  });
});

describe('useMoveToWorkspace', () => {
  let labels: (string | null)[] = [];

  const Probe = ({
    kind,
    items,
  }: {
    kind: Parameters<typeof useMoveToWorkspace>[0];
    items: MovableItem[];
  }) => {
    const move = useMoveToWorkspace(kind);
    labels = items.map((item) => {
      const option = move.menuOption(item);
      return option ? String(option.label) : null;
    });
    return <>{move.dialog}</>;
  };

  const probe = (
    kind: Parameters<typeof useMoveToWorkspace>[0],
    items: MovableItem[],
    store = makeStore(),
  ) => {
    act(() => {
      root.render(
        <Provider store={store}>
          <MemoryRouter>
            <Probe kind={kind} items={items} />
          </MemoryRouter>
        </Provider>,
      );
    });
    return labels;
  };

  const personal = { kind: 'personal' as const, team_id: null };
  const team = { kind: 'team' as const, team_id: 't1' };

  it('offers Move to team on an own item when a team takes it', () => {
    expect(
      probe('agent', [
        {
          id: 'a1',
          name: 'A',
          origin: 'own',
          workspace: personal,
          allowed_actions: ['move_to_team'],
        },
      ]),
    ).toEqual(['workspace.menu.moveToTeam']);
  });

  it('offers nothing when no team lets the caller add', () => {
    expect(
      probe(
        'agent',
        [
          {
            id: 'a1',
            name: 'A',
            origin: 'own',
            workspace: personal,
            allowed_actions: ['move_to_team'],
          },
        ],
        makeStore('personal', 'viewer'),
      ),
    ).toEqual([null]);
  });

  it('offers nothing on a shared item or without the action', () => {
    expect(
      probe('source', [
        {
          id: 's1',
          name: 'S',
          origin: 'shared',
          workspace: personal,
          allowed_actions: ['use'],
        },
        {
          id: 's2',
          name: 'S2',
          origin: 'own',
          workspace: personal,
          allowed_actions: ['edit'],
        },
      ]),
    ).toEqual([null, null]);
  });

  it('offers Move to Personal on a team item the caller may move out', () => {
    expect(
      probe(
        'tool',
        [
          {
            id: 't1',
            name: 'T',
            origin: 'team',
            workspace: team,
            allowed_actions: ['move_out'],
          },
          {
            id: 't2',
            name: 'T2',
            origin: 'team',
            workspace: team,
            allowed_actions: ['use'],
          },
        ],
        makeStore('t1', 'admin'),
      ),
    ).toEqual(['workspace.menu.moveToPersonal', null]);
  });

  it('gates a team folder by the role there', () => {
    const folder: MovableItem = {
      id: 'f1',
      name: 'Carriers',
      origin: 'team',
      workspace: team,
    };
    expect(probe('folder', [folder], makeStore('t1', 'admin'))).toEqual([
      'workspace.menu.moveToPersonal',
    ]);
    expect(probe('folder', [folder], makeStore('t1', 'editor'))).toEqual([
      null,
    ]);
  });

  it('offers Move to team on an own folder', () => {
    expect(
      probe('folder', [
        { id: 'f1', name: 'Carriers', origin: 'own', workspace: personal },
      ]),
    ).toEqual(['workspace.menu.moveToTeam']);
  });

  it('offers nothing when the store holds no workspace list', () => {
    const item: MovableItem = {
      id: 'a1',
      name: 'A',
      origin: 'own',
      allowed_actions: ['move_to_team'],
    };
    expect(moveDirection(item, null, null)).toBeNull();
    expect(moveDirection(item, undefined, undefined)).toBeNull();
  });

  it('opens the dialog from the option', async () => {
    let option: MenuOption | null = null;
    const Opener = () => {
      const move = useMoveToWorkspace('prompt');
      option = move.menuOption({
        id: 'p1',
        name: 'Tone',
        origin: 'own',
        workspace: personal,
        allowed_actions: ['move_to_team'],
      });
      return <>{move.dialog}</>;
    };
    act(() => {
      root.render(
        <Provider store={makeStore()}>
          <MemoryRouter>
            <Opener />
          </MemoryRouter>
        </Provider>,
      );
    });
    act(() => option!.onClick(new Event('select')));
    await flush();
    expect(api.planMove).toHaveBeenCalledWith(
      {
        to: { workspace: 't1', folder_id: null },
        items: [{ type: 'prompt', id: 'p1' }],
      },
      { token: 'tok' },
    );
  });
});
