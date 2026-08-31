import { describe, expect, it } from 'vitest';

import {
  AnswerSegment,
  appendThoughtText,
  getAnswerSegments,
  recordToolCall,
  synthesizeSegments,
} from './answerSegments';
import { ToolCallsType } from './types';

const call = (overrides: Partial<ToolCallsType> = {}): ToolCallsType => ({
  tool_name: 'brave',
  action_name: 'brave_web_search',
  call_id: 'c1',
  arguments: {},
  status: 'completed',
  ...overrides,
});

describe('appendThoughtText', () => {
  it('coalesces consecutive reasoning deltas', () => {
    const segments: AnswerSegment[] = [];
    appendThoughtText(segments, 'I should ');
    appendThoughtText(segments, 'search');
    expect(segments).toEqual([{ kind: 'thought', text: 'I should search' }]);
  });

  it('starts a new reasoning step after a tool call', () => {
    const segments: AnswerSegment[] = [];
    appendThoughtText(segments, 'plan');
    recordToolCall(segments, 'c1');
    appendThoughtText(segments, 'now verify');
    expect(segments).toEqual([
      { kind: 'thought', text: 'plan' },
      { kind: 'tool', call_id: 'c1' },
      { kind: 'thought', text: 'now verify' },
    ]);
  });
});

describe('recordToolCall', () => {
  it('records a call once even though pending and completed both fire', () => {
    const segments: AnswerSegment[] = [];
    recordToolCall(segments, 'c1');
    recordToolCall(segments, 'c1');
    expect(segments).toEqual([{ kind: 'tool', call_id: 'c1' }]);
  });

  it('keeps arrival order across several calls', () => {
    const segments: AnswerSegment[] = [];
    recordToolCall(segments, 'c1');
    recordToolCall(segments, 'c2');
    recordToolCall(segments, 'c1');
    expect(segments).toEqual([
      { kind: 'tool', call_id: 'c1' },
      { kind: 'tool', call_id: 'c2' },
    ]);
  });

  it('ignores an empty call id', () => {
    const segments: AnswerSegment[] = [];
    recordToolCall(segments, '');
    expect(segments).toEqual([]);
  });
});

describe('synthesizeSegments / getAnswerSegments', () => {
  it('orders a reloaded answer as reasoning then tool calls', () => {
    expect(
      synthesizeSegments({
        thought: 'reasoning',
        tool_calls: [call({ call_id: 'c1' }), call({ call_id: 'c2' })],
      }),
    ).toEqual([
      { kind: 'thought', text: 'reasoning' },
      { kind: 'tool', call_id: 'c1' },
      { kind: 'tool', call_id: 'c2' },
    ]);
  });

  it('omits fields that are absent', () => {
    expect(synthesizeSegments({ thought: 'only reasoning' })).toEqual([
      { kind: 'thought', text: 'only reasoning' },
    ]);
    expect(synthesizeSegments({})).toEqual([]);
  });

  it('prefers live steps when present', () => {
    const live: AnswerSegment[] = [
      { kind: 'thought', text: 'live' },
      { kind: 'tool', call_id: 'c1' },
    ];
    expect(
      getAnswerSegments({
        thought: 'live',
        tool_calls: [call({ call_id: 'c1' })],
        segments: live,
      }),
    ).toBe(live);
  });

  it('falls back when steps were cleared by a tail snapshot', () => {
    expect(getAnswerSegments({ thought: 'flat', segments: [] })).toEqual([
      { kind: 'thought', text: 'flat' },
    ]);
  });

  it('falls back when the order misses a call the answer holds', () => {
    expect(
      getAnswerSegments({
        thought: 'reasoning',
        tool_calls: [call({ call_id: 'c1' }), call({ call_id: 'c2' })],
        segments: [{ kind: 'tool', call_id: 'c2' }],
      }),
    ).toEqual([
      { kind: 'thought', text: 'reasoning' },
      { kind: 'tool', call_id: 'c1' },
      { kind: 'tool', call_id: 'c2' },
    ]);
  });

  it('falls back when the order misses reasoning the answer holds', () => {
    expect(
      getAnswerSegments({
        thought: 'full reasoning',
        tool_calls: [call({ call_id: 'c1' })],
        segments: [
          { kind: 'tool', call_id: 'c1' },
          { kind: 'thought', text: 'reasoning' },
        ],
      }),
    ).toEqual([
      { kind: 'thought', text: 'full reasoning' },
      { kind: 'tool', call_id: 'c1' },
    ]);
  });

  it('keeps the live order when reasoning arrived in several pieces', () => {
    const live: AnswerSegment[] = [
      { kind: 'thought', text: 'plan' },
      { kind: 'tool', call_id: 'c1' },
      { kind: 'thought', text: 'verify' },
    ];
    expect(
      getAnswerSegments({
        thought: 'planverify',
        tool_calls: [call({ call_id: 'c1' })],
        segments: live,
      }),
    ).toBe(live);
  });

  it('does not fall back for a call the backend left without an id', () => {
    const live: AnswerSegment[] = [{ kind: 'tool', call_id: 'c1' }];
    expect(
      getAnswerSegments({
        tool_calls: [call({ call_id: 'c1' }), call({ call_id: '' })],
        segments: live,
      }),
    ).toBe(live);
  });
});
