import { describe, expect, it } from 'vitest';

import {
  AnswerSegment,
  appendAnswerText,
  appendThoughtText,
  getAnswerSegments,
  hydrateSegments,
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

describe('appendAnswerText', () => {
  it('coalesces answer deltas and splits them around a tool call', () => {
    const segments: AnswerSegment[] = [];
    appendAnswerText(segments, 'Now ');
    appendAnswerText(segments, 'step 2:');
    recordToolCall(segments, 'c1');
    appendAnswerText(segments, 'Done.');
    appendAnswerText(segments, '');
    expect(segments).toEqual([
      { kind: 'text', text: 'Now step 2:' },
      { kind: 'tool', call_id: 'c1' },
      { kind: 'text', text: 'Done.' },
    ]);
  });
});

describe('hydrateSegments', () => {
  it('slices the saved lengths out of the response and the reasoning', () => {
    expect(
      hydrateSegments(
        [
          { kind: 'thought', length: 4 },
          { kind: 'text', length: 3 },
          { kind: 'tool', call_id: 'c1' },
          { kind: 'thought', length: 6 },
          { kind: 'text', length: 5 },
        ],
        'abc😀 ok',
        'planverify',
      ),
    ).toEqual([
      { kind: 'thought', text: 'plan' },
      { kind: 'text', text: 'abc' },
      { kind: 'tool', call_id: 'c1' },
      { kind: 'thought', text: 'verify' },
      { kind: 'text', text: '😀 ok' },
    ]);
  });

  it('drops an order that does not fit what was saved', () => {
    expect(
      hydrateSegments([{ kind: 'text', length: 10 }], 'short', ''),
    ).toBeUndefined();
    expect(hydrateSegments([{ kind: 'bogus' }], 'x', '')).toBeUndefined();
    expect(hydrateSegments(null, 'x', '')).toBeUndefined();
    expect(hydrateSegments([], 'x', '')).toBeUndefined();
  });
});

describe('getAnswerSegments with answer text', () => {
  const calls = [call({ call_id: 'c1' })];

  it('keeps an order whose text accounts for the whole answer', () => {
    const live: AnswerSegment[] = [
      { kind: 'text', text: 'Now:' },
      { kind: 'tool', call_id: 'c1' },
      { kind: 'text', text: 'Done.' },
    ];
    expect(
      getAnswerSegments({
        response: 'Now:Done.',
        tool_calls: calls,
        segments: live,
      }),
    ).toBe(live);
  });

  it('falls back when the answer was replaced after the order was recorded', () => {
    expect(
      getAnswerSegments({
        response: 'Blocked by a guardrail.',
        tool_calls: calls,
        segments: [
          { kind: 'text', text: 'Now:' },
          { kind: 'tool', call_id: 'c1' },
        ],
      }),
    ).toEqual([
      { kind: 'tool', call_id: 'c1' },
      { kind: 'text', text: 'Blocked by a guardrail.' },
    ]);
  });

  it('puts the answer after the steps when the order recorded no text', () => {
    expect(
      getAnswerSegments({
        response: 'the answer',
        thought: 'plan',
        tool_calls: calls,
        segments: [
          { kind: 'thought', text: 'plan' },
          { kind: 'tool', call_id: 'c1' },
        ],
      }),
    ).toEqual([
      { kind: 'thought', text: 'plan' },
      { kind: 'tool', call_id: 'c1' },
      { kind: 'text', text: 'the answer' },
    ]);
  });

  it('synthesizes the answer text last for a reload with no order', () => {
    expect(
      getAnswerSegments({ response: 'the answer', tool_calls: calls }),
    ).toEqual([
      { kind: 'tool', call_id: 'c1' },
      { kind: 'text', text: 'the answer' },
    ]);
  });
});
