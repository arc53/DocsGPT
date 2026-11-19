import type { Dispatch } from '@reduxjs/toolkit';

import type { Doc } from '../models/misc';
import { captureWorkspace } from '../workspace/requestWorkspace';
import { getDocs } from './preferenceApi';
import { setSourceDocs } from './preferenceSlice';

/**
 * Reads the app's knowledge list (`preference.sourceDocs`) again, after a
 * change made elsewhere moved sources: a folder deleted (its sources moved
 * up a level) or something moved to another workspace (its sources left
 * this one). The pickers read this list, so without it they keep offering
 * what left or file it under a folder that is gone. A failed read keeps the
 * list it had; an answer that lands after a workspace switch is dropped.
 *
 * Args:
 *   token: The session token.
 *
 * Returns:
 *   A thunk resolving to the fresh list, or null when it couldn't be read.
 */
export const reloadSourceDocs =
  (token: string | null) =>
  async (dispatch: Dispatch): Promise<Doc[] | null> => {
    const workspace = captureWorkspace();
    const docs = await getDocs(token);
    if (docs && workspace.isCurrent()) dispatch(setSourceDocs(docs));
    return docs;
  };
