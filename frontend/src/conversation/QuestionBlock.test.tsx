import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import QuestionBlock from './QuestionBlock';
import type { ToolCallsType } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const QUESTIONS = [
  {
    id: 'q1',
    text: 'Which quarter?',
    note: null,
    multi: false,
    options: [
      { id: 'a', label: 'Q3 2026' },
      { id: 'b', label: 'Q4 2026 so far' },
    ],
  },
  {
    id: 'q2',
    text: "Who's it for?",
    note: null,
    multi: false,
    options: [
      { id: 'a', label: 'External' },
      { id: 'b', label: 'Internal' },
    ],
  },
];

const paused: ToolCallsType = {
  tool_name: 'ask_user',
  action_name: 'ask_user',
  call_id: 'ask-1',
  arguments: {},
  status: 'awaiting_answer',
  message: 'Two things change what goes in it:',
  questions: QUESTIONS,
};

// As the server saves the call once the turn moved on.
const saved = (overrides: Partial<ToolCallsType>): ToolCallsType => ({
  tool_name: 'ask_user',
  action_name: 'ask_user',
  call_id: 'ask-1',
  arguments: {
    message: 'Two things change what goes in it:',
    questions: QUESTIONS,
  },
  ...overrides,
});

describe('QuestionBlock', () => {
  let container: HTMLDivElement;
  let root: Root;
  const onAction = vi.fn();

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    onAction.mockReset();
  });

  const render = (call: ToolCallsType, withAction = true) =>
    act(async () =>
      root.render(
        <QuestionBlock
          call={call}
          onAction={withAction ? onAction : undefined}
        />,
      ),
    );
  const button = (label: string) =>
    Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === label,
    );
  const card = (id: string) =>
    container.querySelector<HTMLElement>(`[data-question="${id}"]`)!;
  const pick = (id: string, label: string) => {
    const el = Array.from(card(id).querySelectorAll('label')).find(
      (l) => l.textContent === label,
    )!;
    return document.getElementById(el.htmlFor)!;
  };

  it('shows the lead-in line and question cards on the answer column', async () => {
    await render(paused);
    const column = container.querySelector('.mr-5.ml-6')!;
    expect(column.textContent).toContain('Two things change what goes in it:');
    expect(column.querySelectorAll('[data-question]')).toHaveLength(2);
    expect(card('q1').getAttribute('data-slot')).toBe('card');
    expect(button('questions.sendAnswers')).toBeDefined();
    expect(button('questions.justAnswer')).toBeDefined();
  });

  it('resumes with the composed answers, or with Just answer', async () => {
    await render(paused);
    await act(async () => pick('q1', 'Q3 2026').click());
    await act(async () => pick('q2', 'External').click());
    await act(async () => button('questions.sendAnswers')!.click());
    expect(onAction).toHaveBeenCalledWith('ask-1', {
      answer: "Which quarter? → Q3 2026\nWho's it for? → External",
    });
    await act(async () => button('questions.justAnswer')!.click());
    expect(onAction).toHaveBeenLastCalledWith('ask-1', { skipped: true });
  });

  it('comes back with what was picked when the server refuses the answers', async () => {
    await render(paused);
    await act(async () => pick('q1', 'Q4 2026 so far').click());
    await act(async () => button('questions.sendAnswers')!.click());
    // The cards fold into the record at once, then come back waiting (in
    // the turn's error branch, so a fresh mount).
    await render(saved({ status: 'success', result: 'x' as never }));
    await act(async () => root.unmount());
    root = createRoot(container);
    await render(paused);
    expect(pick('q1', 'Q4 2026 so far').getAttribute('data-state')).toBe(
      'checked',
    );
    await act(async () => pick('q2', 'Internal').click());
    await act(async () => button('questions.sendAnswers')!.click());
    expect(onAction).toHaveBeenLastCalledWith('ask-1', {
      answer: "Which quarter? → Q4 2026 so far\nWho's it for? → Internal",
    });
  });

  it('starts empty for other questions under a reused call id', async () => {
    await render(paused);
    await act(async () => pick('q1', 'Q3 2026').click());
    await act(async () => root.unmount());
    root = createRoot(container);
    await render({
      ...paused,
      questions: [{ ...QUESTIONS[0], text: 'Which year?' }],
    });
    expect(pick('q1', 'Q3 2026').getAttribute('data-state')).toBe('unchecked');
  });

  it('cannot be answered where the turn cannot resume', async () => {
    await render(paused, false);
    expect(button('questions.sendAnswers')).toBeUndefined();
    expect(container.querySelector('[role="radio"]')).toBeNull();
  });

  it('folds an answered call into each question and its answer', async () => {
    await render(
      saved({ status: 'success', result: 'Which quarter? → Q3 2026' as never }),
    );
    expect(button('questions.sendAnswers')).toBeUndefined();
    expect(card('q1').textContent).toContain('Q3 2026');
    expect(card('q2').textContent).toContain('questions.notAnswered');
    expect(container.textContent).toContain(
      'Two things change what goes in it:',
    );
  });

  it('folds the questions into one card when a reply was typed', async () => {
    await render(saved({ status: 'success', result: 'Q3, for them' as never }));
    expect(container.querySelector('[data-question]')).toBeNull();
    const record = container.querySelector('[data-slot="question-record"]')!;
    expect(record.textContent).toBe(
      "1. Which quarter?2. Who's it for?questions.answeredInMessage",
    );
  });

  it("shows a typed reply as the user's own bubble after the record", async () => {
    await render(saved({ status: 'success', result: 'Q3, for them' as never }));
    const bubble = container.querySelector<HTMLElement>(
      '[data-slot="question-reply"]',
    )!;
    expect(bubble.textContent).toBe('Q3, for them');
    expect(bubble.className).toContain('bg-secondary');
    expect(
      container
        .querySelector('[data-slot="question-record"]')!
        .compareDocumentPosition(bubble) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('shows a reply typed for a lone question as a bubble too', async () => {
    await render(
      saved({
        status: 'success',
        arguments: { questions: QUESTIONS.slice(0, 1) },
        result: 'Q3 please' as never,
      }),
    );
    expect(
      container.querySelector('[data-slot="question-record"]')!.textContent,
    ).toBe('Which quarter?questions.answeredInMessage');
    expect(
      container.querySelector('[data-slot="question-reply"]')!.textContent,
    ).toBe('Q3 please');
  });

  it('marks skipped and retired questions', async () => {
    await render(saved({ status: 'skipped' }));
    expect(card('q1').textContent).toContain('questions.skipped');
    expect(card('q2').textContent).toContain('questions.skipped');
    await render(
      saved({
        status: 'denied',
        not_run: 'moved_on',
        result: 'Not answered: the conversation moved on.' as never,
      }),
    );
    expect(card('q1').textContent).toContain('questions.notAnswered');
  });
});
