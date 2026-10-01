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
    // Named, since the button's own label doesn't say which file.
    expect(document.getElementById(describedBy!)?.textContent).toBe(
      'scan.pdf: Upload failed. The file could not be read.',
    );
  });

  it('adds no tooltip to a chip that did not fail', async () => {
    await render([att({ status: 'completed', errorMessage: undefined })]);

    expect(
      container.querySelector('div[data-slot="tooltip-trigger"]'),
    ).toBeNull();
  });
});

describe('AttachmentChipList states', () => {
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

  const chipOf = (name: string) =>
    [...container.querySelectorAll<HTMLElement>('[draggable="true"]')].find(
      (chip) => chip.textContent?.includes(name),
    )!;

  it('marks a file still waiting for an upload slot as queued', async () => {
    await render([
      att({ id: 'q', fileName: 'queued.pdf', status: 'uploading' }),
      att({
        id: 'u',
        fileName: 'moving.pdf',
        status: 'uploading',
        progress: 40,
      }),
      att({
        id: 'p',
        fileName: 'parsing.pdf',
        status: 'processing',
        progress: 10,
      }),
    ]);

    expect(
      chipOf('queued.pdf').querySelector(
        'svg[aria-label="conversation.attachments.queued"]',
      ),
    ).not.toBeNull();
    expect(
      chipOf('moving.pdf').querySelector(
        '[aria-label="conversation.attachments.uploading"]',
      ),
    ).not.toBeNull();
    expect(
      chipOf('parsing.pdf').querySelector(
        '[aria-label="conversation.attachments.processing"]',
      ),
    ).not.toBeNull();
  });

  it('caps the chip area and scrolls it, so many files keep the page in view', async () => {
    await render([att({ status: 'completed', errorMessage: undefined })]);
    const list = container.querySelector('[data-slot="attachment-chips"]')!;
    expect(list.className).toMatch(/(^|\s)max-h-\S+/);
    expect(list.className).toContain('overflow-y-auto');
  });

  it('draws a failed chip in the destructive tone, not faded', async () => {
    await render([
      att({ id: 'f', fileName: 'bad.mov' }),
      att({ id: 'ok', fileName: 'good.pdf', status: 'completed' }),
    ]);
    const failed = chipOf('bad.mov');
    expect(failed.getAttribute('data-status')).toBe('failed');
    expect(failed.className).toContain('border-destructive/50');
    expect(failed.className).toContain('bg-destructive/10');
    expect(failed.className).not.toContain('opacity-70');
    const tile = failed.querySelector('[data-slot="attachment-tile"]')!;
    expect(tile.className).toContain('bg-destructive');
    expect(tile.className).not.toContain('bg-primary');

    const good = chipOf('good.pdf');
    expect(good.className).not.toContain('destructive');
  });

  it('opens the failure reason on keyboard focus too', async () => {
    await render([att()]);
    const chip = chipOf('scan.pdf');
    expect(chip.tabIndex).toBe(0);
    await act(async () => {
      chip.focus();
      vi.advanceTimersByTime(500);
    });
    expect(
      document.body.querySelector('[data-slot="tooltip-content"]')?.textContent,
    ).toContain('Upload failed. The file could not be read.');
  });
});
