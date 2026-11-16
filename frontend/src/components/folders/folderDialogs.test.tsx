import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('../../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../hooks')>()),
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options && 'name' in options
        ? `${key}:${options.name}`
        : options && 'list' in options
          ? `${key}:${options.list}`
          : key,
  }),
}));

const api = vi.hoisted(() => ({
  getFolders: vi.fn(),
  createFolder: vi.fn(),
  updateFolder: vi.fn(),
  deleteFolder: vi.fn(),
  fileFolderItems: vi.fn(),
  getDocs: vi.fn(),
}));
vi.mock('../../api/services/userService', () => ({ default: api }));

// The Move to team / Move to Personal option, as the page's hook gives it.
const moveToWorkspace = vi.hoisted(() => ({
  kinds: [] as string[],
  items: [] as unknown[],
}));
vi.mock('../../workspace/move/useMoveToWorkspace', () => ({
  useMoveToWorkspace: (kind: string) => {
    moveToWorkspace.kinds.push(kind);
    return {
      menuOption: (item: unknown) => {
        moveToWorkspace.items.push(item);
        return { label: 'workspace.menu.moveToTeam', onClick: () => undefined };
      },
      dialog: <div data-testid="move-to-workspace-dialog" />,
    };
  },
  default: () => ({ menuOption: () => null, dialog: null }),
}));

import actionToastReducer from '../../notifications/actionToastSlice';
import workspaceReducer, {
  PERSONAL_ROW,
  type WorkspaceRole,
} from '../../workspace/workspaceSlice';
import FolderNameModal from './FolderNameModal';
import foldersReducer from './foldersSlice';
import MoveToFolderModal, { type MoveSubject } from './MoveToFolderModal';
import NewFolderButton from './NewFolderButton';
import type { Folder } from './types';
import { useFolderMenu } from './useFolderMenu';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const folders: Folder[] = [
  { id: 'carriers', name: 'Carriers', parent_id: null, item_count: 3 },
  { id: 'rates', name: 'Rate archive', parent_id: 'carriers' },
  { id: 'old', name: 'Old', parent_id: 'rates' },
  { id: 'customs', name: 'Customs', parent_id: null },
];

const json = (body: unknown, ok = true, status = 200) =>
  Promise.resolve({ ok, status, json: () => Promise.resolve(body) });

/** Personal, or a team where the caller has `role`. */
const workspaceState = (role?: WorkspaceRole) => ({
  current: role ? 't1' : 'personal',
  workspaces: role
    ? [
        PERSONAL_ROW,
        { id: 't1', kind: 'team' as const, name: 'Operations', role },
      ]
    : [PERSONAL_ROW],
  loaded: true,
  loading: false,
  epoch: 0,
  lastReason: null,
  latestRequestId: null,
});

let store: ReturnType<typeof makeStore>;

