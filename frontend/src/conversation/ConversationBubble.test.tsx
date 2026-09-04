import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AttachmentPreviewImage } from './ConversationBubble';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('AttachmentPreviewImage', () => {
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

  const render = async (previewUrl: string, fileName: string) => {
    await act(async () => {
      root.render(
        <AttachmentPreviewImage previewUrl={previewUrl} fileName={fileName} />,
      );
    });
  };

  it('renders the thumbnail with accessible alt text', async () => {
    await render('blob:test-photo', 'photo.png');
    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    expect(img?.getAttribute('src')).toBe('blob:test-photo');
    expect(img?.getAttribute('alt')).toBe('photo.png');
  });

  it('falls back to the document icon when the image cannot load', async () => {
    await render('blob:dead-url', 'photo.png');
    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    await act(async () => {
      img?.dispatchEvent(new Event('error'));
    });
    const fallback = container.querySelector('img');
    expect(fallback?.getAttribute('alt')).toBe('Attachment');
    expect(fallback?.getAttribute('src')).not.toBe('blob:dead-url');
  });
});
