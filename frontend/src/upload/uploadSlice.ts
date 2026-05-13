import { createSelector, createSlice, PayloadAction } from '@reduxjs/toolkit';

import {
  DismissedEntry,
  isDismissed,
  loadDismissed,
  saveDismissed,
} from '../notifications/dismissedPersistence';
import { sseEventReceived } from '../notifications/notificationsSlice';
import { RootState } from '../store';

const DISMISSED_SOURCE_IDS_STORAGE_KEY = 'docsgpt:dismissedUploadSourceIds';
const DISMISSED_SOURCE_IDS_TTL_MS = 24 * 60 * 60 * 1000;
const DISMISSED_SOURCE_IDS_CAP = 200;

function recordDismissedSourceId(
  list: DismissedEntry[],
  sourceId: string,
): DismissedEntry[] {
  const now = Date.now();
  const cutoff = now - DISMISSED_SOURCE_IDS_TTL_MS;
  const next = list.filter(
    (entry) => entry.at >= cutoff && entry.id !== sourceId,
  );
  next.push({ id: sourceId, at: now });
  return next.length > DISMISSED_SOURCE_IDS_CAP
    ? next.slice(-DISMISSED_SOURCE_IDS_CAP)
    : next;
}

export interface Attachment {
  id: string; // Client-side state-management id (uuid generated in MessageInput)
  fileName: string;
  progress: number;
  status: 'uploading' | 'processing' | 'completed' | 'failed';
  taskId: string; // Server-assigned celery task ID (used for API calls)
  /**
   * Server-assigned attachment id (stable across the lifecycle —
   * ``attachment.*`` SSE events use this in ``scope.id``). Set as
   * soon as the upload response returns. Distinct from ``id``
   * (client) and ``taskId`` (celery).
   */
  attachmentId?: string;
  token_count?: number;
}

export type UploadTaskStatus =
  | 'preparing'
  | 'uploading'
  | 'training'
  | 'completed'
  | 'failed';

export interface UploadTask {
  id: string;
  fileName: string;
  progress: number;
  status: UploadTaskStatus;
  taskId?: string;
  /**
   * Server-derived source id (uuid5 over the idempotency key) returned by
   * the upload endpoint. Used to correlate inbound SSE ingest events
   * (``source.ingest.*``) back to this task without consulting the
   * polling endpoint.
   */
  sourceId?: string;
  errorMessage?: string;
  dismissed?: boolean;
  /**
   * Flipped when ``source.ingest.completed`` carries
   * ``payload.limited === true`` (the worker hit a token cap during
   * ingest). The slice routes such events to a failed status and
   * sets this flag so ``UploadToast`` can surface a translated
   * token-limit message instead of a generic error. Forward-looking:
   * no worker code path sets ``limited: true`` today.
   */
  tokenLimitReached?: boolean;
}

interface UploadState {
  attachments: Attachment[];
  tasks: UploadTask[];
  /** Persisted dismissed sourceIds; keeps backlog-replay auto-creates silent. */
  dismissedSourceIds: DismissedEntry[];
}

const initialState: UploadState = {
  attachments: [],
  tasks: [],
  dismissedSourceIds: loadDismissed(
    DISMISSED_SOURCE_IDS_STORAGE_KEY,
    DISMISSED_SOURCE_IDS_TTL_MS,
  ),
};

