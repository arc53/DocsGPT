import { Undo2 } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  DescriptionItem,
  DescriptionList,
} from '@/components/ui/description-list';

/** One "why" row: the field's label, what it now holds, and why. */
export type ProposalReasonRow = {
  key: string;
  label: string;
  summary: string;
  detail?: string | null;
};

/**
 * What a draft did, as the panel shows it under the model's message: a row
 * per changed field with its reason, the model's notes, what the server left
 * out, and Undo all. Recipes map their proposal into these props.
 *
 * Args:
 *   message: The draft's short summary.
 *   rows: A reason per changed field.
 *   notes: Things the user should know ("No ticketing tool is connected…").
 *   dropped: Lines naming what was left out and why.
 *   onUndoAll: Undoes every drafted field; omit when nothing can be undone.
 *   footer: Extra actions after Undo all.
 */
export function ProposalSummary({
  message,
  rows,
  notes = [],
  dropped = [],
  onUndoAll,
  footer,
}: {
  message?: string;
  rows: ProposalReasonRow[];
  notes?: string[];
  dropped?: string[];
  onUndoAll?: () => void;
  footer?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3" data-slot="proposal-summary">
      {message && (
        <p className="text-sm wrap-break-word whitespace-pre-wrap">{message}</p>
      )}
      {rows.length > 0 && (
        <Card variant="subtle" padding="sm">
          <DescriptionList>
            {rows.map((row) => (
              <DescriptionItem key={row.key} label={row.label}>
                <span className="wrap-break-word">{row.summary}</span>
                {row.detail && (
                  <span className="text-muted-foreground block text-xs wrap-break-word">
                    {row.detail}
                  </span>
                )}
              </DescriptionItem>
            ))}
          </DescriptionList>
        </Card>
      )}
      {notes.length > 0 && (
        <Alert variant="info" role="note">
          <AlertDescription>
            <ul className="flex flex-col gap-1">
              {notes.map((note, index) => (
                <li key={index}>{note}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
      {dropped.length > 0 && (
        <Alert variant="warning" role="status">
          <AlertDescription>
            <p>{t('drafter.droppedTitle')}</p>
            <ul className="flex flex-col gap-1">
              {dropped.map((line, index) => (
                <li key={index}>{line}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
      {(onUndoAll || footer) && (
        <div className="flex flex-wrap gap-2">
          {onUndoAll && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              shape="pill"
              onClick={onUndoAll}
            >
              <Undo2 />
              {t('drafter.undoAll')}
            </Button>
          )}
          {footer}
        </div>
      )}
    </div>
  );
}
