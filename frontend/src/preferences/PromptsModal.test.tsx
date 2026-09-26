import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('react-router-dom', () => ({
  Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
}));

vi.mock('../api/services/userService', () => ({
  default: {
    getUserTools: () =>
      Promise.resolve({ json: () => Promise.resolve({ success: false }) }),
  },
}));

import PromptsModal from './PromptsModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('PromptsModal', () => {
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

  const render = async (setContent: (c: string) => void = () => undefined) => {
    await act(async () => {
      root.render(
        <PromptsModal
          existingPrompts={[]}
          modalState="ACTIVE"
          setModalState={() => undefined}
          type="ADD"
          newPromptName=""
          setNewPromptName={() => undefined}
          newPromptContent="Hello {{ source.content }}"
          setNewPromptContent={setContent}
          editPromptName=""
          setEditPromptName={() => undefined}
          editPromptContent=""
          setEditPromptContent={() => undefined}
          currentPromptEdit={{ name: '', id: '', type: '' }}
        />,
      );
    });
  };

  it('edits the prompt text in a large Textarea', async () => {
    await render();
    const textarea = document.body.querySelector<HTMLTextAreaElement>(
      '#new-prompt-content',
    );
    expect(textarea?.dataset.slot).toBe('textarea');
    expect(textarea?.dataset.size).toBe('lg');
  });

  it('scrolls the highlight layer through custom properties, not a transform', async () => {
    await render();
    const layer = document.body.querySelector<HTMLElement>(
      '.prompt-variable-highlight',
    )?.parentElement;
    expect(layer).toBeTruthy();
    expect(layer?.style.transform).toBe('');
    expect(layer?.style.getPropertyValue('--scroll-x')).toBe('0px');
    expect(layer?.style.getPropertyValue('--scroll-y')).toBe('0px');
  });
  it('inserts a variable from a Select that never keeps a value', async () => {
    const setContent = vi.fn();
    await render(setContent);
    const triggers = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>(
        '[data-slot="select-trigger"]',
      ),
    );
    expect(triggers.map((b) => b.textContent)).toEqual([
      'modals.prompts.systemVariablesDropdownLabel',
      'modals.prompts.toolVariables',
    ]);
    const [system] = triggers;
    expect(system.dataset.size).toBe('field');
    expect(system.dataset.shape).toBe('pill');
    expect(system.hasAttribute('data-placeholder')).toBe(true);

    const textarea = document.body.querySelector<HTMLTextAreaElement>(
      '#new-prompt-content',
    )!;
    textarea.setSelectionRange(5, 5);
    await act(async () => {
      system.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
    const option = Array.from(
      document.body.querySelectorAll<HTMLElement>('[role="option"]'),
    ).find((o) =>
      o.textContent?.includes(
        'modals.prompts.systemVariableOptions.systemDate',
      ),
    );
    expect(option).toBeDefined();
    await act(async () => {
      option!.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
    expect(setContent).toHaveBeenCalledWith(
      'Hello {{ system.date }} {{ source.content }}',
    );
    // The trigger falls back to its label: nothing stays selected.
    expect(system.textContent).toBe(
      'modals.prompts.systemVariablesDropdownLabel',
    );
  });
});
