import { describe, expect, it } from 'vitest';

import reducer, { addQuery, raiseError } from './agentPreviewSlice';

describe('agent preview curated errors', () => {
  const seeded = () => reducer(undefined, addQuery({ prompt: 'q' }));

  it('keeps the code and params of a curated error', () => {
    const next = reducer(
      seeded(),
      raiseError({
        index: 0,
        message: 'Too large.',
        code: 'context_length_exceeded',
        params: { needed_tokens: 300000, available_tokens: 200000 },
      }),
    );
    expect(next.queries[0].error).toBe('Too large.');
    expect(next.queries[0].errorCode).toBe('context_length_exceeded');
    expect(next.queries[0].errorParams).toEqual({
      needed_tokens: 300000,
      available_tokens: 200000,
    });
  });

  it('drops a stale code when a later error has none', () => {
    let state = reducer(
      seeded(),
      raiseError({ index: 0, message: 'x', code: 'server_error' }),
    );
    state = reducer(state, raiseError({ index: 0, message: 'raw' }));
    expect(state.queries[0].errorCode).toBeUndefined();
    expect(state.queries[0].errorParams).toBeUndefined();
  });
});
