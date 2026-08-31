import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';

import type { Attachment } from '../../upload/uploadSlice';
import AttachmentChipList, { isImageAttachment } from './AttachmentChipList';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('isImageAttachment', () => {
  it('identifies images from previewUrl', () => {
    expect(isImageAttachment({ previewUrl: 'blob:http://localhost/123' })).toBe(
      true,
    );
  });

  it('identifies images from mimeType', () => {
    expect(isImageAttachment({ mimeType: 'image/png' })).toBe(true);
    expect(isImageAttachment({ mimeType: 'image/jpeg' })).toBe(true);
    expect(isImageAttachment({ mimeType: 'application/pdf' })).toBe(false);
  });

  it('identifies images from file extensions', () => {
    expect(isImageAttachment({ fileName: 'photo.jpg' })).toBe(true);
    expect(isImageAttachment({ fileName: 'screenshot.png' })).toBe(true);
    expect(isImageAttachment({ fileName: 'graphic.webp' })).toBe(true);
    expect(isImageAttachment({ fileName: 'doc.pdf' })).toBe(false);
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

  it('renders generic document icon for non-image attachments', async () => {
    const attachments: Attachment[] = [
      {
        id: '1',
        fileName: 'report.pdf',
        status: 'completed',
        progress: 100,
        taskId: 'task-1',
        mimeType: 'application/pdf',
      },
    ];

    await act(async () => {
      root.render(
        <AttachmentChipList
          attachments={attachments}
          draggingId={null}
          onRemove={vi.fn()}
          onDragStart={vi.fn()}
          onDragOver={vi.fn()}
          onDropOn={vi.fn()}
        />,
      );
    });

    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    expect(img?.getAttribute('alt')).toBe('Attachment');
    expect(container.textContent).toContain('report.pdf');
  });

  it('renders image thumbnail preview when previewUrl is present', async () => {
    const attachments: Attachment[] = [
      {
        id: '2',
        fileName: 'photo.png',
        status: 'completed',
        progress: 100,
        taskId: 'task-2',
        mimeType: 'image/png',
        previewUrl: 'blob:http://localhost/test-photo',
      },
    ];

    await act(async () => {
      root.render(
        <AttachmentChipList
          attachments={attachments}
          draggingId={null}
          onRemove={vi.fn()}
          onDragStart={vi.fn()}
          onDragOver={vi.fn()}
          onDropOn={vi.fn()}
        />,
      );
    });

    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    expect(img?.getAttribute('src')).toBe('blob:http://localhost/test-photo');
    expect(img?.getAttribute('alt')).toBe('photo.png');
    expect(container.textContent).toContain('photo.png');
  });

  it('calls onRemove when remove button is clicked', async () => {
    const onRemove = vi.fn();
    const attachments: Attachment[] = [
      {
        id: '3',
        fileName: 'photo.png',
        status: 'completed',
        progress: 100,
        taskId: 'task-3',
        mimeType: 'image/png',
        previewUrl: 'blob:http://localhost/test-photo',
      },
    ];

    await act(async () => {
      root.render(
        <AttachmentChipList
          attachments={attachments}
          draggingId={null}
          onRemove={onRemove}
          onDragStart={vi.fn()}
          onDragOver={vi.fn()}
          onDropOn={vi.fn()}
        />,
      );
    });

    const button = container.querySelector('button');
    expect(button).not.toBeNull();
    await act(async () => {
      button?.click();
    });

    expect(onRemove).toHaveBeenCalledWith('3');
  });
});
