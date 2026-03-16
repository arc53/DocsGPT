import { createSelector, createSlice, PayloadAction } from '@reduxjs/toolkit';
import { RootState } from '../store';

export interface Attachment {
  id: string; // Unique identifier for the attachment (required for state management)
  fileName: string;
  progress: number;
  status: 'uploading' | 'processing' | 'completed' | 'failed';
  taskId: string; // Server-assigned task ID (used for API calls)
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
