import { createSelector, createSlice, PayloadAction } from '@reduxjs/toolkit';

import { sseEventReceived } from '../notifications/notificationsSlice';
import { RootState } from '../store';

export interface Attachment {
  id: string; // Client-side state-management id (uuid generated in MessageInput)
  fileName: string;
  progress: number;
  status: 'uploading' | 'processing' | 'completed' | 'failed';
  taskId: string; // Server-assigned celery task ID (used for API calls)
  /**
   * Server-assigned attachment id (stable across the lifecycle —
   * Phase 3A's ``attachment.*`` SSE events use this in ``scope.id``).
   * Set as soon as the upload response returns. Distinct from
   * ``id`` (client) and ``taskId`` (celery).
   */
  attachmentId?: string;
  /**
   * ``Date.now()`` of the last SSE event that matched this attachment
   * by ``attachmentId``. Drives the per-attachment push-freshness
   * gate in MessageInput's polling loop — same pattern as
   * ``UploadTask.lastEventAt``.
   */
  lastEventAt?: number;
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
  /**
   * ``Date.now()`` of the last SSE event that matched this task by
   * ``sourceId``. Drives the per-task push-freshness gate: if the
   * channel is globally healthy but this task hasn't seen an event in
   * a while, the polling loop falls back rather than skipping. Unset
   * until the first matching event arrives.
   */
  lastEventAt?: number;
  errorMessage?: string;
  dismissed?: boolean;
}

interface UploadState {
  attachments: Attachment[];
  tasks: UploadTask[];
}

const initialState: UploadState = {
  attachments: [],
  tasks: [],
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

        // When task completes or fails, set dismissed to false to notify user
        if (updates.status === 'completed' || updates.status === 'failed') {
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
      // to ``state.attachments`` matched by ``attachmentId``. Each
      // tab's slice handles attachments it knows about — events for
      // attachments uploaded in another session are silently dropped.
      if (e.type.startsWith('attachment.') && scopeId) {
        const attachment = state.attachments.find(
          (a) => a.attachmentId === scopeId,
        );
        if (attachment) {
          const payload = (e.payload || {}) as Record<string, unknown>;
          attachment.lastEventAt = Date.now();
          switch (e.type) {
            case 'attachment.queued':
            case 'attachment.processing.progress': {
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
              // Mirror the polling path (MessageInput.tsx:870):
              // replace the client-generated uuid with the server's
              // attachment id so question submission
              // (Conversation.tsx:174) sends an id the backend can
              // resolve. Without this, push-fresh attachments skip
              // polling and get submitted with the UI uuid, and the
              // backend silently drops them from the message context.
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
      const task = state.tasks.find((t) => t.sourceId === scopeId);
      if (!task) return;
      const payload = (e.payload || {}) as Record<string, unknown>;
      // Stamp the per-task freshness clock on every matching event so
      // ``Upload.tsx`` can prove this task is hearing from its worker
      // — independent of the global SSE channel-health flag.
      task.lastEventAt = Date.now();

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
          task.status = 'completed';
          task.progress = 100;
          task.errorMessage = undefined;
          task.dismissed = false;
          break;
        case 'source.ingest.failed':
          task.status = 'failed';
          task.errorMessage =
            typeof payload.error === 'string'
              ? payload.error
              : 'Ingestion failed.';
          task.dismissed = false;
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
