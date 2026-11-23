import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const { interpolation: _i, ...rest } = opts ?? {};
      void _i;
      return Object.keys(rest).length ? `${key}:${JSON.stringify(rest)}` : key;
    },
  }),
}));

// The menu is a Radix dropdown; the tests only need its options.
vi.mock('../components/ui/dropdown-menu', () => ({
  ActionMenu: ({
    options,
  }: {
    options: { label: string; onClick: () => void }[];
  }) => (
    <div data-testid="menu">
      {options.map((o) => (
        <button key={o.label} type="button" onClick={o.onClick}>
          {o.label}
        </button>
      ))}
    </div>
  ),
}));

const service = vi.hoisted(() => ({
  getPrompts: vi.fn(),
  createPrompt: vi.fn(),
  getSinglePrompt: vi.fn(),
  getPreferences: vi.fn(),
  updatePreferences: vi.fn(),
  getUserTools: vi.fn(),
  getFolders: vi.fn(),
  fileFolderItems: vi.fn(),
}));
vi.mock('../api/services/userService', () => ({ default: service }));

vi.mock('../drafter/useDrafterConfig', () => ({
  useDrafterConfig: () => null,
}));
vi.mock('../prompts/usePromptChecks', () => ({
  usePromptChecks: () => [],
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

// The Move to team option, as the page's hook gives it.
const moveToWorkspace = vi.hoisted(() => ({
  kinds: [] as string[],
  onMoved: [] as (undefined | (() => void))[],
}));
vi.mock('../workspace/move/useMoveToWorkspace', () => {
  const hook = (kind: string) => {
    moveToWorkspace.kinds.push(kind);
    return {
      menuOption: (_item: unknown, options?: { onMoved?: () => void }) => {
        moveToWorkspace.onMoved.push(options?.onMoved);
        return { label: 'workspace.menu.moveToTeam', onClick: () => {} };
      },
      dialog: null,
    };
  };
  return { useMoveToWorkspace: hook, default: hook };
});

import actionToastReducer from '../notifications/actionToastSlice';
import foldersReducer from '../components/folders/foldersSlice';
import type { Folder } from '../components/folders/types';
import preferenceReducer, { setToken } from '../preferences/preferenceSlice';
import { setRequestWorkspace } from '../workspace/requestWorkspace';
import workspaceReducer, {
  PERSONAL_ROW,
  type WorkspaceRole,
} from '../workspace/workspaceSlice';
import Prompts from './Prompts';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const response = (body: unknown, ok = true, status = 200) =>
  Promise.resolve({ ok, status, json: () => Promise.resolve(body) });

const OWNER_ACTIONS = [
  'delete',
  'duplicate',
  'edit',
  'share',
  'use',
  'move_folder',
];
const presets = [
  { id: 'default', name: 'default', type: 'public' },
  { id: 'creative', name: 'creative', type: 'public' },
  { id: 'strict', name: 'strict', type: 'public' },
];
const personal = { kind: 'personal' as const, team_id: null };
const own = {
  id: 'p-own',
  name: 'Vendor checks',
  type: 'private',
  access: 'owner',
  origin: 'own',
  workspace: personal,
  created_by: { user_id: 'me', label: 'Lena' },
  allowed_actions: OWNER_ACTIONS,
  folder_id: null,
};
const filed = {
  ...own,
  id: 'p-filed',
  name: 'Intake',
  folder_id: 'f-onboarding',
  folder_path: [{ id: 'f-onboarding', name: 'Carrier onboarding' }],
};
const shared = {
  id: 'p-shared',
  name: 'Lane pricing notes',
  // The old field still says "team"; the origin is what counts.
  type: 'team',
  team_access: 'viewer',
  access: 'viewer',
  origin: 'shared',
  workspace: personal,
  created_by: { user_id: 'priya', label: 'Priya' },
  allowed_actions: ['use', 'duplicate'],
};
const team = { kind: 'team' as const, team_id: 't1' };
const teamPrompt = {
  id: 'p-team',
  name: 'Weekly lane report',
  type: 'team',
  access: 'editor',
  origin: 'team',
  workspace: team,
  created_by: { user_id: 'dana', label: 'Dana' },
  allowed_actions: ['use', 'duplicate', 'edit', 'move_folder'],
};

// Another team's prompt shared with this team: use only.
const received = {
  id: 'p-received',
  name: 'Sales tone',
  type: 'team',
  access: 'viewer',
  team_access: 'viewer',
  origin: 'team_shared',
  workspace: team,
  shared_from: { team_id: 'sales', name: 'Sales' },
  owner_label: 'Sales',
  allowed_actions: ['use'],
  folder_id: null,
  folder_path: [],
};

const folders: Folder[] = [
  {
    id: 'f-onboarding',
    name: 'Carrier onboarding',
    parent_id: null,
    counts: { prompt: 1, agent: 2, tool: 3 },
  },
  {
    // Holds only agents: it stays on the Agents page.
    id: 'f-agents',
    name: 'Agent drafts',
    parent_id: null,
    counts: { agent: 4 },
  },
  {
    // An empty folder shows on every page.
    id: 'f-empty',
    name: 'Fresh',
    parent_id: null,
    counts: {},
  },
];

/** Personal, or a team where the caller has `role`. */
const workspaceState = (role?: WorkspaceRole) => ({
  current: role ? 't1' : 'personal',
  workspaces: role
    ? [
        PERSONAL_ROW,
        {
          id: 't1',
          kind: 'team' as const,
          name: 'Operations',
          role,
          member_count: 12,
        },
      ]
    : [PERSONAL_ROW],
  loaded: true,
  loading: false,
  epoch: 0,
  lastReason: null,
  latestRequestId: null,
});

const makeStore = (role?: WorkspaceRole) =>
  configureStore({
    reducer: {
      preference: preferenceReducer,
      actionToast: actionToastReducer,
      folders: foldersReducer,
      workspace: workspaceReducer,
    },
    preloadedState: {
      folders: {
        tree: {
          items: folders,
          loaded: true,
          loading: false,
          failed: false,
          latestRequestId: null,
          removedParents: {},
        },
      },
      workspace: workspaceState(role),
    },
  });

describe('Prompts page in a workspace', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: ReturnType<typeof makeStore>;

  beforeEach(() => {
    Object.values(service).forEach((fn) => fn.mockReset());
    service.getPrompts.mockImplementation(() =>
      response([...presets, own, filed, shared]),
    );
    service.getFolders.mockImplementation(() =>
      response({ folders, workspace: personal }),
    );
    service.getUserTools.mockImplementation(() => response({ success: false }));
    service.getSinglePrompt.mockImplementation(() =>
      response({ content: '', updated_at: 'v1' }),
    );
    moveToWorkspace.kinds = [];
    moveToWorkspace.onMoved = [];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = (role?: WorkspaceRole, entry = '/settings/prompts') => {
    store = makeStore(role);
    store.dispatch(setToken('tok'));
    return act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={[entry]}>
            <Routes>
              <Route path="/settings/prompts" element={<Prompts />} />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });
  };

  const headings = () =>
    Array.from(container.querySelectorAll('h2')).map((h) => h.textContent);
  const section = (title: string) =>
    Array.from(container.querySelectorAll('section')).find((s) =>
      s.querySelector('h2')?.textContent?.startsWith(title),
    );
  const cardTitles = (root: ParentNode = container) =>
    Array.from(
      root.querySelectorAll('[data-slot="card"] [data-slot="card-title"]'),
    ).map((title) => title.textContent);
  const card = (name: string) =>
    Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="card"]'),
    ).find(
      (c) => c.querySelector('[data-slot="card-title"]')?.textContent === name,
    )!;
  const folderTiles = () =>
    Array.from(container.querySelectorAll('[data-folder-tile]')).map((tile) =>
      tile.getAttribute('data-folder-tile'),
    );
  const button = (text: string) =>
    Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent === text,
    );

  it('in Personal: folders, your prompts, then Shared with you', async () => {
    await render();
    expect(headings()).toEqual([
      'settings.prompts.sections.folders2',
      'settings.prompts.sections.included3',
      'settings.prompts.sections.yours1',
      'workspace.page.sharedWithYou1',
    ]);
    // A folder that holds only agents stays off this page; an empty one shows.
    expect(folderTiles()).toEqual(['f-onboarding', 'f-empty']);
    // A filed prompt is in its folder, not at the root.
    expect(cardTitles()).not.toContain('Intake');
    expect(cardTitles(section('workspace.page.sharedWithYou')!)).toEqual([
      'Lane pricing notes',
    ]);
    // Shared with you names the owner and the caller's role; own tiles neither.
    const sharedCard = card('Lane pricing notes');
    expect(
      sharedCard.querySelector('[data-testid="creator-meta"]')?.textContent,
    ).toBe('Priya');
    expect(
      sharedCard.querySelector('[data-testid="role-meta"]'),
    ).not.toBeNull();
    const ownCard = card('Vendor checks');
    expect(ownCard.querySelector('[data-testid="creator-meta"]')).toBeNull();
    expect(ownCard.querySelector('[data-testid="role-meta"]')).toBeNull();
    // The old "Shared with team" section is gone.
    expect(headings()).not.toContain('settings.prompts.sections.shared1');
  });

  it('in a team: the team prompts name who added them, with no role and no Shared with you', async () => {
    service.getPrompts.mockImplementation(() =>
      response([...presets, teamPrompt]),
    );
    await render('editor');
    expect(headings()).not.toContainEqual(
      expect.stringMatching(/^workspace\.page\.sharedWithYou/),
    );
    expect(headings()).toContain('settings.prompts.sections.team1');
    const tile = card('Weekly lane report');
    expect(
      tile.querySelector('[data-testid="creator-meta"]')?.textContent,
    ).toBe('Dana');
    expect(tile.querySelector('[data-testid="role-meta"]')).toBeNull();
    // An Editor can add prompts and folders.
    expect(button('settings.prompts.addPrompt')).toBeDefined();
    expect(button('folders.newFolder')).toBeDefined();
  });

  it('in a team, a Viewer gets no Add prompt and no New folder', async () => {
    service.getPrompts.mockImplementation(() =>
      response([...presets, teamPrompt]),
    );
    await render('viewer');
    expect(button('settings.prompts.addPrompt')).toBeUndefined();
    expect(button('folders.newFolder')).toBeUndefined();
  });

  it('inside a folder lists only the prompts filed there', async () => {
    await render(undefined, '/settings/prompts?folder=f-onboarding');
    expect(cardTitles()).toEqual(['Intake']);
    expect(
      container.querySelector('[data-slot="folder-crumb-row"]')?.textContent,
    ).toContain('Carrier onboarding');
    // The other kinds the folder holds link to it on their pages.
    const also = Array.from(
      container.querySelectorAll<HTMLAnchorElement>(
        '[data-slot="folder-crumb-row"] a',
      ),
    ).map((a) => a.getAttribute('href'));
    expect(also).toContain('/agents?folder=f-onboarding');
    expect(also).toContain('/settings/tools?folder=f-onboarding');
    // The presets are never filed.
    expect(headings()).not.toContainEqual(
      expect.stringMatching(/^settings\.prompts\.sections\.included/),
    );
  });

  it('a prompt added inside a folder is created in it', async () => {
    service.createPrompt.mockImplementation(() =>
      response({ id: 'p-new', updated_at: 'v1' }),
    );
    await render(undefined, '/settings/prompts?folder=f-onboarding');
    await act(async () => button('settings.prompts.addPrompt')!.click());
    const view = container.querySelector<HTMLElement>(
      '[data-slot="prompt-view"]',
    )!;
    const type = (
      field: HTMLInputElement | HTMLTextAreaElement,
      value: string,
    ) =>
      act(async () => {
        const proto =
          field instanceof HTMLTextAreaElement
            ? HTMLTextAreaElement.prototype
            : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(
          field,
          value,
        );
        field.dispatchEvent(new Event('input', { bubbles: true }));
      });
    await type(view.querySelector('input[type="text"]')!, 'Welcome message');
    await type(view.querySelector('textarea')!, 'Welcome the carrier.');
    const save = Array.from(view.querySelectorAll('button')).find(
      (b) => b.textContent === 'modals.prompts.save',
    )!;
    await act(async () => save.click());
    expect(service.createPrompt).toHaveBeenCalledWith(
      {
        name: 'Welcome message',
        content: 'Welcome the carrier.',
        folder_id: 'f-onboarding',
      },
      'tok',
    );
  });

  it('offers Move to folder and Move to team on a prompt of yours', async () => {
    await render();
    const labels = Array.from(
      card('Vendor checks').querySelectorAll('[data-testid="menu"] button'),
    ).map((b) => b.textContent);
    expect(labels).toContain('folders.moveToFolder');
    expect(labels).toContain('workspace.menu.moveToTeam');
    expect(moveToWorkspace.kinds).toContain('prompt');
    // The move hands the page its reload.
    expect(moveToWorkspace.onMoved.some((fn) => typeof fn === 'function')).toBe(
      true,
    );
  });

  it('never offers Move to folder on a shared prompt the caller only views', async () => {
    await render();
    const labels = Array.from(
      card('Lane pricing notes').querySelectorAll(
        '[data-testid="menu"] button',
      ),
    ).map((b) => b.textContent);
    expect(labels).not.toContain('folders.moveToFolder');
  });

  const menuLabels = (name: string) =>
    Array.from(card(name).querySelectorAll('[data-testid="menu"] button')).map(
      (b) => b.textContent,
    );

  it("offers Share on a team's prompt to a Viewer, to see who has access", async () => {
    service.getPrompts.mockImplementation(() =>
      response([
        ...presets,
        { ...teamPrompt, access: 'viewer', allowed_actions: ['use'] },
      ]),
    );
    await render('viewer');
    expect(menuLabels('Weekly lane report')).toContain(
      'settings.prompts.shareWithTeam',
    );
  });

  const allMenuLabels = () =>
    Array.from(container.querySelectorAll('[data-testid="menu"] button')).map(
      (b) => b.textContent,
    );

  it("never offers a team's Viewer Duplicate, since the copy can't be saved there", async () => {
    service.getPrompts.mockImplementation(() =>
      response([
        ...presets,
        {
          ...teamPrompt,
          access: 'viewer',
          allowed_actions: ['use', 'duplicate'],
        },
      ]),
    );
    await render('viewer');
    expect(menuLabels('Weekly lane report').length).toBeGreaterThan(0);
    // Nor on the built-in prompts.
    expect(allMenuLabels()).not.toContain('settings.prompts.duplicate');
  });

  it("offers a team's Editor Duplicate", async () => {
    service.getPrompts.mockImplementation(() =>
      response([...presets, teamPrompt]),
    );
    await render('editor');
    expect(menuLabels('Weekly lane report')).toContain(
      'settings.prompts.duplicate',
    );
  });

  it("reloads the list when the Share dialog's offer moves the prompt", async () => {
    // Not a plain assignment, which would narrow `props` to null below.
    Object.assign(share, { props: null });
    await render();
    const shareItem = Array.from(
      card('Vendor checks').querySelectorAll<HTMLButtonElement>(
        '[data-testid="menu"] button',
      ),
    ).find((b) => b.textContent === 'settings.prompts.shareWithTeam')!;
    await act(async () => shareItem.click());
    expect(share.props?.onMoved).toBeTypeOf('function');
    const loads = service.getPrompts.mock.calls.length;
    await act(async () => share.props!.onMoved!());
    expect(service.getPrompts.mock.calls.length).toBeGreaterThan(loads);
  });

  it("lists another team's prompts under Shared with this team, naming the team, to read and use only", async () => {
    service.getPrompts.mockImplementation(() =>
      response([...presets, teamPrompt, received]),
    );
    await render('editor');
    expect(headings()).toEqual([
      'settings.prompts.sections.folders2',
      'settings.prompts.sections.included3',
      'settings.prompts.sections.team1',
      'workspace.page.sharedFromTeams.title1',
    ]);
    expect(
      cardTitles(section('workspace.page.sharedFromTeams.title')!),
    ).toEqual(['Sales tone']);
    const tile = card('Sales tone');
    expect(
      tile.querySelector('[data-testid="shared-from-meta"]')?.textContent,
    ).toBe('workspace.page.sharedFromTeams.from:{"team":"Sales"}');
    expect(tile.querySelector('[data-testid="role-meta"]')).toBeNull();
    // It opens to read; nothing edits, copies, files, moves or deletes it.
    const labels = menuLabels('Sales tone');
    expect(labels).toContain('settings.prompts.view');
    for (const refused of [
      'settings.prompts.edit',
      'settings.prompts.duplicate',
      'folders.moveToFolder',
      'settings.prompts.delete',
    ])
      expect(labels).not.toContain(refused);
  });

  it("keeps a list that answers after a workspace switch out of the new workspace's pickers", async () => {
    let answer: (body: unknown) => void = () => undefined;
    service.getPrompts.mockImplementation(
      () =>
        new Promise((resolve) => {
          answer = (body) =>
            resolve({ ok: true, status: 200, json: async () => body });
        }),
    );
    setRequestWorkspace('personal', 0);
    try {
      await render();
      const before = store.getState().preference.prompts;
      // The user switches to a team while the list is out.
      setRequestWorkspace('t1', 1);
      await act(async () => answer([...presets, own]));
      expect(store.getState().preference.prompts).toBe(before);
    } finally {
      setRequestWorkspace('personal', 0);
    }
  });
});