const makeStore = (role?: WorkspaceRole) =>
  configureStore({
    reducer: {
      preference: () => ({ token: 'tok' }),
      folders: foldersReducer,
      actionToast: actionToastReducer,
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

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  moveToWorkspace.kinds = [];
  moveToWorkspace.items = [];
  api.getFolders.mockImplementation(() => json({ folders }));
  api.getDocs.mockImplementation(() => json([]));
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

const mount = async (node: React.ReactNode, role?: WorkspaceRole) => {
  store = makeStore(role);
  await act(async () => {
    root.render(<Provider store={store}>{node}</Provider>);
  });
};

const dialog = () => document.body.querySelector('[role="dialog"]');
const button = (label: string) =>
  Array.from(document.body.querySelectorAll('button')).find(
    (b) => b.textContent === label,
  );
const typeInto = async (input: HTMLInputElement, value: string) => {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )?.set;
    setter?.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
};
const click = async (el: Element | undefined | null) => {
  await act(async () => {
    (el as HTMLElement).click();
  });
};

describe('FolderNameModal', () => {
  it('keeps the dialog open with the error under the field', async () => {
    api.createFolder.mockImplementation(() =>
      json(
        { success: false, error: 'folder_name_taken', message: 'taken' },
        false,
        409,
      ),
    );
    const onOpenChange = vi.fn();
    await mount(
      <FolderNameModal
        open
        onOpenChange={onOpenChange}
        kind="agent"
        mode="create"
        parentId="carriers"
      />,
    );
    const input = dialog()?.querySelector('input') as HTMLInputElement;
    // The field is labelled, not placeholder-only.
    expect(dialog()?.textContent).toContain('folders.name');
    await typeInto(input, '  Rate archive ');
    await click(button('folders.create'));
    expect(api.createFolder).toHaveBeenCalledWith(
      { name: 'Rate archive', parent_id: 'carriers' },
      'tok',
    );
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(dialog()?.querySelector('[role="alert"]')?.textContent).toBe(
      'folders.errors.nameTaken',
    );
  });

  it('closes once the rename is saved and the list reloaded', async () => {
    api.updateFolder.mockImplementation(() =>
      json({ id: 'customs', name: 'Customs 2026', parent_id: null }),
    );
    const onOpenChange = vi.fn();
    await mount(
      <FolderNameModal
        open
        onOpenChange={onOpenChange}
        kind="agent"
        mode="rename"
        folder={{ id: 'customs', name: 'Customs' }}
      />,
    );
    const input = dialog()?.querySelector('input') as HTMLInputElement;
    expect(input.value).toBe('Customs');
    await typeInto(input, 'Customs 2026');
    await click(button('folders.rename'));
    expect(api.updateFolder).toHaveBeenCalledWith(
      'customs',
      { name: 'Customs 2026' },
      'tok',
    );
    expect(api.getFolders).toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe('MoveToFolderModal', () => {
  const renderMove = (subject: MoveSubject, onMoved = vi.fn()) =>
    mount(
      <MoveToFolderModal
        open
        onOpenChange={() => undefined}
        kind="agent"
        subject={subject}
        onMoved={onMoved}
      />,
    );
  const row = (text: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLElement>('[data-slot="command-item"]'),
    ).find((el) => el.textContent?.includes(text));

  it('lists the root first and marks where the item is', async () => {
    await renderMove({
      kind: 'items',
      ids: ['a1'],
      name: 'Support',
      folderId: 'customs',
    });
    expect(dialog()?.textContent).toContain('folders.moveTitle:Support');
    const rows = Array.from(
      document.body.querySelectorAll('[data-slot="command-item"]'),
    ).map((el) => el.textContent);
    expect(rows[0]).toContain('folders.root.agent');
    expect(row('Customs')?.textContent).toContain('folders.current');
    expect(row('Customs')?.getAttribute('data-disabled')).toBe('true');
    // Nothing is chosen yet, so Move waits.
    expect(button('folders.move')?.disabled).toBe(true);
  });

  it('files the item into the chosen folder', async () => {
    api.fileFolderItems.mockImplementation(() =>
      json({ success: true, moved: ['a1'], skipped: [] }),
    );
    const onMoved = vi.fn();
    await renderMove(
      { kind: 'items', ids: ['a1'], name: 'Support', folderId: null },
      onMoved,
    );
    await click(row('Carriers'));
    await click(button('folders.move'));
    expect(api.fileFolderItems).toHaveBeenCalledWith(
      { type: 'agent', folder_id: 'carriers', ids: ['a1'] },
      'tok',
    );
    expect(onMoved).toHaveBeenCalledWith('carriers');
  });

  it('searches every level and shows the trail', async () => {
    await renderMove({
      kind: 'items',
      ids: ['a1'],
      name: 'Support',
      folderId: null,
    });
    const input = document.body.querySelector(
      '[data-slot="command-input"]',
    ) as HTMLInputElement;
    await typeInto(input, 'arch');
    const rows = Array.from(
      document.body.querySelectorAll('[data-slot="command-item"]'),
    ).map((el) => el.textContent);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toContain('Carriers › Rate archive');
  });

  it('moves a folder: never into itself, never past three levels', async () => {
    await renderMove({ kind: 'folder', folder: folders[3] });
    // Customs is a leaf, so a third-level target is still too deep only
    // below Old; at the top level it is where it already is.
    expect(row('folders.root.agent')?.textContent).toContain('folders.current');
    const carriers = { kind: 'folder' as const, folder: folders[0] };
    await act(async () => root.unmount());
    root = createRoot(container);
    await renderMove(carriers);
    // Carriers spans three levels: Customs can't take it, and its own
    // subtree isn't offered.
    expect(row('Customs')?.textContent).toContain('folders.tooDeep');
    expect(row('Customs')?.getAttribute('data-disabled')).toBe('true');
    expect(row('Rate archive')).toBeUndefined();
  });

  it('keeps a failed move in the dialog', async () => {
    api.updateFolder.mockImplementation(() =>
      json({ success: false, error: 'folder_too_deep' }, false, 400),
    );
    await renderMove({ kind: 'folder', folder: folders[3] });
    await click(row('Carriers'));
    await click(button('folders.move'));
    expect(api.updateFolder).toHaveBeenCalledWith(
      'customs',
      { parent_id: 'carriers' },
      'tok',
    );
    expect(dialog()?.querySelector('[role="alert"]')?.textContent).toBe(
      'folders.errors.tooDeep',
    );
  });

  it('says why a personal item cannot go in a team folder', async () => {
    api.fileFolderItems.mockImplementation(() =>
      json(
        {
          success: false,
          error: 'item_not_in_team',
          message: 'move it first',
          ids: ['a1'],
        },
        false,
        409,
      ),
    );
    await renderMove({
      kind: 'items',
      ids: ['a1'],
      name: 'Support',
      folderId: null,
    });
    await click(row('Carriers'));
    await click(button('folders.move'));
    expect(dialog()?.querySelector('[role="alert"]')?.textContent).toBe(
      'folders.errors.itemNotInTeam',
    );
  });

  it('names the root Agents in a team, and lists the whole tree', async () => {
    await mount(
      <MoveToFolderModal
        open
        onOpenChange={() => undefined}
        kind="agent"
        subject={{
          kind: 'items',
          ids: ['a1'],
          name: 'Support',
          folderId: null,
        }}
      />,
      'editor',
    );
    const rows = Array.from(
      document.body.querySelectorAll('[data-slot="command-item"]'),
    ).map((el) => el.textContent);
    expect(rows[0]).toContain('folders.root.teamAgent');
    expect(rows.some((text) => text?.includes('Customs'))).toBe(true);
  });
});

describe('useFolderMenu', () => {
  function Harness({ folder }: { folder: Folder }) {
    const menu = useFolderMenu('agent');
    const options = menu.menuOptions(folder);
    return (
      <>
        {options.map((option) => (
          <button
            key={option.label}
            type="button"
            onClick={(e) => option.onClick(e.nativeEvent)}
          >
            {option.label}
          </button>
        ))}
        {menu.dialogs}
      </>
    );
  }

  const labels = () =>
    Array.from(container.querySelectorAll('button')).map((b) => b.textContent);

  it('offers Rename, Move to folder, Move to team, then Delete after a rule', async () => {
    await mount(<Harness folder={folders[0]} />);
    expect(labels()).toEqual([
      'folders.rename',
      'folders.moveToFolder',
      'workspace.menu.moveToTeam',
      'folders.delete',
    ]);
    // The move option is asked for the folder, in the workspace it lives in.
    expect(moveToWorkspace.kinds).toContain('folder');
    expect(moveToWorkspace.items[0]).toMatchObject({
      id: 'carriers',
      name: 'Carriers',
      workspace: { kind: 'personal' },
      origin: 'own',
    });
    expect(
      container.querySelector('[data-testid="move-to-workspace-dialog"]'),
    ).not.toBeNull();
  });

  it("names a team's folder as the team's", async () => {
    await mount(<Harness folder={folders[0]} />, 'editor');
    expect(moveToWorkspace.items[0]).toMatchObject({
      workspace: { kind: 'team', team_id: 't1' },
      origin: 'team',
    });
  });

  it('leaves a Viewer in a team only what the move hook offers', async () => {
    await mount(<Harness folder={folders[0]} />, 'viewer');
    expect(labels()).toEqual(['workspace.menu.moveToTeam']);
  });

  it('confirms a delete with what moves where, then deletes', async () => {
    api.deleteFolder.mockImplementation(() =>
      json({ success: true, moved_items: 3, moved_folders: 1 }),
    );
    await mount(<Harness folder={folders[0]} />);
    await click(button('folders.delete'));
    expect(dialog()?.textContent).toContain('folders.deleteConfirm');
    expect(dialog()?.textContent).toContain('folders.deleteMoves');
    await click(button('folders.deleteFolder'));
    expect(api.deleteFolder).toHaveBeenCalledWith('carriers', 'tok');
    // Its sources moved up a level: the pickers' knowledge list is read
    // again, so none stays filed under the deleted folder.
    expect(api.getDocs).toHaveBeenCalledWith('tok');
    // Nothing was renamed: the folder leaving the page says enough.
    expect(store.getState().actionToast.current).toBeNull();
  });

  it('names the folders a delete renamed in the toast', async () => {
    api.deleteFolder.mockImplementation(() =>
      json({
        success: true,
        moved_items: 0,
        moved_folders: 1,
        renamed: [
          { id: 'rates', from: 'Rate archive', to: 'Rate archive (2)' },
        ],
      }),
    );
    await mount(<Harness folder={folders[0]} />);
    await click(button('folders.delete'));
    await click(button('folders.deleteFolder'));
    // No item moved: the knowledge list has nothing to catch up on.
    expect(api.getDocs).not.toHaveBeenCalled();
    const toast = store.getState().actionToast.current;
    expect(toast?.variant).toBe('success');
    expect(toast?.message).toContain('Rate archive → Rate archive (2)');
  });
});

describe('NewFolderButton', () => {
  it('shows in Personal and for an Editor in a team', async () => {
    await mount(<NewFolderButton onClick={() => undefined} />);
    expect(button('folders.newFolder')).toBeDefined();
    await act(async () => root.unmount());
    root = createRoot(container);
    await mount(<NewFolderButton onClick={() => undefined} />, 'editor');
    expect(button('folders.newFolder')).toBeDefined();
  });

  it('is left out for a Viewer in a team', async () => {
    await mount(<NewFolderButton onClick={() => undefined} />, 'viewer');
    expect(button('folders.newFolder')).toBeUndefined();
  });
});
