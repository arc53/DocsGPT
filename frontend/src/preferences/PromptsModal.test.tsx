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

  it('scrolls the editor body so a short window never pushes it under the footer', async () => {
    await render();
    const textarea = document.body.querySelector<HTMLTextAreaElement>(
      '#new-prompt-content',
    );
    // The Modal body is the textarea's nearest ancestor that sits beside the
    // footer; it must stay the dialog's scroller (the variable menus portal
    // their lists, so nothing in it has to escape).
    const footer = document.body.querySelector('[data-slot="modal-footer"]');
    const body = footer?.previousElementSibling as HTMLElement | null;
    expect(body?.contains(textarea)).toBe(true);
    expect(body?.className).toContain('overflow-y-auto');
    expect(body?.className).not.toContain('overflow-visible');
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

  it('opens a prompt the caller may not edit read-only', async () => {
    await act(async () => {
      root.render(
        <PromptsModal
          existingPrompts={[]}
          modalState="ACTIVE"
          setModalState={() => undefined}
          type="EDIT"
          newPromptName=""
          setNewPromptName={() => undefined}
          newPromptContent=""
          setNewPromptContent={() => undefined}
          editPromptName="Carrier rates"
          setEditPromptName={() => undefined}
          editPromptContent="Summarise {{ source.content }}"
          setEditPromptContent={() => undefined}
          currentPromptEdit={{ name: 'Carrier rates', id: 'p1', type: 'team' }}
          handleEditPrompt={() => undefined}
          readOnly
        />,
      );
    });
    expect(document.body.textContent).toContain('modals.prompts.viewPrompt');
    expect(
      document.body.querySelector<HTMLTextAreaElement>('textarea')?.readOnly,
    ).toBe(true);
    expect(
      document.body.querySelector<HTMLInputElement>('input[type="text"]')
        ?.disabled,
    ).toBe(true);
    const labels = Array.from(document.body.querySelectorAll('button')).map(
      (b) => b.textContent,
    );
    expect(labels).not.toContain('modals.prompts.save');
    // A shared prompt gets the shared view-only notice, not the built-in copy.
    expect(document.body.textContent).toContain('common.viewOnlyNotice');
    expect(document.body.textContent).not.toContain(
      'modals.prompts.viewDescription',
    );
    expect(
      document.body.querySelector('[data-slot="alert"]')?.getAttribute('role'),
    ).toBe('note');
    expect(labels).toContain('common.close');
    expect(labels).not.toContain('modals.prompts.cancel');
  });

  it('keeps the built-in copy for a built-in prompt', async () => {
    await act(async () => {
      root.render(
        <PromptsModal
          existingPrompts={[]}
          modalState="ACTIVE"
          setModalState={() => undefined}
          type="EDIT"
          newPromptName=""
          setNewPromptName={() => undefined}
          newPromptContent=""
          setNewPromptContent={() => undefined}
          editPromptName="Default"
          setEditPromptName={() => undefined}
          editPromptContent="You are a helpful assistant."
          setEditPromptContent={() => undefined}
          currentPromptEdit={{ name: 'Default', id: 'd1', type: 'public' }}
          handleEditPrompt={() => undefined}
          onDuplicate={() => undefined}
        />,
      );
    });
    expect(document.body.textContent).toContain(
      'modals.prompts.viewDescription',
    );
    expect(document.body.textContent).not.toContain('common.viewOnlyNotice');
    const labels = Array.from(document.body.querySelectorAll('button')).map(
      (b) => b.textContent,
    );
    expect(labels).toContain('modals.prompts.duplicate');
    expect(labels).toContain('common.close');
  });
});
