import { useTranslation } from 'react-i18next';

import { QuestionCards } from '../components/QuestionCards';
import { Card } from '../components/ui/card';
import {
  type QuestionAction,
  questionMessageOf,
  questionsOf,
  questionState,
  readAnswers,
  resultText,
} from './questionCall';
import { ToolCallsType } from './types';
import { cn } from '@/lib/utils';

/**
 * An `ask_user` call in the answer column, on its `mr-5 ml-6` text column:
 * the model's lead-in line as answer text, then the questions. Waiting, they
 * are cards to answer with Send answers or pass with Just answer; afterwards
 * they fold into the record of what was answered (or "Skipped", or "Not
 * answered" for questions the chat moved past). A reply typed in the
 * composer folds them into one card, "Answered in your message", and shows
 * as the user's own bubble under it.
 *
 * Args:
 *   call: The `ask_user` call.
 *   onAction: Resumes the turn with the answers or the skip; without it the
 *     cards can't be answered here.
 *   disabled: The turn is busy (a resume is streaming).
 */
export default function QuestionBlock({
  call,
  onAction,
  disabled = false,
}: {
  call: ToolCallsType;
  onAction?: (callId: string, action: QuestionAction) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const state = questionState(call);
  const questions = questionsOf(call);
  const message = questionMessageOf(call);
  if (!state) return null;
  const active = state === 'awaiting' && Boolean(onAction) && !disabled;
  const result = resultText(call);
  const { answers, reply } =
    state === 'answered'
      ? readAnswers(questions, result)
      : { answers: {}, reply: null };
  // Under a question with no answer: "Skipped", "Not answered" (the
  // default), or nothing while waiting or while the answer is still on its
  // way.
  const emptyLabel =
    state === 'skipped'
      ? t('questions.skipped')
      : state === 'awaiting' || (state === 'answered' && result === null)
        ? null
        : undefined;

  return (
    // Stretched to the column, as the approval bars are (see PATTERNS.md ›
    // Chat answer column).
    <div className="w-full min-w-0" data-slot="question-block">
      <div
        className={cn(
          'my-2 mr-5 ml-6 flex flex-col gap-4',
          active &&
            'animate-in fade-in duration-160 ease-out motion-reduce:animate-none',
        )}
      >
        <div className={cn('flex flex-col', active ? 'gap-3' : 'gap-2')}>
          {message && (
            <p className="leading-normal wrap-break-word whitespace-pre-wrap">
              {message}
            </p>
          )}
          {reply ? (
            <Card
              variant="subtle"
              padding="sm"
              className="gap-2"
              data-slot="question-record"
            >
              {questions.map((question, index) => (
                <p
                  key={question.id}
                  className="text-sm font-medium wrap-break-word"
                >
                  {questions.length > 1 ? `${index + 1}. ` : ''}
                  {question.text}
                </p>
              ))}
              <p className="text-muted-foreground text-sm">
                {t('questions.answeredInMessage')}
              </p>
            </Card>
          ) : (
            <QuestionCards
              questions={questions}
              active={active}
              onAnswer={(answer) => onAction?.(call.call_id, { answer })}
              onSkip={() => onAction?.(call.call_id, { skipped: true })}
              skipLabel={t('questions.justAnswer')}
              answers={state === 'awaiting' ? undefined : answers}
              emptyLabel={emptyLabel}
              className={active ? undefined : 'gap-2'}
              // A refused Send answers brings the cards back waiting: with
              // what was picked. The questions are in the key, as a provider
              // may reuse a call id ("call_0") across turns.
              memoryKey={`${call.call_id}\n${JSON.stringify(
                questions.map((question) => [question.id, question.text]),
              )}`}
            />
          )}
        </div>
        {/* The reply is the user's message, so it is their bubble (the
            drafter's recipe, DraftPanel), its right edge on the column's
            mr-5 gutter like the question bubble's. */}
        {reply && (
          <div
            className="bg-secondary text-foreground ml-8 self-end rounded-3xl px-5 py-4 text-sm leading-normal wrap-anywhere whitespace-pre-wrap sm:text-base"
            data-slot="question-reply"
          >
            {reply}
          </div>
        )}
      </div>
    </div>
  );
}
