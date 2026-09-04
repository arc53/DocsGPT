import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useAttachmentPreviewUrl } from './useAttachmentPreview';
import type { AttachmentPreviewSource } from './useAttachmentPreview';

const { mockGetPreview } = vi.hoisted(() => ({ mockGetPreview: vi.fn() }));
vi.mock('../api/services/userService', () => ({
  default: { getAttachmentPreview: mockGetPreview },
}));

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function Host({
  attachment,
  token,
  shareId,
}: {
  attachment: {
    id?: string;
    fileName?: string;
    mimeType?: string;
    previewUrl?: string;
  };
  token: string | null;
  shareId?: string | null;
}) {
  const url = useAttachmentPreviewUrl(attachment, token, shareId);
  return <span>{url ?? 'none'}</span>;
}

describe('useAttachmentPreviewUrl', () => {
  let container: HTMLDivElement;
  let root: Root;
  const realCreateObjectURL = URL.createObjectURL;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    mockGetPreview.mockReset();
    URL.createObjectURL = (() => 'blob:fetched') as typeof URL.createObjectURL;
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    URL.createObjectURL = realCreateObjectURL;
  });

  const render = async (
    attachment: AttachmentPreviewSource,
    token: string | null = 'tok',
    shareId?: string | null,
  ) => {
    await act(async () => {
      root.render(
        <Host attachment={attachment} token={token} shareId={shareId} />,
      );
    });
  };

  const okImage = () =>
    mockGetPreview.mockResolvedValue(
      new Response(new Blob(['imgbytes'], { type: 'image/png' })),
    );

  it('reuses a live snapshot previewUrl without fetching', async () => {
    await render({
      id: 'a1',
      fileName: 'photo.png',
      mimeType: 'image/png',
      previewUrl: 'blob:snap',
    });
    expect(container.textContent).toBe('blob:snap');
    expect(mockGetPreview).not.toHaveBeenCalled();
  });

  it('fetches image bytes by ID when no snapshot URL exists', async () => {
    okImage();
    await render({ id: 'att-1', fileName: 'photo.png', mimeType: 'image/png' });
    expect(container.textContent).toBe('blob:fetched');
    expect(mockGetPreview).toHaveBeenCalledWith('att-1', 'tok', undefined);
  });

  it('fetches for image suffixes when the mime type is absent', async () => {
    okImage();
    await render({ id: 'att-2', fileName: 'scan.webp' });
    expect(container.textContent).toBe('blob:fetched');
  });

  it('never fetches for non-image attachments', async () => {
    await render({
      id: 'att-3',
      fileName: 'doc.pdf',
      mimeType: 'application/pdf',
    });
    expect(container.textContent).toBe('none');
    expect(mockGetPreview).not.toHaveBeenCalled();
  });

  it('falls back to null when the fetch fails', async () => {
    mockGetPreview.mockResolvedValue(new Response(null, { status: 404 }));
    await render({ id: 'att-4', fileName: 'photo.png', mimeType: 'image/png' });
    expect(container.textContent).toBe('none');
  });

  it('passes the share identifier through for share-scoped fetches', async () => {
    okImage();
    await render(
      { id: 'att-5', fileName: 'photo.png', mimeType: 'image/png' },
      null,
      'share-9',
    );
    expect(mockGetPreview).toHaveBeenCalledWith('att-5', null, 'share-9');
    expect(container.textContent).toBe('blob:fetched');
  });

  it('caches by attachment ID and does not refetch on remount', async () => {
    okImage();
    await render({ id: 'att-6', fileName: 'photo.png', mimeType: 'image/png' });
    expect(container.textContent).toBe('blob:fetched');
    await act(async () => root.unmount());
    container.remove();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await render({ id: 'att-6', fileName: 'photo.png', mimeType: 'image/png' });
    expect(container.textContent).toBe('blob:fetched');
    expect(mockGetPreview).toHaveBeenCalledTimes(1);
  });
});
