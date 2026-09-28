import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import type { Attachment } from '../../upload/uploadSlice';
import AttachmentChipList from './AttachmentChipList';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const att = (over: Partial<Attachment> = {}): Attachment => ({
  id: 'a1',
  fileName: 'scan.pdf',
  progress: 0,
  status: 'failed',
  taskId: '',
  errorMessage: 'Upload failed. The file could not be read.',
  ...over,
});

describe('AttachmentChipList failed chip', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.useFakeTimers();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.useRealTimers();
  });

  const render = async (attachments: Attachment[]) => {
    await act(async () => {
      root.render(
        <AttachmentChipList
          attachments={attachments}
          draggingId={null}
          onRemove={() => {}}
          onDragStart={() => {}}
          onDragOver={() => {}}
          onDropOn={() => {}}
        />,
      );
    });
  };

  const tooltip = () =>
    document.body.querySelector('[data-slot="tooltip-content"]');

  it('shows no inline failure line under the chips', async () => {
    await render([att()]);

    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('.text-destructive')).toBeNull();
  });

  it('shows the reason in a tooltip when the chip is hovered', async () => {
    await render([att()]);
    expect(tooltip()).toBeNull();

    // The remove X is an IconButton with its own tooltip; the chip is the div.
    const chip = container.querySelector('div[data-slot="tooltip-trigger"]')!;
    await act(async () => {
      chip.dispatchEvent(
        new PointerEvent('pointermove', {
          bubbles: true,
          pointerType: 'mouse',
        }),
      );
      vi.advanceTimersByTime(500);
    });

    // The full name, since two long names can truncate to the same text.
    expect(tooltip()?.textContent).toContain(
      'scan.pdf: Upload failed. The file could not be read.',
    );
  });

  it('announces failures in a persistent polite live region', async () => {
    await render([att({ status: 'uploading', errorMessage: undefined })]);
    const region = container.querySelector('[role="status"]');
    expect(region?.textContent).toBe('');

    await render([att()]);

    // Same node, updated in place, so screen readers announce the change.
    expect(container.querySelector('[role="status"]')).toBe(region);
    expect(region?.textContent).toBe(
      'scan.pdf: Upload failed. The file could not be read.',
    );
  });

  it('describes the focusable remove button with the reason', async () => {
    await render([att()]);

    const remove = container.querySelector(
      'button[aria-label="conversation.attachments.remove"]',
    )!;
    const describedBy = remove.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy!)?.textContent).toBe(
      'Upload failed. The file could not be read.',
    );
  });

  it('adds no tooltip to a chip that did not fail', async () => {
    await render([att({ status: 'completed', errorMessage: undefined })]);

    expect(
      container.querySelector('div[data-slot="tooltip-trigger"]'),
    ).toBeNull();
  });
});
