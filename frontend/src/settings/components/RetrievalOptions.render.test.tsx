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
});
