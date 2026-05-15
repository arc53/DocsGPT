import { describe, expect, it } from 'vitest';

import reducer, {
  applyMessageTail,
  setConversation,
} from './conversationSlice';

const baseQuery = {
  prompt: 'tell me a poem',
  messageId: 'm-1',
  messageStatus: 'pending' as const,
};

const seedSlice = () => reducer(undefined, setConversation([baseQuery]));

describe('applyMessageTail — streaming partial', () => {
  it('writes response to the query while status is streaming', () => {
    const state = seedSlice();
    const next = reducer(
      state,
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'streaming',
          response: 'Hello, par',
          thought: null,
          sources: [],
          tool_calls: [],
        },
      }),
    );
    expect(next.queries[0].messageStatus).toBe('streaming');
    expect(next.queries[0].response).toBe('Hello, par');
  });

  it('updates response on each successive tail tick', () => {
    let state = seedSlice();
    state = reducer(
      state,
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'streaming',
          response: 'Hello',
          sources: [],
          tool_calls: [],
        },
      }),
    );
    state = reducer(
      state,
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'streaming',
          response: 'Hello, world',
          sources: [],
          tool_calls: [],
        },
      }),
    );
    expect(state.queries[0].response).toBe('Hello, world');
  });

  it('applies sources and tool_calls when they appear mid-stream', () => {
    const state = seedSlice();
    const next = reducer(
      state,
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'streaming',
          response: 'partial',
          sources: [{ id: 's1', title: 'doc' }],
          tool_calls: [{ name: 'search' }],
        },
      }),
    );
    expect(next.queries[0].sources).toEqual([{ id: 's1', title: 'doc' }]);
    expect(next.queries[0].tool_calls).toEqual([{ name: 'search' }]);
  });

  it('ignores empty sources / tool_calls arrays so the renderer stays clean', () => {
    const state = seedSlice();
    const next = reducer(
      state,
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'streaming',
          response: 'partial',
          sources: [],
          tool_calls: [],
        },
      }),
    );
    expect(next.queries[0].sources).toBeUndefined();
    expect(next.queries[0].tool_calls).toBeUndefined();
  });

  it('promotes to complete with the final response and clears any error', () => {
    let state = seedSlice();
    state = reducer(
      state,
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'streaming',
          response: 'partial',
        },
      }),
    );
    state = reducer(
      state,
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'complete',
          response: 'Final answer.',
        },
      }),
    );
    expect(state.queries[0].messageStatus).toBe('complete');
    expect(state.queries[0].response).toBe('Final answer.');
    expect(state.queries[0].error).toBeUndefined();
  });

  it('surfaces failed status as error and clears response', () => {
    const state = seedSlice();
    const next = reducer(
      state,
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'failed',
          response: 'whatever',
          error: 'worker died',
        },
      }),
    );
    expect(next.queries[0].messageStatus).toBe('failed');
    expect(next.queries[0].error).toBe('worker died');
    expect(next.queries[0].response).toBeUndefined();
  });
});
