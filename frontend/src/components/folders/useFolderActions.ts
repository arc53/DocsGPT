import { useCallback, useMemo } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import { selectToken } from '../../preferences/preferenceSlice';
import { reloadSourceDocs } from '../../preferences/reloadSourceDocs';
import type { AppDispatch } from '../../store';
import { captureWorkspace } from '../../workspace/requestWorkspace';
import { folderRemoved, folderSaved, loadFolders } from './foldersSlice';
import type { RenamedFolder } from './folderCopy';
import type { Folder, ItemKind } from './types';

/**
 * A refused folder request: `code` is the server's error code
 * (`folder_name_taken`, `folder_too_deep`, `folder_cycle`,
 * `invalid_folder_name`, `folder_not_found`, `team_item_not_fileable`,
 * `item_not_in_team`, `workspace_role_required`, `skipped` when nothing could
 * be filed), or `request_failed` for a transport or unknown failure.
 */
export class FolderRequestError extends Error {
  code: string;
  status: number;

  constructor(code: string, message: string, status = 0) {
    super(message);
    this.name = 'FolderRequestError';
    this.code = code;
    this.status = status;
  }
}

/** The error code of a rejection, `request_failed` when it has none. */
export const folderErrorCode = (reason: unknown): string =>
  reason instanceof FolderRequestError ? reason.code : 'request_failed';

type ResponseBody = Record<string, unknown> | null;

const readJson = async (response: Response): Promise<ResponseBody> => {
  try {
    return await response.json();
  } catch {
    return null;
  }
};

/** Throws the server's error when the request was refused, else the body. */
const unwrap = async (
  response: Response | undefined,
): Promise<ResponseBody> => {
  if (!response) throw new FolderRequestError('request_failed', '');
  const body = await readJson(response);
  if (!response.ok || body?.success === false) {
    throw new FolderRequestError(
      typeof body?.error === 'string' ? body.error : 'request_failed',
      typeof body?.message === 'string' ? body.message : '',
      response.status,
    );
  }
  return body;
};

export type FolderActions = {
  /** Create a folder in `parentId` (null: the top level). */
  create: (name: string, parentId: string | null) => Promise<Folder>;
  rename: (id: string, name: string) => Promise<Folder>;
  /** Move a folder under `parentId` (null: the top level). */
  move: (id: string, parentId: string | null) => Promise<Folder>;
  /**
   * Delete a folder; its contents move to its parent (null: the root), and
   * `renamed` lists the child folders renamed to keep names unique there.
   */
  remove: (
    id: string,
    parentId: string | null,
  ) => Promise<{
    moved_items: number;
    moved_folders: number;
    renamed: RenamedFolder[];
  }>;
  /**
   * File items of the hook's kind into `folderId` (null unfiles them).
   * Rejects with `skipped` when none of them could be filed, and with
   * `team_item_not_fileable` / `item_not_in_team` when an item doesn't
   * belong in the tree.
   */
  fileItems: (
    ids: string[],
    folderId: string | null,
  ) => Promise<{ moved: string[]; skipped: string[] }>;
  /** Reload the folder tree (counts change with every filing). */
  reload: () => Promise<unknown>;
};

/**
 * The folder requests of the current workspace's tree. Each resolves once the
 * server has done it and the tree has been reloaded, so the counts on screen
 * are the server's, and rejects with a `FolderRequestError` the caller shows
 * where the user is looking (a FormField, the dialog's Alert, a toast).
 *
 * Args:
 *   kind: The kind `fileItems` files; folders themselves hold every kind.
 */
export function useFolderActions(kind: ItemKind): FolderActions {
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);

  const reload = useCallback(
    () => dispatch(loadFolders({ token, force: true })),
    [dispatch, token],
  );

  const run = useCallback(
    async <T>(
      request: Promise<Response>,
      onSuccess?: (body: T) => void,
    ): Promise<T> => {
      const workspace = captureWorkspace();
      let response: Response;
      try {
        response = await request;
      } catch {
        throw new FolderRequestError('request_failed', '');
      }
      const body = (await unwrap(response)) as T;
      // Another workspace's tree is on screen now: leave it alone.
      if (!workspace.isCurrent()) return body;
      onSuccess?.(body);
      await reload();
      return body;
    },
    [reload],
  );

  // The saved folder goes in at once: the reload after it never rejects, so
  // a failed one would otherwise keep the old name or place on screen.
  const saved = useCallback(
    (folder: Folder) => {
      if (folder && typeof folder.id === 'string')
        dispatch(folderSaved(folder));
    },
    [dispatch],
  );

  return useMemo(
    () => ({
      create: (name, parentId) =>
        run<Folder>(
          userService.createFolder({ name, parent_id: parentId }, token),
          saved,
        ),
      rename: (id, name) =>
        run<Folder>(userService.updateFolder(id, { name }, token), saved),
      move: (id, parentId) =>
        run<Folder>(
          userService.updateFolder(id, { parent_id: parentId }, token),
          saved,
        ),
      remove: async (id, parentId) => {
        const result = await run<{
          moved_items?: number;
          moved_folders?: number;
          renamed?: RenamedFolder[];
        }>(userService.deleteFolder(id, token), () =>
          dispatch(folderRemoved({ id, parentId })),
        );
        // Its sources now sit in the parent: the pickers' copy of the
        // knowledge list would still file them under the deleted folder.
        if (result?.moved_items !== 0) void dispatch(reloadSourceDocs(token));
        return {
          moved_items: result?.moved_items ?? 0,
          moved_folders: result?.moved_folders ?? 0,
          renamed: Array.isArray(result?.renamed) ? result.renamed : [],
        };
      },
      fileItems: async (ids, folderId) => {
        const result = await run<{ moved?: string[]; skipped?: string[] }>(
          userService.fileFolderItems(
            { type: kind, folder_id: folderId, ids },
            token,
          ),
        );
        const moved = result.moved ?? [];
        const skipped = result.skipped ?? [];
        if (moved.length === 0 && skipped.length > 0)
          throw new FolderRequestError('skipped', '');
        return { moved, skipped };
      },
      reload,
    }),
    [run, reload, saved, dispatch, kind, token],
  );
}