export const uploadSlice = createSlice({
  name: 'upload',
  initialState,
  reducers: {
    addAttachment: (state, action: PayloadAction<Attachment>) => {
      state.attachments.push(action.payload);
    },
    updateAttachment: (
      state,
      action: PayloadAction<{
        id: string;
        updates: Partial<Attachment>;
      }>,
    ) => {
      const index = state.attachments.findIndex(
        (att) => att.id === action.payload.id,
      );
      if (index !== -1) {
        state.attachments[index] = {
          ...state.attachments[index],
          ...action.payload.updates,
        };
      }
    },
    removeAttachment: (state, action: PayloadAction<string>) => {
      state.attachments = state.attachments.filter(
        (att) => att.id !== action.payload,
      );
    },
    // Reorder attachments array by moving item from sourceIndex to destinationIndex
    reorderAttachments: (
      state,
      action: PayloadAction<{ sourceIndex: number; destinationIndex: number }>,
    ) => {
      const { sourceIndex, destinationIndex } = action.payload;
      if (
        sourceIndex < 0 ||
        destinationIndex < 0 ||
        sourceIndex >= state.attachments.length ||
        destinationIndex >= state.attachments.length
      )
        return;

      const [moved] = state.attachments.splice(sourceIndex, 1);
      state.attachments.splice(destinationIndex, 0, moved);
    },
    clearAttachments: (state) => {
      state.attachments = state.attachments.filter(
        (att) => att.status === 'uploading' || att.status === 'processing',
      );
    },
    addUploadTask: (state, action: PayloadAction<UploadTask>) => {
      state.tasks.unshift(action.payload);
    },
    updateUploadTask: (
      state,
      action: PayloadAction<{
        id: string;
        updates: Partial<UploadTask>;
      }>,
    ) => {
      const index = state.tasks.findIndex(
        (task) => task.id === action.payload.id,
      );
      if (index !== -1) {
        const updates = action.payload.updates;
        const existingSourceId = state.tasks[index].sourceId;
        const incomingSourceId = updates.sourceId;
        const effectiveSourceId = incomingSourceId ?? existingSourceId;
        const sourceWasDismissed =
          !!effectiveSourceId &&
          isDismissed(state.dismissedSourceIds, effectiveSourceId);

        // Re-surface on terminal status, except when the sourceId was
        // dismissed in a prior session (don't re-pop after reload).
        if (
          (updates.status === 'completed' || updates.status === 'failed') &&
          !sourceWasDismissed
        ) {
          state.tasks[index] = {
            ...state.tasks[index],
            ...updates,
            dismissed: false,
          };
        } else {
          state.tasks[index] = {
            ...state.tasks[index],
            ...updates,
          };
        }
      }
    },
    dismissUploadTask: (state, action: PayloadAction<string>) => {
      const index = state.tasks.findIndex((task) => task.id === action.payload);
      if (index !== -1) {
        state.tasks[index] = {
          ...state.tasks[index],
          dismissed: true,
        };
        // Persist by sourceId so a reload doesn't re-pop via the SSE
        // backlog replay's auto-create branch.
        const sourceId = state.tasks[index].sourceId;
        if (sourceId) {
          state.dismissedSourceIds = recordDismissedSourceId(
            state.dismissedSourceIds,
            sourceId,
          );
          saveDismissed(
            DISMISSED_SOURCE_IDS_STORAGE_KEY,
            state.dismissedSourceIds,
          );
        }
      }
    },
    removeUploadTask: (state, action: PayloadAction<string>) => {
      state.tasks = state.tasks.filter((task) => task.id !== action.payload);
    },
  },
  extraReducers: (builder) => {
    // Consume backend SSE ingest events for sub-second progress and
    // terminal-status updates. The match is by ``sourceId`` (set by
    // the upload endpoint's response). Polling stays as the
    // correctness-of-record fallback in Upload.tsx.
    builder.addCase(sseEventReceived, (state, action) => {
      const e = action.payload;
      const scopeId =
        typeof e.scope?.id === 'string' && e.scope.id.length > 0
          ? e.scope.id
          : undefined;

      // Attachment events flow through the same SSE pipe; route them
      // to ``state.attachments`` matched by ``attachmentId``. SSE is
      // the sole driver of attachment state transitions — polling
      // has been removed. Events for attachments uploaded in another
      // session are silently dropped.
      if (e.type.startsWith('attachment.') && scopeId) {
        const attachment = state.attachments.find(
          (a) => a.attachmentId === scopeId,
        );
        if (attachment) {
          const payload = (e.payload || {}) as Record<string, unknown>;
          switch (e.type) {
            case 'attachment.queued':
            case 'attachment.progress': {
              if (
                attachment.status === 'completed' ||
                attachment.status === 'failed'
              ) {
                break;
              }
              attachment.status = 'processing';
              const current = Number(payload.current);
              if (Number.isFinite(current)) {
                const clamped = Math.max(0, Math.min(100, current));
                if (clamped > attachment.progress) {
                  attachment.progress = clamped;
                }
              }
              break;
            }
            case 'attachment.completed': {
              attachment.status = 'completed';
              attachment.progress = 100;
              // Replace the client-generated uuid with the server's
              // attachment id so question submission
              // (Conversation.tsx:174) sends an id the backend can
              // resolve. Without this the backend would silently drop
              // the attachment from the message context.
              attachment.id = scopeId;
              const tokenCount = Number(payload.token_count);
              if (Number.isFinite(tokenCount)) {
                attachment.token_count = tokenCount;
              }
              break;
            }
            case 'attachment.failed': {
              attachment.status = 'failed';
              break;
            }
            default:
              break;
          }
        }
        return;
      }

      if (!e.type.startsWith('source.ingest.')) return;
      if (!scopeId) return;
      // ``source.ingest.*`` payloads do not carry a celery task_id
      // (see ``application/worker.py`` — only ``source_id`` /
      // ``job_name`` / ``filename`` are published), so ``sourceId``
      // is the only correlation key.
      const payload = (e.payload || {}) as Record<string, unknown>;
      let task = state.tasks.find((t) => t.sourceId === scopeId);
      if (!task) {
        // Auto-create on backlog/live SSE when the local task is gone
        // (page refresh mid-ingest). Skip ``completed`` so the historical
        // backlog doesn't pop toasts for already-finished sources.
        if (e.type === 'source.ingest.completed') return;
        const fileName =
          (typeof payload.filename === 'string' && payload.filename) ||
          (typeof payload.job_name === 'string' && payload.job_name) ||
          scopeId;
        const previouslyDismissed = isDismissed(
          state.dismissedSourceIds,
          scopeId,
        );
        task = {
          id: scopeId,
          fileName,
          progress: 0,
          status: 'training',
          sourceId: scopeId,
          dismissed: previouslyDismissed,
        };
        state.tasks.push(task);
        task = state.tasks[state.tasks.length - 1];
      }
      const wasTerminal =
        task.status === 'completed' || task.status === 'failed';
      const sourceWasDismissed =
        !!task.sourceId && isDismissed(state.dismissedSourceIds, task.sourceId);

      switch (e.type) {
        case 'source.ingest.queued':
          // Don't regress a task already past 'training' (e.g. the
          // queued event arrives after the upload XHR finished and
          // status flipped to 'training'). Idempotent on retries.
          if (task.status === 'preparing' || task.status === 'uploading') {
            task.status = 'training';
            task.progress = 0;
          }
          break;
        case 'source.ingest.progress': {
          const current = Number(payload.current);
          if (!Number.isFinite(current)) break;
          // Clamp + monotonic — never regress an already-higher value.
          const clamped = Math.max(0, Math.min(100, current));
          if (task.status === 'completed' || task.status === 'failed') break;
          task.status = 'training';
          if (clamped > task.progress) task.progress = clamped;
          break;
        }
        case 'source.ingest.completed':
          if (payload.limited === true) {
            // Token-cap reached during ingest — surface as a failure
            // so the toast shows the translated limit message rather
            // than a misleading success state.
            task.status = 'failed';
            task.progress = 100;
            task.tokenLimitReached = true;
            task.errorMessage = undefined;
            // Only un-dismiss on the initial terminal transition;
            // duplicate envelopes (StrictMode remount, reconnect
            // overlap) must not re-pop a user-dismissed toast.
            if (!wasTerminal && !sourceWasDismissed) task.dismissed = false;
          } else {
            task.status = 'completed';
            task.progress = 100;
            task.errorMessage = undefined;
            task.tokenLimitReached = false;
            if (!wasTerminal && !sourceWasDismissed) task.dismissed = false;
          }
          break;
        case 'source.ingest.failed':
          task.status = 'failed';
          task.errorMessage =
            typeof payload.error === 'string'
              ? payload.error
              : 'Ingestion failed.';
          if (!wasTerminal && !sourceWasDismissed) task.dismissed = false;
          break;
        default:
          break;
      }
    });
  },
});

export const {
  addAttachment,
  updateAttachment,
  removeAttachment,
  reorderAttachments,
  clearAttachments,
  addUploadTask,
  updateUploadTask,
  dismissUploadTask,
  removeUploadTask,
} = uploadSlice.actions;

export const selectAttachments = (state: RootState) => state.upload.attachments;
export const selectCompletedAttachments = createSelector(
  [selectAttachments],
  (attachments) => attachments.filter((att) => att.status === 'completed'),
);
export const selectUploadTasks = (state: RootState) => state.upload.tasks;

export default uploadSlice.reducer;
