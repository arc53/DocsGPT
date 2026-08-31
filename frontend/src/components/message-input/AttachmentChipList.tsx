import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import AlertIcon from '../../assets/alert.svg';
import DocumentationDark from '../../assets/documentation-dark.svg';
import type { Attachment } from '../../upload/uploadSlice';
import { Button } from '../ui/button';

type AttachmentChipListProps = {
  attachments: Attachment[];
  draggingId: string | null;
  onRemove: (id: string) => void;
  onDragStart: (e: React.DragEvent, id: string) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDropOn: (e: React.DragEvent, targetId: string) => void;
};

export function isImageAttachment(attachment: {
  mimeType?: string;
  fileName?: string;
  previewUrl?: string;
}): boolean {
  if (attachment.previewUrl) return true;
  if (
    attachment.mimeType &&
    attachment.mimeType.toLowerCase().startsWith('image/')
  ) {
    return true;
  }
  if (attachment.fileName) {
    return /\.(png|jpe?g|gif|webp|svg|bmp|avif|ico)$/i.test(
      attachment.fileName,
    );
  }
  return false;
}

export default function AttachmentChipList({
  attachments,
  draggingId,
  onRemove,
  onDragStart,
  onDragOver,
  onDropOn,
}: AttachmentChipListProps) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-wrap gap-1.5 px-2 py-2 sm:gap-2 sm:px-3">
      {attachments.map((attachment) => {
        const isImage = isImageAttachment(attachment);
        const hasPreview = isImage && Boolean(attachment.previewUrl);

        return (
          <div
            key={attachment.id}
            draggable={true}
            onDragStart={(e) => onDragStart(e, attachment.id)}
            onDragOver={onDragOver}
            onDrop={(e) => onDropOn(e, attachment.id)}
            className={`group dark:text-foreground bg-muted text-muted-foreground dark:bg-accent relative flex items-center rounded-xl px-2 py-1 text-xs sm:px-3 sm:py-1.5 sm:text-sm ${
              attachment.status !== 'completed' ? 'opacity-70' : 'opacity-100'
            } ${
              draggingId === attachment.id
                ? 'ring-dashed opacity-60 ring-2 ring-purple-200'
                : ''
            }`}
            title={attachment.fileName}
          >
            {hasPreview && attachment.status === 'completed' ? (
              <div className="bg-muted mr-2 flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-md">
                <img
                  src={attachment.previewUrl}
                  alt={attachment.fileName}
                  className="h-full w-full object-cover"
                />
              </div>
            ) : hasPreview &&
              (attachment.status === 'uploading' ||
                attachment.status === 'processing') ? (
              <div className="bg-muted relative mr-2 flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-md">
                <img
                  src={attachment.previewUrl}
                  alt={attachment.fileName}
                  className="h-full w-full object-cover opacity-50"
                />
                <div className="absolute inset-0 flex items-center justify-center">
                  <svg className="h-[18px] w-[18px]" viewBox="0 0 24 24">
                    <circle
                      className="opacity-20"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                      fill="none"
                    />
                    <circle
                      className="text-primary"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                      fill="none"
                      strokeDasharray="62.83"
                      strokeDashoffset={62.83 * (1 - attachment.progress / 100)}
                      transform="rotate(-90 12 12)"
                    />
                  </svg>
                </div>
              </div>
            ) : (
              <div className="bg-primary mr-2 flex h-8 w-8 shrink-0 items-center justify-center rounded-md p-1">
                {attachment.status === 'completed' && (
                  <img
                    src={DocumentationDark}
                    alt="Attachment"
                    className="h-[15px] w-[15px] object-fill"
                  />
                )}

                {attachment.status === 'failed' && (
                  <img
                    src={AlertIcon}
                    alt="Failed"
                    className="h-[15px] w-[15px] object-fill"
                  />
                )}

                {(attachment.status === 'uploading' ||
                  attachment.status === 'processing') && (
                  <div className="flex h-[15px] w-[15px] items-center justify-center">
                    <svg className="h-[15px] w-[15px]" viewBox="0 0 24 24">
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
                        className="text-[#ECECF1]"
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
            )}

            <span className="max-w-[120px] truncate font-medium sm:max-w-[150px]">
              {attachment.fileName}
            </span>

            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="ml-1.5 h-auto w-auto rounded-full p-1"
              onClick={() => {
                onRemove(attachment.id);
              }}
              aria-label={t('conversation.attachments.remove')}
            >
              <X
                aria-label={t('conversation.attachments.remove')}
                className="h-2.5 w-2.5"
              />
            </Button>
          </div>
        );
      })}
    </div>
  );
}
