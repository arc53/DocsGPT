import { useCallback, useMemo } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import { selectToken } from '../../preferences/preferenceSlice';
import type { AppDispatch } from '../../store';
import { folderRemoved, loadFolders } from './foldersSlice';
import type { Folder, FolderType } from './types';

/**
 * A refused folder request: `code` is the server's error code
 * (`folder_name_taken`, `folder_too_deep`, `folder_cycle`,
 * `invalid_folder_name`, `folder_not_found`, `skipped` when nothing could be
 * filed), or `request_failed` for a transport or unknown failure.
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
  /** Delete a folder; its contents move to its parent (null: the root). */
  remove: (
    id: string,
    parentId: string | null,
  ) => Promise<{ moved_items: number; moved_folders: number }>;
  /**
   * File items into `folderId` (null unfiles them). Rejects with `skipped`
   * when none of them could be filed.
   */
  fileItems: (
    ids: string[],
    folderId: string | null,
  ) => Promise<{ moved: string[]; skipped: string[] }>;
  /** Reload this type's folders (counts change with every filing). */
  reload: () => Promise<unknown>;
};

/**
 * The folder requests for one type. Each resolves once the server has done it
 * and the folder list has been reloaded, so the counts on screen are the
 * server's, and rejects with a `FolderRequestError` the caller shows where
 * the user is looking (a FormField, the dialog's Alert, a toast).
 */
export function useFolderActions(type: FolderType): FolderActions {
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);

  const reload = useCallback(
    () => dispatch(loadFolders({ type, token })),
    [dispatch, type, token],
  );

  const run = useCallback(
    async <T>(
      request: Promise<Response>,
      onSuccess?: () => void,
    ): Promise<T> => {
      let response: Response;
      try {
        response = await request;
      } catch {
        throw new FolderRequestError('request_failed', '');
      }
      const body = (await unwrap(response)) as T;
      onSuccess?.();
      await reload();
      return body;
    },
    [reload],
  );

  return useMemo(
    () => ({
      create: (name, parentId) =>
        run<Folder>(
          userService.createFolder({ type, name, parent_id: parentId }, token),
        ),
      rename: (id, name) =>
        run<Folder>(userService.updateFolder(id, { name }, token)),
      move: (id, parentId) =>
        run<Folder>(
          userService.updateFolder(id, { parent_id: parentId }, token),
        ),
      remove: (id, parentId) =>
        run(userService.deleteFolder(id, token), () =>
          dispatch(folderRemoved({ type, id, parentId })),
        ),
      fileItems: async (ids, folderId) => {
        const result = await run<{ moved?: string[]; skipped?: string[] }>(
          userService.fileFolderItems(
            { type, folder_id: folderId, ids },
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
    [run, reload, dispatch, type, token],
  );
}
