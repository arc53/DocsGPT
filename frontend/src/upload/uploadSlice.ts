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

interface UploadState {
  attachments: Attachment[];
}

const initialState: UploadState = {
  attachments: [],
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
  },
});

export const {
  addAttachment,
  updateAttachment,
  removeAttachment,
  clearAttachments,
} = uploadSlice.actions;

export const selectAttachments = (state: RootState) => state.upload.attachments;
export const selectCompletedAttachments = (state: RootState) =>
  state.upload.attachments.filter((att) => att.status === 'completed');

export default uploadSlice.reducer;
