import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import RetrievalOptions, {
  DEFAULT_RETRIEVAL_OPTIONS,
} from './RetrievalOptions';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('RetrievalOptions disclosure', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('opens the options in a Collapsible the toggle controls', () => {
    act(() => {
      root.render(
        <RetrievalOptions
          value={DEFAULT_RETRIEVAL_OPTIONS}
          onChange={vi.fn()}
        />,
      );
    });
    const toggle = container.querySelector(
      'button[aria-expanded]',
    ) as HTMLButtonElement;
    const body = container.querySelector('[data-slot="collapsible"]');
    expect(body).not.toBeNull();
    expect(toggle.getAttribute('aria-controls')).toBe(body!.id);
    expect(body!.getAttribute('data-state')).toBe('closed');
    act(() => toggle.click());
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(body!.getAttribute('data-state')).toBe('open');
  });

  it('leaves no gap under the closed toggle: the body carries the space', () => {
    act(() => {
      root.render(
        <RetrievalOptions
          value={DEFAULT_RETRIEVAL_OPTIONS}
          onChange={vi.fn()}
        />,
      );
    });
    const wrapper = container.firstElementChild as HTMLElement;
    expect(wrapper.className.split(' ')).not.toContain('gap-4');
    const collapsible = container.querySelector(
      '[data-slot="collapsible"]',
    ) as HTMLElement;
    const inner = collapsible.firstElementChild!
      .firstElementChild as HTMLElement;
    expect(inner.className.split(' ')).toContain('pt-4');
  });

  it('caps the chunk-size input and explains the limit', () => {
    act(() => {
      root.render(
        <RetrievalOptions
          value={DEFAULT_RETRIEVAL_OPTIONS}
          onChange={vi.fn()}
          alwaysOpen
        />,
      );
    });

    const input = container.querySelector(
      '#chunking-max-tokens',
    ) as HTMLInputElement;
    expect(input.max).toBe('4096');
    expect(container.textContent).toContain('chunking.maxTokensHint');
  });
});
