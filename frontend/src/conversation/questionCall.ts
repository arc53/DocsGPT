import type { Question } from '../components/QuestionCards';
import type { Query } from './conversationModels';
import type { ToolCallsType } from './types';

/** The chat's clarifying-questions tool (docsgpt/agents/tools/ask_user.py). */
export const ASK_USER = 'ask_user';

/** What a resume sends for a question call: the answers, or Just answer. */
export type QuestionAction = { answer: string } | { skipped: true };

/** How an `ask_user` call shows: waiting for the user, or its folded record. */
export type QuestionState = 'awaiting' | 'answered' | 'skipped' | 'not_run';

/**
 * The questions a call carries, read defensively: the live pause sends them
 * beside the call, an answered call keeps them as its arguments.
 *
 * Args:
 *   value: The `questions` value.
 *
 * Returns:
 *   The questions, or an empty list when there are none to draw.
 */
export function readQuestions(value: unknown): Question[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((raw, index): Question[] => {
    if (!raw || typeof raw !== 'object') return [];
    const item = raw as Record<string, unknown>;
    const text = typeof item.text === 'string' ? item.text.trim() : '';
    if (!text) return [];
    const options = Array.isArray(item.options)
      ? item.options.flatMap((option, at) => {
          const label =
            typeof option === 'string'
              ? option
              : option && typeof option === 'object'
                ? (option as Record<string, unknown>).label
                : null;
          if (typeof label !== 'string' || !label.trim()) return [];
          const id =
            option && typeof option === 'object'
              ? (option as Record<string, unknown>).id
              : null;
          return [{ id: typeof id === 'string' ? id : String(at), label }];
        })
      : [];
    return [
      {
        id: typeof item.id === 'string' ? item.id : `q${index + 1}`,
        text,
        note: typeof item.note === 'string' && item.note ? item.note : null,
        multi: options.length > 0 && item.multi === true,
        options,
        placeholder:
          typeof item.placeholder === 'string' ? item.placeholder : null,
      },
    ];
  });
}

/** The questions an `ask_user` call asked (the normalized ones first). */
export function questionsOf(call: ToolCallsType): Question[] {
  const live = readQuestions(call.questions);
  return live.length ? live : readQuestions(call.arguments?.questions);
}

/** The line the model wrote above its questions, if any. */
export function questionMessageOf(call: ToolCallsType): string | null {
  const message = call.message ?? call.arguments?.message;
  return typeof message === 'string' && message.trim() ? message : null;
}

/**
 * How an `ask_user` call shows in the answer column, or null when it is an
 * ordinary step: questions that were never asked (invalid, a second round),
 * or ones the server already wrote into the answer as text.
 *
 * Args:
 *   call: A tool call of the turn.
 *
 * Returns:
 *   The state of its question block, or null.
 */
export function questionState(call: ToolCallsType): QuestionState | null {
  if (call.tool_name !== ASK_USER && call.action_name !== ASK_USER) return null;
  if (isHiddenCall(call) || questionsOf(call).length === 0) return null;
  switch (call.status) {
    case 'awaiting_answer':
      return 'awaiting';
    case 'skipped':
      return 'skipped';
    case 'denied':
      return call.not_run ? 'not_run' : null;
    case 'success':
    case 'completed':
    case 'pending':
    case undefined: {
      // Shown as answer text to a caller without question cards: the
      // questions are in the answer already, so it stays a step row.
      return call.shown_as === 'text' ? null : 'answered';
    }
    default:
      return null;
  }
}

/**
 * Whether the call is the server refusing an `ask_user` round (a second
 * round, invalid questions, or asked beside other tools): internal to the
 * model, so the chat shows it nowhere.
 */
export const isHiddenCall = (call: ToolCallsType): boolean =>
  (call.tool_name === ASK_USER || call.action_name === ASK_USER) &&
  call.error_type === 'questions_not_asked';

/** Whether the call draws as a question block rather than a step row. */
export const isQuestionCall = (call: ToolCallsType): boolean =>
  questionState(call) !== null;

/** The call's result as text (an answer is saved as a plain string). */
export function resultText(call: ToolCallsType): string | null {
  const result: unknown = call.result;
  return typeof result === 'string' ? result : null;
}

/**
 * Each question's answer, read back from the answer text the client sent
 * (`composeAnswers`: a line per answered question, "<question> → <answer>").
 * A message typed in the composer instead has no such lines: with one
 * question it is that question's answer, with more it is returned whole.
 *
 * Args:
 *   questions: The questions as asked.
 *   result: The call's result, the answer text.
 *
 * Returns:
 *   Answers by question id, and the typed reply none of them took.
 */
export function readAnswers(
  questions: Question[],
  result: string | null,
): { answers: Record<string, string>; reply: string | null } {
  const answers: Record<string, string> = {};
  const text = result?.trim() ?? '';
  if (!text) return { answers, reply: null };
  const lines = text.split('\n');
  for (const question of questions) {
    const prefix = `${question.text} → `;
    const line = lines.find((candidate) => candidate.startsWith(prefix));
    if (line) answers[question.id] = line.slice(prefix.length).trim();
  }
  if (Object.keys(answers).length > 0) return { answers, reply: null };
  if (questions.length === 1)
    return { answers: { [questions[0].id]: text }, reply: null };
  return { answers, reply: text };
}

/**
 * The call the latest turn is paused on for an answer, which a message typed
 * in the composer answers instead of starting a new turn.
 *
 * Args:
 *   queries: The conversation's turns.
 *
 * Returns:
 *   The waiting `ask_user` call, or null.
 */
export function pendingQuestionCall(queries: Query[]): ToolCallsType | null {
  const last = queries[queries.length - 1];
  return (
    last?.tool_calls?.find((call) => questionState(call) === 'awaiting') ?? null
  );
}

/**
 * The call as recorded once the user answered or skipped it, so the cards
 * fold at once instead of waiting for the resumed stream to say so.
 *
 * Args:
 *   call: The waiting call.
 *   action: What the user sent.
 *
 * Returns:
 *   The fields to merge into the call.
 */
export function answeredCall(
  call: ToolCallsType,
  action: QuestionAction,
): Partial<ToolCallsType> & { call_id: string } {
  return {
    call_id: call.call_id,
    arguments: {
      message: questionMessageOf(call),
      questions: questionsOf(call),
    },
    ...('answer' in action
      ? {
          status: 'success',
          // Saved as a plain string; `result` is typed for object results.
          result: action.answer as unknown as ToolCallsType['result'],
        }
      : { status: 'skipped' }),
  };
}
