import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

import PromptTextArea from './PromptTextArea';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('PromptTextArea mention menu', () => {
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
    document.body.innerHTML = '';
  });

  const render = (value: string) =>
    act(() => {
      root.render(
        <PromptTextArea
          value={value}
          onChange={() => undefined}
          nodes={[]}
          edges={[]}
          selectedNodeId="n1"
        />,
      );
    });

  const menu = () =>
    document.querySelector('[data-slot="popover-content"]') as HTMLElement;

  it('opens a portalled popover on "{{" and keeps focus in the textarea', () => {
    render('{{');
    const textarea = container.querySelector('textarea')!;
    act(() => {
      textarea.focus();
      textarea.setSelectionRange(2, 2);
      textarea.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
    });

    expect(menu()).not.toBeNull();
    expect(container.contains(menu())).toBe(false);
    expect(menu().textContent).toContain('source.content');
    expect(document.activeElement).toBe(textarea);
  });

  it('closes when the trigger text is gone', () => {
    render('{{');
    const textarea = container.querySelector('textarea')!;
    act(() => {
      textarea.focus();
      textarea.setSelectionRange(2, 2);
      textarea.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
    });
    render('hello');
    act(() => {
      textarea.setSelectionRange(5, 5);
      textarea.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
    });

    expect(menu()).toBeNull();
  });
});
