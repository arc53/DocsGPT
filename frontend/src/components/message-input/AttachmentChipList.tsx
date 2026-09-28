import { Paperclip, TriangleAlert, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { Attachment } from '../../upload/uploadSlice';
import { IconButton } from '../ui/icon-button';
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip';
import { cn } from '@/lib/utils';

type AttachmentChipListProps = {
  attachments: Attachment[];
  draggingId: string | null;
  onRemove: (id: string) => void;
  onDragStart: (e: React.DragEvent, id: string) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDropOn: (e: React.DragEvent, targetId: string) => void;
  /** Completed attachments the selected model has no way to read. */
  unreadableIds?: Set<string>;
  /** Display name of the selected model, for the unreadable-file warning. */
  modelName?: string;
};

export default function AttachmentChipList({
  attachments,
  draggingId,
  onRemove,
  onDragStart,
  onDragOver,
  onDropOn,
  unreadableIds,
  modelName,
}: AttachmentChipListProps) {
  const { t } = useTranslation();

  // Not a failure: the file is kept and still sends. It only warns that the
  // model picked right now would receive nothing it can read.
  const unreadable = modelName
    ? attachments.filter((attachment) => unreadableIds?.has(attachment.id))
    : [];

  return (
    <>
      <div className="flex flex-wrap gap-1.5 px-2 py-2 sm:gap-2 sm:px-3">
        {attachments.map((attachment) => {
          const failed = attachment.status === 'failed';
          // A failed file never blocks the send (it is dropped then), so its
          // reason stays out of the way: the chip's warning icon marks it, and
          // the reason is a hover tooltip plus screen-reader text.
          const failureReason = failed
            ? (attachment.errorMessage ?? t('conversation.attachments.failed'))
            : null;
          const chip = (
            <div
              key={attachment.id}
              draggable={true}
              onDragStart={(e) => onDragStart(e, attachment.id)}
              onDragOver={onDragOver}
              onDrop={(e) => onDropOn(e, attachment.id)}
              // opacity-60 while dragging never applied (opacity-70 / -100
              // come later in the stylesheet), so only the ring shows the drag.
              className={cn(
                'group bg-muted text-foreground relative flex items-center rounded-xl px-2 py-1 text-xs sm:px-3 sm:py-1.5 sm:text-sm',
                attachment.status !== 'completed'
                  ? 'opacity-70'
                  : 'opacity-100',
                draggingId === attachment.id && 'ring-primary/30 ring-2',
              )}
            >
              <div className="bg-primary mr-2 flex size-8 items-center justify-center rounded-md p-1">
                {attachment.status === 'completed' && (
                  <Paperclip
                    aria-label={t('conversation.attachments.attached')}
                    className="text-primary-foreground size-3.75"
                  />
                )}

                {attachment.status === 'failed' && (
                  <TriangleAlert
                    aria-label={t('conversation.attachments.failed')}
                    className="text-primary-foreground size-4"
                  />
                )}

                {(attachment.status === 'uploading' ||
                  attachment.status === 'processing') && (
                  <div className="flex size-3.75 items-center justify-center">
                    <svg className="size-3.75" viewBox="0 0 24 24">
                      <circle
                        className="opacity-0"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="transparent"
                        strokeWidth="4"
                        fill="none"
                      />
                      <circle
                        className="text-primary-foreground"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        strokeWidth="4"
                        fill="none"
                        strokeDasharray="62.83"
                        strokeDashoffset={
                          62.83 * (1 - attachment.progress / 100)
                        }
                        transform="rotate(-90 12 12)"
                      />
                    </svg>
                  </div>
                )}
              </div>

              <span
                className="max-w-[120px] truncate font-medium sm:max-w-[150px]"
                title={failed ? undefined : attachment.fileName}
              >
                {attachment.fileName}
              </span>
              {failureReason && (
                <span className="sr-only">{failureReason}</span>
              )}

              <IconButton
                label={t('conversation.attachments.remove')}
                variant="ghost"
                size="icon-xs"
                shape="pill"
                className="ml-1.5"
                onClick={() => {
                  onRemove(attachment.id);
                }}
              >
                <X aria-hidden="true" className="size-4" />
              </IconButton>
            </div>
          );
          if (!failureReason) return chip;
          return (
            <Tooltip key={attachment.id}>
              <TooltipTrigger asChild>{chip}</TooltipTrigger>
              <TooltipContent>{failureReason}</TooltipContent>
            </Tooltip>
          );
        })}
      </div>

      {unreadable.length > 0 && (
        <div
          className="text-warning flex flex-col gap-0.5 px-2 pb-1 text-xs sm:px-3"
          role="status"
        >
          {unreadable.map((attachment) => (
            <span key={attachment.id}>
              {t('conversation.attachments.unreadableByModel', {
                name: attachment.fileName,
                model: modelName,
              })}
            </span>
          ))}
        </div>
      )}
    </>
  );
}
