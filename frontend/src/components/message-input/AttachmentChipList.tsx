import { Paperclip, TriangleAlert, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { Attachment } from '../../upload/uploadSlice';
import { IconButton } from '../ui/icon-button';
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

  // A tooltip is the one place a touch user can never look, and this list is
  // where a phone picker's unsupported file lands. Show the reason inline,
  // as soon as it is known, rather than only once a send is attempted.
  const failures = attachments.filter(
    (attachment) => attachment.status === 'failed' && attachment.errorMessage,
  );
  // Not a failure: the file is kept and still sends. It only warns that the
  // model picked right now would receive nothing it can read.
  const unreadable = modelName
    ? attachments.filter((attachment) => unreadableIds?.has(attachment.id))
    : [];

  return (
    <>
      <div className="flex flex-wrap gap-1.5 px-2 py-2 sm:gap-2 sm:px-3">
        {attachments.map((attachment) => {
          return (
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
              title={
                attachment.status === 'failed' && attachment.errorMessage
                  ? `${attachment.fileName}: ${attachment.errorMessage}`
                  : attachment.fileName
              }
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

              <span className="max-w-[120px] truncate font-medium sm:max-w-[150px]">
                {attachment.fileName}
              </span>

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
        })}
      </div>

      {failures.length > 0 && (
        <div
          className="text-destructive flex flex-col gap-0.5 px-2 pb-1 text-xs sm:px-3"
          role="alert"
        >
          {failures.map((attachment) => (
            <span key={attachment.id}>
              {attachment.fileName}: {attachment.errorMessage}
            </span>
          ))}
        </div>
      )}

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
