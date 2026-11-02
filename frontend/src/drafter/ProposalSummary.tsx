import { ListChecks } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

import { DrafterStepRow, FilledRow } from './DrafterStepRow';

/** One filled field: its label and what it now holds. */
export type ProposalReasonRow = {
  key: string;
  label: string;
  summary: string;
};

/**
 * What a draft did, as the panel shows it for the turn: the model's message
 * and notes as paragraphs, a "Filled N fields" step row that opens a line per
 * field, what the server left out, and the turn's actions (the step's Next)
 * last. Undo lives on each field's Drafted badge. Recipes map their proposal
 * into these props.
 *
 * Args:
 *   message: The draft's short summary.
 *   rows: A row per filled field.
 *   notes: Things the user should know ("No ticketing tool is connected…").
 *   dropped: Lines naming what was left out and why.
 *   actions: Buttons for the latest turn, such as the step's Next.
 */
export function ProposalSummary({
  message,
  rows,
  notes = [],
  dropped = [],
  actions,
}: {
  message?: string;
  rows: ProposalReasonRow[];
  notes?: string[];
  dropped?: string[];
  actions?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-2" data-slot="proposal-summary">
      {message && (
        <p className="text-sm wrap-break-word whitespace-pre-wrap">{message}</p>
      )}
      {notes.map((note, index) => (
        <p key={index} className="text-sm wrap-break-word whitespace-pre-wrap">
          {note}
        </p>
      ))}
      {rows.length > 0 && (
        <DrafterStepRow
          icon={ListChecks}
          label={t('drafter.filled', { count: rows.length })}
        >
          {rows.map((row) => (
            <FilledRow key={row.key} label={row.label} value={row.summary} />
          ))}
        </DrafterStepRow>
      )}
      {dropped.length > 0 && (
        <Alert variant="warning" role="status">
          <AlertTitle>{t('drafter.droppedTitle')}</AlertTitle>
          <AlertDescription>
            <ul className="flex flex-col gap-1">
              {dropped.map((line, index) => (
                <li key={index}>{line}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
      {actions && <div className="flex flex-wrap gap-2 pt-1">{actions}</div>}
    </div>
  );
}
