import { Paperclip } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { planEntryFor, summarizePlan } from './attachmentPlan';
import type {
  AttachmentPlanEntry,
  AttachmentPlanStatus,
} from './conversationModels';

const STATUS_TONE: Record<AttachmentPlanStatus, string> = {
  inline: 'bg-emerald-500',
  partial: 'bg-amber-500',
  tool: 'bg-sky-500',
  omitted: 'bg-muted-foreground',
  unreadable: 'bg-destructive',
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
          const label = entry
            ? t(`conversation.attachments.plan.${entry.status}`)
            : null;
          return (
            <div
              key={index}
              title={label ? `${file.fileName} — ${label}` : file.fileName}
              data-plan-status={entry?.status}
              className="bg-muted text-foreground flex items-center rounded-xl p-2 text-sm"
            >
              <div className="bg-primary mr-2 items-center justify-center rounded-lg p-1.5">
                <Paperclip
                  aria-label={t('conversation.attachments.attachment')}
                  className="text-primary-foreground size-3.75"
                />
              </div>
              <div className="flex min-w-0 flex-col">
                <span className="max-w-37.5 truncate font-normal">
                  {file.fileName}
                </span>
                {entry && label && (
                  <span className="flex items-center gap-1 text-xs opacity-80">
                    <span
                      aria-hidden="true"
                      className={`inline-block size-1.5 rounded-full ${STATUS_TONE[entry.status]}`}
                    />
                    {label}
                  </span>
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
