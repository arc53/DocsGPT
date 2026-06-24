import { describe, expect, it } from 'vitest';

import { Attachment } from '../../upload/uploadSlice';
import reducer, {
  addQuery,
  collectCompletedAttachmentIds,
  setWorkflowRunId,
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
