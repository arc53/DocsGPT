import { nanoid } from '@reduxjs/toolkit';
import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector, useStore } from 'react-redux';

import userService from '../api/services/userService';
import type { Doc } from '../models/misc';
import { getDocs } from '../preferences/preferenceApi';
import {
  selectSelectedDocs,
  selectToken,
  setSelectedDocs,
  setSourceDocs,
} from '../preferences/preferenceSlice';
import type { RootState } from '../store';
import {
  addUploadTask,
  removeUploadTask,
  updateUploadTask,
} from './uploadSlice';

/** A chat file to turn into Knowledge: its server attachment id and name. */
export interface KnowledgeFile {
  id: string;
  fileName: string;
}

// An ingest of many large files can take a while; the wait is only a store
// subscription, and the upload toast reports the outcome either way.
const INGEST_WAIT_MS = 30 * 60_000;

type IngestOutcome = 'completed' | 'failed' | 'timeout';

/**
 * Resolve once the ingest behind an upload task ends. The task is driven by
 * the ``source.ingest.*`` events (uploadSlice); the recent-events walk covers
 * a terminal event that arrived before the task learned its source id.
 */
export function waitForSourceIngest(
  store: {
    getState: () => RootState;
    subscribe: (cb: () => void) => () => void;
  },
  clientTaskId: string,
  sourceId: string,
  timeoutMs = INGEST_WAIT_MS,
): Promise<IngestOutcome> {
  const check = (): IngestOutcome | null => {
    const state = store.getState();
    const task = state.upload.tasks.find((t) => t.id === clientTaskId);
    if (task?.status === 'completed' || task?.status === 'failed') {
      return task.status;
    }
    for (const event of state.notifications.recentEvents) {
      if (event.scope?.id !== sourceId) continue;
      if (event.type === 'source.ingest.completed') return 'completed';
      if (event.type === 'source.ingest.failed') return 'failed';
    }
    return null;
  };
  return new Promise((resolve) => {
    const now = check();
    if (now) {
      resolve(now);
      return;
    }
    const timer = window.setTimeout(() => {
      unsubscribe();
      resolve('timeout');
    }, timeoutMs);
    const unsubscribe = store.subscribe(() => {
      const outcome = check();
      if (!outcome) return;
      window.clearTimeout(timer);
      unsubscribe();
      resolve(outcome);
    });
  });
}

/**
 * Turn chat attachments into a Knowledge source in place: the server copies
 * the stored files into an ingest job, the upload toast shows its progress,
 * and the new source is added to the chat's selection once it is ready.
 *
 * ``addToKnowledge`` resolves ``true`` as soon as the server accepted the
 * job (the caller can drop the files from the composer then), ``false``
 * when it refused, with ``error`` set for an inline message.
 */
export function useAddToKnowledge() {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const store = useStore<RootState>();
  const token = useSelector(selectToken);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectWhenReady = useCallback(
    async (clientTaskId: string, sourceId: string) => {
      const outcome = await waitForSourceIngest(store, clientTaskId, sourceId);
      if (outcome !== 'completed') return;
      const docs = await getDocs(token);
      if (!Array.isArray(docs)) return;
      dispatch(setSourceDocs(docs));
      const created = docs.find((doc: Doc) => doc.id === sourceId);
      if (!created) return;
      // Read the selection as it is now, not as it was when the job started.
      const current = selectSelectedDocs(store.getState()) ?? [];
      dispatch(
        setSelectedDocs([
          ...current.filter((doc: Doc) => doc.id !== sourceId),
          created,
        ]),
      );
    },
    [dispatch, store, token],
  );

  const addToKnowledge = useCallback(
    async (files: KnowledgeFile[]): Promise<boolean> => {
      if (files.length === 0) return false;
      setPending(true);
      setError(null);
      const name =
        files.length === 1
          ? files[0].fileName
          : t('conversation.attachments.knowledgeName', {
              name: files[0].fileName,
              count: files.length - 1,
            });
      const clientTaskId = nanoid();
      // Added before the request, as Upload does, so an ingest event that
      // beats the response merges into this row instead of a second toast.
      dispatch(
        addUploadTask({
          id: clientTaskId,
          fileName: name,
          progress: 0,
          status: 'preparing',
        }),
      );
      try {
        const response = await userService.createSourceFromAttachments(
          { attachment_ids: files.map((file) => file.id), name },
          token,
        );
        const data = await response.json().catch(() => null);
        if (!response.ok || !data?.success || !data.source_id) {
          throw new Error(data?.message ?? `HTTP ${response.status}`);
        }
        const sourceId = String(data.source_id);
        dispatch(
          updateUploadTask({
            id: clientTaskId,
            updates: { status: 'training', taskId: data.task_id, sourceId },
          }),
        );
        void selectWhenReady(clientTaskId, sourceId).catch((err) => {
          console.error('Could not select the new Knowledge source:', err);
        });
        return true;
      } catch (err) {
        console.error('Could not add attachments to Knowledge:', err);
        dispatch(removeUploadTask(clientTaskId));
        setError(t('conversation.attachments.knowledgeFailed'));
        return false;
      } finally {
        setPending(false);
      }
    },
    [dispatch, selectWhenReady, t, token],
  );

  return { addToKnowledge, pending, error };
}
