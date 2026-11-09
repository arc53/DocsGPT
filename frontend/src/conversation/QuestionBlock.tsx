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
 * answered" for questions the chat moved past).
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
  // default), or nothing while waiting, for a reply typed for them all, or
  // while the answer is still on its way.
  const emptyLabel =
    state === 'skipped'
      ? t('questions.skipped')
      : state === 'awaiting' ||
          reply ||
          (state === 'answered' && result === null)
        ? null
        : undefined;

  return (
    // Stretched to the column, as the approval bars are (see PATTERNS.md ›
    // Chat answer column).
    <div className="w-full min-w-0" data-slot="question-block">
      <div
        className={cn(
          'my-2 mr-5 ml-6 flex flex-col',
          active
            ? 'animate-in fade-in gap-3 duration-160 ease-out motion-reduce:animate-none'
            : 'gap-2',
        )}
      >
        {message && (
          <p className="leading-normal wrap-break-word whitespace-pre-wrap">
            {message}
          </p>
        )}
        <QuestionCards
          questions={questions}
          active={active}
          onAnswer={(answer) => onAction?.(call.call_id, { answer })}
          onSkip={() => onAction?.(call.call_id, { skipped: true })}
          skipLabel={t('questions.justAnswer')}
          answers={state === 'awaiting' ? undefined : answers}
          emptyLabel={emptyLabel}
          className={active ? undefined : 'gap-2'}
        />
        {reply && (
          <Card variant="subtle" padding="sm" className="gap-1">
            <p className="text-sm font-medium">{t('questions.yourAnswer')}</p>
            <p className="text-sm wrap-break-word whitespace-pre-wrap">
              {reply}
            </p>
          </Card>
        )}
      </div>
    </div>
  );
}
