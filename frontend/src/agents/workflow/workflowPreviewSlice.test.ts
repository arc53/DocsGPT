import { describe, expect, it } from 'vitest';

import { Attachment } from '../../upload/uploadSlice';
import reducer, {
  addQuery,
  collectCompletedAttachmentIds,
  collectRunAttachmentIds,
  previewSendBlockReason,
  resetWorkflowPreview,
  setPreviewOpen,
  setWorkflowRunId,
  UNSAVED_DRAFT_ATTACHMENTS_MESSAGE,
} from './workflowPreviewSlice';

const seedState = () => reducer(undefined, { type: '@@INIT' });

const att = (over: Partial<Attachment>): Attachment => ({
  id: 'a1',
  fileName: 'f.pdf',
  progress: 100,
  status: 'completed',
  taskId: 't1',
  ...over,
});

describe('collectCompletedAttachmentIds', () => {
  it('returns ids of completed attachments only', () => {
    const ids = collectCompletedAttachmentIds([
      att({ id: 'done', status: 'completed' }),
      att({ id: 'busy', status: 'processing' }),
      att({ id: 'up', status: 'uploading' }),
      att({ id: 'bad', status: 'failed' }),
    ]);
    expect(ids).toEqual(['done']);
  });

  it('drops completed rows with no server id and returns [] when none', () => {
    expect(
      collectCompletedAttachmentIds([att({ id: '', status: 'completed' })]),
    ).toEqual([]);
    expect(collectCompletedAttachmentIds([])).toEqual([]);
  });
});

describe('collectRunAttachmentIds', () => {
  const completed = [att({ id: 'done', status: 'completed' })];

  it('returns completed ids for a saved workflow', () => {
    expect(collectRunAttachmentIds(completed, 'wf-1')).toEqual(['done']);
  });

  it('returns [] for an unsaved draft so uploads are neither sent nor cleared', () => {
    expect(collectRunAttachmentIds(completed, null)).toEqual([]);
    expect(collectRunAttachmentIds(completed, undefined)).toEqual([]);
    expect(collectRunAttachmentIds(completed, '')).toEqual([]);
  });
});

describe('previewSendBlockReason', () => {
  it('blocks an unsaved draft that has completed attachments', () => {
    expect(previewSendBlockReason(null, true)).toBe(
      UNSAVED_DRAFT_ATTACHMENTS_MESSAGE,
    );
    expect(previewSendBlockReason(undefined, true)).toBe(
      UNSAVED_DRAFT_ATTACHMENTS_MESSAGE,
    );
    expect(previewSendBlockReason('', true)).toBe(
      UNSAVED_DRAFT_ATTACHMENTS_MESSAGE,
    );
  });

  it('allows a saved workflow, or an unsaved draft with no attachments', () => {
    expect(previewSendBlockReason('wf-1', true)).toBeNull();
    expect(previewSendBlockReason('wf-1', false)).toBeNull();
    expect(previewSendBlockReason(null, false)).toBeNull();
  });
});

describe('setWorkflowRunId', () => {
  it('stores the run id on the addressed query', () => {
    let state = seedState();
    state = reducer(state, addQuery({ prompt: 'run it' }));
    state = reducer(
      state,
      setWorkflowRunId({ index: 0, workflowRunId: 'run-1' }),
    );
    expect(state.queries[0].workflowRunId).toBe('run-1');
  });

  it('ignores an out-of-range index without throwing', () => {
    let state = seedState();
    state = reducer(state, addQuery({ prompt: 'q' }));
    state = reducer(
      state,
      setWorkflowRunId({ index: 5, workflowRunId: 'run-x' }),
    );
    expect(state.queries[0].workflowRunId).toBeUndefined();
  });
});

describe('setPreviewOpen', () => {
  it('defaults to closed and toggles the preview-open flag', () => {
    let state = seedState();
    expect(state.previewOpen).toBe(false);
    state = reducer(state, setPreviewOpen(true));
    expect(state.previewOpen).toBe(true);
    state = reducer(state, setPreviewOpen(false));
    expect(state.previewOpen).toBe(false);
  });

  it('survives a resetWorkflowPreview so the overlay flag stays set', () => {
    let state = seedState();
    state = reducer(state, setPreviewOpen(true));
    state = reducer(state, addQuery({ prompt: 'q' }));
    state = reducer(state, resetWorkflowPreview());
    expect(state.queries).toEqual([]);
    expect(state.previewOpen).toBe(true);
  });
});
