import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { RootState } from '../store';

export interface Attachment {
  fileName: string;
  progress: number;
  status: 'uploading' | 'processing' | 'completed' | 'failed';
  taskId: string;
  id?: string;
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
        taskId: string;
        updates: Partial<Attachment>;
      }>,
    ) => {
      const index = state.attachments.findIndex(
        (att) => att.taskId === action.payload.taskId,
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
        (att) => att.taskId !== action.payload && att.id !== action.payload,
      );
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
  clearAttachments,
  addUploadTask,
  updateUploadTask,
  dismissUploadTask,
  removeUploadTask,
} = uploadSlice.actions;

export const selectAttachments = (state: RootState) => state.upload.attachments;
export const selectCompletedAttachments = (state: RootState) =>
  state.upload.attachments.filter((att) => att.status === 'completed');
export const selectUploadTasks = (state: RootState) => state.upload.tasks;

export default uploadSlice.reducer;
