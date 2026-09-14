import type { Attachment } from '../../upload/uploadSlice';

/**
 * Whether the selected model has no way to read a completed attachment.
 *
 * A file with extracted text reaches any model as text. A file without any
 * (an image, or a scanned PDF stored with `extraction_status: 'no_text'`)
 * only reaches a model that takes that format natively; a PDF also reaches a
 * model that takes images, which is sent its pages as images. When the model
 * or the file type is unknown, stay quiet rather than warn on a guess.
 */
export function cannotReadAttachment(
  attachment: Attachment,
  supportedTypes: string[] | undefined,
): boolean {
  if (attachment.status !== 'completed') return false;
  const mime = attachment.mimeType;
  if (!mime || !supportedTypes) return false;

  const isPdf = mime === 'application/pdf';
  if (!isPdf && !mime.startsWith('image/')) return false;

  const hasText =
    attachment.extractionStatus !== 'no_text' &&
    (attachment.token_count ?? 0) > 0;
  if (hasText) return false;

  if (supportedTypes.includes(mime)) return false;
  if (isPdf && supportedTypes.some((type) => type.startsWith('image/'))) {
    return false;
  }
  return true;
}
