import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { PromptEditReview } from './PromptEditReview';
import type { PromptReview } from './usePromptReview';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
  }),
}));

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const LINE = 'If the pages do not cover it, say so.';
const TEXT = `Answer from the pages.\n${LINE}\nKeep it short.`;

const reviewOf = (
  edits: PromptReview['proposal']['edits'],
  current: string | null = null,
): PromptReview => ({
  proposal: { edits },
  original: TEXT,
  decisions: {},
  current,
});

describe('PromptEditReview', () => {
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
    vi.restoreAllMocks();
  });

  it('marks only what changes, the words it shares staying plain', async () => {
    await act(async () =>
      root.render(
        <PromptEditReview
          review={reviewOf([
            {
              id: 'e1',
              find: LINE,
              replace: `${LINE}\n## Boundaries`,
              reason: 'Adds the guard.',
            },
          ])}
          onDecide={() => undefined}
        />,
      ),
    );
    const change = container.querySelector('[data-edit-id="e1"]')!;
    // The re-sent line is not struck and added back: only the new text is.
    expect(change.querySelector('del')).toBeNull();
    expect(change.querySelector('ins')!.textContent).toBe(
      'drafter.prompt.addedText\n## Boundaries',
    );
    expect(change.textContent).toBe(
      `${LINE}1drafter.prompt.addedText\n## Boundaries`,
    );
  });

  // Live check 101: the current change's underline ran under the words it
  // keeps too.
  it('underlines only the changed words of the current change', async () => {
    await act(async () =>
      root.render(
        <PromptEditReview
          review={reviewOf(
            [
              {
                id: 'e1',
                find: 'Keep it short.',
                replace: 'Keep it short and plain.',
                reason: 'Plainer.',
              },
            ],
            'e1',
          )}
          onDecide={() => undefined}
        />,
      ),
    );
    const change = container.querySelector('[data-edit-id="e1"]')!;
    expect(change.className).not.toContain('underline');
    const marked = Array.from(change.querySelectorAll('.underline'));
    expect(marked).toHaveLength(1);
    // Only what comes and goes; the shared "Keep it short" stays plain.
    expect(marked[0].textContent).not.toContain('Keep it short');
    expect(marked[0].textContent).toContain('and plain');
  });

  it('opens on change 1, scrolled to the top of the box, focus left alone', async () => {
    const scrolled = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrolled,
    });
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
      function (this: HTMLElement) {
        const top = this.hasAttribute('data-edit-id') ? 400 : 100;
        return { top } as DOMRect;
      },
    );
    const outside = document.createElement('button');
    document.body.appendChild(outside);
    outside.focus();
    await act(async () =>
      root.render(
        <PromptEditReview
          review={reviewOf([
            {
              id: 'e1',
              find: 'Keep it short.',
              replace: 'Keep it brief.',
              reason: 'r',
            },
          ])}
          onDecide={() => undefined}
        />,
      ),
    );
    const box = container.querySelector<HTMLElement>('[role="region"]')!;
    // The change sits at the box's top (its padding aside).
    expect(box.scrollTop).toBe(300);
    expect(scrolled).toHaveBeenCalledWith({ block: 'nearest' });
    expect(document.activeElement).toBe(outside);
    outside.remove();
  });
});
