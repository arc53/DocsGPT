import type { Attachment } from '../../upload/uploadSlice';
import { cannotReadAttachment } from './attachmentReadability';

const att = (over: Partial<Attachment> = {}): Attachment => ({
  id: 'a1',
  fileName: 'scan.pdf',
  progress: 100,
  status: 'completed',
  taskId: 't1',
  ...over,
});

const PDF_AND_IMAGES = [
  'application/pdf',
  'image/png',
  'image/jpeg',
  'image/webp',
];
const IMAGES_ONLY = ['image/png', 'image/jpeg', 'image/webp'];
const TEXT_ONLY: string[] = [];

const scannedPdf = att({
  mimeType: 'application/pdf',
  extractionStatus: 'no_text',
  token_count: 0,
});
const photo = att({
  fileName: 'photo.webp',
  mimeType: 'image/webp',
  extractionStatus: 'ok',
  token_count: 0,
});

describe('cannotReadAttachment', () => {
  it('flags a scanned PDF on a text-only model', () => {
    expect(cannotReadAttachment(scannedPdf, TEXT_ONLY)).toBe(true);
  });

  it('lets a model that reads PDFs natively take a scanned PDF', () => {
    expect(cannotReadAttachment(scannedPdf, PDF_AND_IMAGES)).toBe(false);
  });

  it('lets an image-only model take a scanned PDF as page images', () => {
    expect(cannotReadAttachment(scannedPdf, IMAGES_ONLY)).toBe(false);
  });

  it('flags an image on a text-only model', () => {
    expect(cannotReadAttachment(photo, TEXT_ONLY)).toBe(true);
  });

  it('lets a vision model take the image', () => {
    expect(cannotReadAttachment(photo, IMAGES_ONLY)).toBe(false);
  });

  it('does not flag a PDF whose text was extracted', () => {
    const textPdf = att({
      mimeType: 'application/pdf',
      extractionStatus: 'ok',
      token_count: 1200,
    });
    expect(cannotReadAttachment(textPdf, TEXT_ONLY)).toBe(false);
  });

  it('stays quiet when the model or the file type is unknown', () => {
    expect(cannotReadAttachment(scannedPdf, undefined)).toBe(false);
    expect(
      cannotReadAttachment(att({ extractionStatus: 'no_text' }), TEXT_ONLY),
    ).toBe(false);
  });

  it('ignores attachments that have not finished processing', () => {
    expect(
      cannotReadAttachment({ ...scannedPdf, status: 'processing' }, TEXT_ONLY),
    ).toBe(false);
  });
});
