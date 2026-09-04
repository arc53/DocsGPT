import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import AlertIcon from '../../assets/alert.svg';
import DocumentationDark from '../../assets/documentation-dark.svg';
import { isImageFileName } from '../../constants/fileUpload';
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

/**
 * Whether an attachment should render as an image thumbnail. A stored
 * ``previewUrl`` is decisive — it is only ever created for images — while
 * ``mimeType`` and the file-name suffix cover rows whose URL is gone
 * (or was never creatable).
 */
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
    return isImageFileName(attachment.fileName);
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

  // A tooltip is the one place a touch user can never look, and this list is
  // where a phone picker's unsupported file lands. Show the reason inline,
  // as soon as it is known, rather than only once a send is attempted.
  const failures = attachments.filter(
    (attachment) => attachment.status === 'failed' && attachment.errorMessage,
  );

  return (
    <>
      <div className="flex flex-wrap gap-1.5 px-2 py-2 sm:gap-2 sm:px-3">
        {attachments.map((attachment) => {
          // A thumbnail needs a live URL; without one an image renders
          // with the generic icon, exactly like a document.
          const previewUrl =
            isImageAttachment(attachment) && attachment.previewUrl
              ? attachment.previewUrl
              : undefined;
          const showProgress =
            attachment.status === 'uploading' ||
            attachment.status === 'processing';
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
              title={
                attachment.status === 'failed' && attachment.errorMessage
                  ? `${attachment.fileName}: ${attachment.errorMessage}`
                  : attachment.fileName
              }
            >
              {previewUrl && attachment.status === 'completed' ? (
                <div className="bg-muted mr-2 flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-md">
                  <img
                    src={previewUrl}
                    alt={attachment.fileName}
                    className="h-full w-full object-cover"
                  />
                </div>
              ) : previewUrl && showProgress ? (
                <div className="bg-muted relative mr-2 flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-md">
                  <img
                    src={previewUrl}
                    alt={attachment.fileName}
                    className="h-full w-full object-cover opacity-50"
                  />
                  <div className="absolute inset-0 flex items-center justify-center">
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
                </div>
              ) : (
                <div className="bg-primary mr-2 flex h-8 w-8 items-center justify-center rounded-md p-1">
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

                  {showProgress && (
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

      {failures.length > 0 && (
        <div
          className="flex flex-col gap-0.5 px-2 pb-1 text-xs text-[#B42318] sm:px-3"
          role="alert"
        >
          {failures.map((attachment) => (
            <span key={attachment.id}>
              {attachment.fileName}: {attachment.errorMessage}
            </span>
          ))}
        </div>
      )}
    </>
  );
}
