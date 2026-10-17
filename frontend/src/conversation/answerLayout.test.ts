import { describe, expect, it } from 'vitest';

import { FlowItem, isNarration, layoutAnswer } from './answerLayout';
import { AnswerSegment } from './answerSegments';
import { ToolCallsType } from './types';

const call = (
  id: string,
  overrides: Partial<ToolCallsType> = {},
): ToolCallsType => ({
  tool_name: 'todo_list',
  action_name: 'todo_list',
  call_id: id,
  arguments: {},
  status: 'completed',
  ...overrides,
});

const tool = (id: string): AnswerSegment => ({ kind: 'tool', call_id: id });
const text = (value: string): AnswerSegment => ({ kind: 'text', text: value });
const thought = (value: string): AnswerSegment => ({
  kind: 'thought',
  text: value,
});

const layout = (steps: AnswerSegment[], calls: ToolCallsType[]) =>
  layoutAnswer(steps, new Map(calls.map((c) => [c.call_id, c])));

// A compact picture of the layout: kinds, with a group's entries inline.
const shape = (items: FlowItem[]) =>
  items.map((item) =>
    item.kind === 'group'
      ? `group(${item.entries.map((entry) => entry.kind).join(',')})`
      : item.kind,
  );

describe('layoutAnswer', () => {
  const calls = ['a', 'b', 'c', 'd'].map((id) => call(id));

  it('groups three or more steps in a row', () => {
    expect(
      shape(
        layout(
          [thought('plan'), tool('a'), tool('b'), tool('c'), text('Done.')],
          calls,
        ),
      ),
    ).toEqual(['thought', 'group(call,call,call)', 'text']);
  });

  it('leaves one or two steps as single rows', () => {
    expect(shape(layout([tool('a'), tool('b'), text('Done.')], calls))).toEqual(
      ['call', 'call', 'text'],
    );
  });

  it('folds short narration and reasoning between steps into the group', () => {
    const items = layout(
      [tool('a'), text('Now step 2:'), tool('b'), thought('hmm'), tool('c')],
      calls,
    );
    expect(shape(items)).toEqual(['group(call,note,call,thought,call)']);
  });

  it('keeps narration that follows the last step outside the group', () => {
    expect(
      shape(
        layout(
          [
            tool('a'),
            tool('b'),
            tool('c'),
            text('Let me check:'),
            thought('x'),
          ],
          calls,
        ),
      ),
    ).toEqual(['group(call,call,call)', 'text', 'thought']);
  });

  it('lets a long passage between steps split the run and stay in the answer', () => {
    const passage = '## Step 1\n\nThe contract ends on 31 December.';
    expect(
      shape(
        layout(
          [tool('a'), tool('b'), tool('c'), text(passage), tool('d')],
          calls,
        ),
      ),
    ).toEqual(['group(call,call,call)', 'text', 'call']);
  });

  it('ends a run at a card that carries actions', () => {
    const withApproval = [
      call('a'),
      call('b'),
      call('x', { status: 'awaiting_approval' }),
      call('c'),
      call('d'),
      call('e'),
    ];
    expect(
      shape(
        layout(
          [tool('a'), tool('b'), tool('x'), tool('c'), tool('d'), tool('e')],
          withApproval,
        ),
      ),
    ).toEqual(['call', 'call', 'call', 'group(call,call,call)']);
  });

  it('treats a wiki write and a scheduler call as cards', () => {
    const cards = [
      call('a'),
      call('w', { tool_name: 'wiki', action_name: 'wiki_create' }),
      call('s', { tool_name: 'scheduler', action_name: 'schedule_task' }),
      call('b'),
    ];
    expect(
      shape(layout([tool('a'), tool('w'), tool('s'), tool('b')], cards)),
    ).toEqual(['call', 'call', 'call', 'call']);
  });

  it('keeps a background job out of a step group: its card carries Cancel', () => {
    const steps = [
      call('a'),
      call('j', { status: 'pending', job_id: 'job-1' }),
      call('b'),
      call('c'),
      call('d'),
    ];
    expect(
      shape(
        layout([tool('a'), tool('j'), tool('b'), tool('c'), tool('d')], steps),
      ),
    ).toEqual(['call', 'call', 'group(call,call,call)']);
  });

  it('turns the notes of a run too short to group back into answer text', () => {
    const items = layout([tool('a'), text('Next:'), tool('b')], calls);
    expect(items.map((item) => item.kind)).toEqual(['call', 'text', 'call']);
  });

  it('drops steps whose call is missing and whitespace between steps', () => {
    expect(
      shape(
        layout(
          [tool('a'), text('\n\n'), tool('gone'), tool('b'), tool('c')],
          calls,
        ),
      ),
    ).toEqual(['group(call,call,call)']);
  });

  it('joins answer text that ends up side by side with a paragraph break', () => {
    const items = layout(
      [text('First.'), tool('gone'), text('Second.')],
      calls,
    );
    expect(items).toEqual([
      { kind: 'text', text: 'First.\n\nSecond.', index: 0 },
    ]);
  });
});

describe('isNarration', () => {
  it('accepts one short paragraph', () => {
    expect(
      isNarration('The crypto API returned 401. Trying a web search:'),
    ).toBe(true);
  });

  it('rejects structure, blank lines and long passages', () => {
    expect(isNarration('## Summary')).toBe(false);
    expect(isNarration('- a list item')).toBe(false);
    expect(isNarration('One.\n\nTwo.')).toBe(false);
    expect(isNarration('x'.repeat(401))).toBe(false);
    expect(isNarration('   ')).toBe(false);
  });
});
