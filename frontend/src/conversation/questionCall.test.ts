import { describe, expect, it } from 'vitest';

import type { Query } from './conversationModels';
import {
  answeredCall,
  isHiddenCall,
  pendingQuestionCall,
  questionState,
  readAnswers,
  readQuestions,
} from './questionCall';
import type { ToolCallsType } from './types';

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
    note: 'Margins stay internal.',
    multi: false,
    options: [
      { id: 'a', label: 'External' },
      { id: 'b', label: 'Internal' },
    ],
  },
];

const askUser = (overrides: Partial<ToolCallsType> = {}): ToolCallsType => ({
  tool_name: 'ask_user',
  action_name: 'ask_user',
  call_id: 'ask-1',
  arguments: {},
  status: 'awaiting_answer',
  message: 'Two things change what goes in it:',
  questions: QUESTIONS,
  ...overrides,
});

describe('questionState', () => {
  it('reads a paused, answered, skipped and retired call', () => {
    expect(questionState(askUser())).toBe('awaiting');
    const saved = {
      questions: undefined,
      message: undefined,
      arguments: { message: 'Lead', questions: QUESTIONS },
    };
    expect(
      questionState(askUser({ ...saved, status: 'success', result: {} })),
    ).toBe('answered');
    expect(questionState(askUser({ ...saved, status: 'skipped' }))).toBe(
      'skipped',
    );
    expect(
      questionState(
        askUser({ ...saved, status: 'denied', not_run: 'moved_on' }),
      ),
    ).toBe('not_run');
  });

  it('leaves other calls, refusals and the text path as steps', () => {
    expect(
      questionState({ ...askUser(), tool_name: 'notes', action_name: 'add' }),
    ).toBeNull();
    const refused = askUser({
      status: 'error',
      error_type: 'questions_not_asked',
    });
    expect(questionState(refused)).toBeNull();
    expect(isHiddenCall(refused)).toBe(true);
    expect(isHiddenCall(askUser())).toBe(false);
    // Shown as answer text by a caller without cards: the server marks it,
    // whatever its result says.
    const asText = askUser({
      status: 'success',
      shown_as: 'text',
      result: 'Reworded later.' as never,
    });
    expect(questionState(asText)).toBeNull();
    // An answered call whose answer happens to start like that is still one.
    const answered = askUser({
      status: 'success',
      result: 'Shown to the user as text, please → Yes' as never,
    });
    expect(questionState(answered)).toBe('answered');
  });
});

describe('readQuestions', () => {
  it('keeps usable questions and reads string options', () => {
    expect(
      readQuestions([
        { text: 'Pick', options: ['One', 'Two'], multi: true },
        { text: '' },
        'nope',
      ]),
    ).toEqual([
      {
        id: 'q1',
        text: 'Pick',
        note: null,
        multi: true,
        options: [
          { id: '0', label: 'One', input: null, exclusive: false },
          { id: '1', label: 'Two', input: null, exclusive: false },
        ],
        placeholder: null,
      },
    ]);
    expect(readQuestions(null)).toEqual([]);
  });

  it('keeps an option that opens a field and one that rules out the rest', () => {
    const [question] = readQuestions([
      {
        text: 'Where do HR cases go?',
        multi: true,
        options: [
          { id: 'a', label: 'HR team email', input: 'hr@…', exclusive: false },
          { id: 'b', label: 'Their manager', input: '  ', exclusive: false },
          { id: 'c', label: 'Nowhere', input: null, exclusive: true },
        ],
      },
    ]);
    expect(question.options).toEqual([
      { id: 'a', label: 'HR team email', input: 'hr@…', exclusive: false },
      { id: 'b', label: 'Their manager', input: null, exclusive: false },
      { id: 'c', label: 'Nowhere', input: null, exclusive: true },
    ]);
  });
});

describe('readAnswers', () => {
  const questions = readQuestions(QUESTIONS);

  it('reads each answered question from its line', () => {
    expect(readAnswers(questions, 'Which quarter? → Q3 2026')).toEqual({
      answers: { q1: 'Q3 2026' },
      reply: null,
    });
  });

  // The server keeps line breaks inside a question's text, and a typed
  // answer can have them too: lines alone can't tell the answers apart.
  it('reads answers whose question or answer runs over several lines', () => {
    const multiline = readQuestions([
      {
        ...QUESTIONS[0],
        text: 'Which quarter?\nPick the one the deck covers.',
      },
      { ...QUESTIONS[1], text: "Who's it for?\nMargins stay internal." },
    ]);
    const composed =
      'Which quarter?\nPick the one the deck covers. → Q3 2026\n' +
      "Who's it for?\nMargins stay internal. → External, the board\nand the CFO";
    expect(readAnswers(multiline, composed)).toEqual({
      answers: { q1: 'Q3 2026', q2: 'External, the board\nand the CFO' },
      reply: null,
    });
    expect(
      readAnswers(
        multiline.slice(0, 1),
        'Which quarter?\nPick the one the deck covers. → Q3 2026',
      ),
    ).toEqual({ answers: { q1: 'Q3 2026' }, reply: null });
    // Only the second answered.
    expect(
      readAnswers(
        multiline,
        "Who's it for?\nMargins stay internal. → Internal",
      ),
    ).toEqual({ answers: { q2: 'Internal' }, reply: null });
  });

  it('reads several answered questions in order', () => {
    expect(
      readAnswers(
        questions,
        "Which quarter? → Q3 2026\nWho's it for? → Internal",
      ),
    ).toEqual({ answers: { q1: 'Q3 2026', q2: 'Internal' }, reply: null });
  });

  it('takes a typed reply as the answer of a lone question', () => {
    expect(readAnswers(questions.slice(0, 1), 'last one')).toEqual({
      answers: { q1: 'last one' },
      reply: null,
    });
    expect(readAnswers(questions, 'Q3, for them')).toEqual({
      answers: {},
      reply: 'Q3, for them',
    });
  });
});

describe('pendingQuestionCall', () => {
  it('finds the question the latest turn waits on', () => {
    const turn: Query = { prompt: 'deck', tool_calls: [askUser()] };
    expect(pendingQuestionCall([turn])?.call_id).toBe('ask-1');
    expect(
      pendingQuestionCall([turn, { prompt: 'next', response: 'ok' }]),
    ).toBeNull();
  });
});

describe('answeredCall', () => {
  it('records the answer with the questions as arguments', () => {
    expect(answeredCall(askUser(), { answer: 'Which quarter? → Q3' })).toEqual({
      call_id: 'ask-1',
      arguments: {
        message: 'Two things change what goes in it:',
        questions: readQuestions(QUESTIONS),
      },
      status: 'success',
      result: 'Which quarter? → Q3',
    });
    expect(answeredCall(askUser(), { skipped: true }).status).toBe('skipped');
  });
});
