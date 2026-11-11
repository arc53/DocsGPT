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
          const fields =
            option && typeof option === 'object'
              ? (option as Record<string, unknown>)
              : {};
          const { id, input } = fields;
          return [
            {
              id: typeof id === 'string' ? id : String(at),
              label,
              input: typeof input === 'string' && input.trim() ? input : null,
              exclusive: fields.exclusive === true,
            },
          ];
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
 * How an `ask_user` call shows in the answer column, or null when it draws
 * no question block: questions that were never asked (invalid, a second
 * round).
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
    case undefined:
      return 'answered';
    default:
      return null;
  }
}

/**
 * Whether the chat shows an `ask_user` call nowhere: the server refusing the
 * round (a second round, invalid questions, or asked beside other tools),
 * which is internal to the model.
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
 * (`composeAnswers`: "<question> → <answer>" per answered question, in order,
 * joined by line breaks). A question's text and an answer can hold line
 * breaks of their own, so each answer runs up to the next answered
 * question's "<question> → ", not to the end of its line. A message typed in
 * the composer instead has no such parts, and is returned whole as the reply,
 * even for a lone question: it shows as the user's own message.
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
  const prefix = (question: Question) => `${question.text} → `;
  let rest = text;
  let left = questions;
  while (left.length > 0) {
    const at = left.findIndex((question) => rest.startsWith(prefix(question)));
    if (at === -1) break;
    const question = left[at];
    left = left.slice(at + 1);
    rest = rest.slice(prefix(question).length);
    // The answer ends where a later answered question starts.
    const end = Math.min(
      rest.length,
      ...left
        .map((later) => rest.indexOf(`\n${prefix(later)}`))
        .filter((index) => index !== -1),
    );
    answers[question.id] = rest.slice(0, end).trim();
    rest = rest.slice(end + 1);
  }
  if (Object.keys(answers).length > 0) return { answers, reply: null };
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

/**
 * The latest turn holding the call `callId` (a provider may reuse a call id
 * across turns), and the call.
 *
 * Args:
 *   queries: The conversation's turns.
 *   callId: The call's id.
 *
 * Returns:
 *   The turn's index (-1 when none holds it) and the call, if found.
 */
export function findQuestionCall(
  queries: Query[],
  callId: string,
): { index: number; call: ToolCallsType | undefined } {
  const index = queries.findLastIndex((query) =>
    query.tool_calls?.some((call) => call.call_id === callId),
  );
  const call = queries[index]?.tool_calls?.find(
    (candidate) => candidate.call_id === callId,
  );
  return { index, call };
}

/**
 * Answer a paused question call and resume its turn, the chat's and the
 * agent preview's way alike. A refused try's error leaves the turn (this
 * answer is the retry), the cards fold into their record at once
 * (`answeredCall`), then the answer goes; when the server refused it,
 * nothing ran and it still waits, so the cards come back as they were for
 * another try. Without the call only the answer goes.
 *
 * Args:
 *   turn: The turn holding the call, and the call (`findQuestionCall`).
 *   action: The answers, or Just answer.
 *   updateQuery: Writes to the turn (the slice's `updateQuery`).
 *   updateToolCall: Writes the call (the slice's `updateToolCall`).
 *   send: Sends the answer; resolves true when the server refused it.
 */
export async function resumeQuestionCall({
  turn,
  call,
  action,
  updateQuery,
  updateToolCall,
  send,
}: {
  turn: Query | undefined;
  call: ToolCallsType | undefined;
  action: QuestionAction;
  updateQuery: (query: Partial<Query>) => void;
  updateToolCall: (call: Partial<ToolCallsType> & { call_id: string }) => void;
  send: () => Promise<boolean>;
}): Promise<void> {
  if (call) {
    if (turn?.error)
      updateQuery({
        error: undefined,
        errorCode: undefined,
        errorParams: undefined,
      });
    updateToolCall(answeredCall(call, action));
  }
  const refused = await send();
  // `result` is written even when the waiting call had none, so the merge
  // drops the answer the record put there.
  if (refused && call) updateToolCall({ ...call, result: call.result });
}
