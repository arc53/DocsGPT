import { Paperclip } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Badge } from '../components/ui/badge';
import { planEntryFor, summarizePlan } from './attachmentPlan';
import type {
  AttachmentPlanEntry,
  AttachmentPlanStatus,
} from './conversationModels';

// Where a file went, as a status Badge: read in full is healthy, read in part
// is a partial state, searchable is informational, left out is neutral and a
// file the model cannot read is an error.
const STATUS_VARIANT: Record<
  AttachmentPlanStatus,
  'success' | 'warning' | 'info' | 'neutral' | 'destructive'
> = {
  inline: 'success',
  partial: 'warning',
  tool: 'info',
  omitted: 'neutral',
  unreadable: 'destructive',
};

/**
 * The files attached to a question, each marked with where it went: read in
 * full, read in part, searched as needed, or left out. Nothing asks the user
 * to act; a short line under the chips says how many were read in full when
 * not all of them were.
 */
export default function AttachmentChips({
  files,
  plan,
}: {
  files: { id: string; fileName: string }[];
  plan?: AttachmentPlanEntry[];
}) {
  const { t } = useTranslation();
  const summary = summarizePlan(plan, files);
  const summaryParts = summary
    ? [
        t('conversation.attachments.plan.summary', {
          inFull: summary.inFull,
          total: summary.total,
        }),
        summary.searchable > 0
          ? t('conversation.attachments.plan.summarySearchable', {
              count: summary.searchable,
            })
          : null,
        summary.notIncluded > 0
          ? t('conversation.attachments.plan.summaryNotIncluded', {
              count: summary.notIncluded,
            })
          : null,
      ].filter(Boolean)
    : [];

  return (
    <div className="mr-5 mb-4 flex flex-col items-end gap-1.5">
      <div className="flex flex-wrap justify-end gap-2">
        {files.map((file, index) => {
          const entry = planEntryFor(plan, file);
          return (
            <div
              key={index}
              data-plan-status={entry?.status}
              className="bg-muted text-foreground flex items-center gap-2 rounded-xl p-2 text-sm"
            >
              <div className="bg-primary items-center justify-center rounded-lg p-1.5">
                <Paperclip
                  aria-label={t('conversation.attachments.attachment')}
                  className="text-primary-foreground size-3.75"
                />
              </div>
              <div className="flex min-w-0 flex-col items-start gap-1">
                <span
                  title={file.fileName}
                  className="max-w-37.5 truncate font-normal"
                >
                  {file.fileName}
                </span>
                {entry && (
                  <Badge variant={STATUS_VARIANT[entry.status]}>
                    {t(`conversation.attachments.plan.${entry.status}`)}
                  </Badge>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {summaryParts.length > 0 && (
        <p className="text-muted-foreground text-xs">
          {summaryParts.join(' · ')}
        </p>
      )}
    </div>
  );
}
