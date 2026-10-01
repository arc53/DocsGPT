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

  const openMenu = (value: string, onChange = vi.fn()) => {
    act(() => {
      root.render(
        <PromptTextArea
          value={value}
          onChange={onChange}
          nodes={[]}
          edges={[]}
          selectedNodeId="n1"
        />,
      );
    });
    const textarea = container.querySelector('textarea')!;
    act(() => {
      textarea.focus();
      textarea.setSelectionRange(value.length, value.length);
      textarea.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
    });
    return { textarea, onChange };
  };

  it('is a Command listbox: group headings and option rows', () => {
    openMenu('{{');
    expect(menu().querySelector('[data-slot="command"]')).not.toBeNull();
    expect(menu().querySelector('[role="listbox"]')).not.toBeNull();
    const headings = Array.from(
      menu().querySelectorAll('[cmdk-group-heading]'),
    ).map((h) => h.textContent);
    expect(headings).toContain('agents.workflow.variables.globalContext');
    // The CommandGroup heading, not a hand-written uppercase eyebrow.
    expect(menu().querySelector('.uppercase')).toBeNull();
    const options = Array.from(
      menu().querySelectorAll<HTMLElement>('[role="option"]'),
    );
    expect(options.map((o) => o.textContent)).toContain('source.content');
    expect(menu().querySelector('button')).toBeNull();
  });

  it('walks the menu with the arrow keys from the textarea and inserts on Enter', () => {
    const { textarea, onChange } = openMenu('{{');
    const key = (k: string) =>
      act(() => {
        textarea.dispatchEvent(
          new KeyboardEvent('keydown', { key: k, bubbles: true }),
        );
      });
    const active = () =>
      menu().querySelector('[data-selected="true"]')?.textContent;
    const options = Array.from(
      menu().querySelectorAll<HTMLElement>('[role="option"]'),
    ).map((o) => o.textContent);
    expect(active()).toBe(options[0]);
    key('ArrowDown');
    expect(active()).toBe(options[1]);
    key('Enter');
    expect(onChange).toHaveBeenCalledWith(`{{ ${options[1]} }}`);
  });

  it('filters by the text typed after "{{"', () => {
    openMenu('{{ system');
    const options = Array.from(
      menu().querySelectorAll<HTMLElement>('[role="option"]'),
    ).map((o) => o.textContent);
    expect(options.length).toBeGreaterThan(0);
    expect(options.every((o) => o?.startsWith('system.'))).toBe(true);
  });
});
