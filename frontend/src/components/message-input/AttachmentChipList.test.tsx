import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Attachment } from '../../upload/uploadSlice';
import AttachmentChipList, { isImageAttachment } from './AttachmentChipList';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const att = (over: Partial<Attachment> = {}): Attachment => ({
  id: 'a1',
  fileName: 'report.pdf',
  progress: 100,
  status: 'completed',
  taskId: 't1',
  ...over,
});

describe('isImageAttachment', () => {
  it('treats a stored preview URL as an image', () => {
    expect(isImageAttachment({ previewUrl: 'blob:local/1' })).toBe(true);
  });

  it('classifies by mime type', () => {
    expect(isImageAttachment({ mimeType: 'image/png' })).toBe(true);
    expect(isImageAttachment({ mimeType: 'IMAGE/JPEG' })).toBe(true);
    expect(isImageAttachment({ mimeType: 'application/pdf' })).toBe(false);
  });

  it('falls back to the file-name suffix', () => {
    expect(isImageAttachment({ fileName: 'photo.jpg' })).toBe(true);
    expect(isImageAttachment({ fileName: 'scan.webp' })).toBe(true);
    expect(isImageAttachment({ fileName: 'doc.pdf' })).toBe(false);
  });

  it('rejects empty attachments', () => {
    expect(isImageAttachment({})).toBe(false);
  });
});

describe('AttachmentChipList', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    attachments: Attachment[],
    onRemove: (id: string) => void = () => {},
  ) => {
    await act(async () => {
      root.render(
        <AttachmentChipList
          attachments={attachments}
          draggingId={null}
          onRemove={onRemove}
          onDragStart={() => {}}
          onDragOver={() => {}}
          onDropOn={() => {}}
        />,
      );
    });
  };

  it('renders the document icon for a completed PDF', async () => {
    await render([att()]);
    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    expect(img?.getAttribute('alt')).toBe('Attachment');
    expect(container.textContent).toContain('report.pdf');
  });

  it('renders a thumbnail for a completed image', async () => {
    await render([
      att({
        id: 'img1',
        fileName: 'photo.png',
        mimeType: 'image/png',
        previewUrl: 'blob:test-photo',
      }),
    ]);
    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    expect(img?.getAttribute('src')).toBe('blob:test-photo');
    expect(img?.getAttribute('alt')).toBe('photo.png');
  });

  it('renders a thumbnail with a progress overlay while uploading', async () => {
    await render([
      att({
        id: 'img1',
        fileName: 'photo.png',
        status: 'uploading',
        progress: 40,
        mimeType: 'image/png',
        previewUrl: 'blob:test-photo',
      }),
    ]);
    const img = container.querySelector('img');
    expect(img?.getAttribute('src')).toBe('blob:test-photo');
    // The ring overlay, not the plain icon branch.
    expect(container.querySelector('svg')).not.toBeNull();
  });

  it('keeps the error icon for a failed attachment', async () => {
    await render([att({ status: 'failed', fileName: 'broken.pdf' })]);
    expect(container.querySelector('img')?.getAttribute('alt')).toBe('Failed');
  });

  it('falls back to the icon for an image without a preview URL', async () => {
    await render([att({ fileName: 'photo.png', mimeType: 'image/png' })]);
    const img = container.querySelector('img');
    expect(img?.getAttribute('alt')).toBe('Attachment');
    expect(img?.getAttribute('src')).not.toBe('blob:test-photo');
  });

  it('calls onRemove with the attachment id', async () => {
    const onRemove = vi.fn();
    await render(
      [
        att({
          id: 'img1',
          fileName: 'photo.png',
          mimeType: 'image/png',
          previewUrl: 'blob:test-photo',
        }),
      ],
      onRemove,
    );
    const button = container.querySelector('button');
    expect(button).not.toBeNull();
    await act(async () => {
      button?.click();
    });
    expect(onRemove).toHaveBeenCalledWith('img1');
  });
});
