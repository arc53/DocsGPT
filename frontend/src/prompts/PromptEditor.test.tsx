import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { PromptReview } from '../drafter/usePromptDrafter';

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('../api/services/userService', () => ({
  default: {
    getUserTools: () =>
      Promise.resolve({ json: () => Promise.resolve({ success: false }) }),
  },
}));

import { PromptEditor, type PromptEditorProps } from './PromptEditor';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const REVIEW: PromptReview = {
  proposal: {
    mode: 'improve',
    message: '',
    edits: [{ id: 'e1', find: 'Be brief.', replace: 'Be short.', reason: 'x' }],
    result: 'Be short.',
    templateMode: { before: false, after: false },
    warnings: [],
    checks: [],
    suggestions: [],
  },
  original: 'Be brief.',
  decisions: {},
  current: null,
};

describe('PromptEditor', () => {
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

  const render = (props: Partial<PromptEditorProps> = {}) =>
    act(async () => {
      root.render(
        <PromptEditor
          idPrefix="edit"
          name="Support"
          setName={() => undefined}
          content="Hello {{ source.content }}"
          setContent={() => undefined}
          {...props}
        />,
      );
    });

  const labels = () =>
    Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="form-field-label"]'),
    );
  const menus = () =>
    container.querySelectorAll('[data-slot="select-trigger"]');

  it('edits the name and the highlighted text with the variable menus', async () => {
    await render();
    expect(labels().map((label) => label.textContent)).toEqual([
      'modals.prompts.promptName',
      'modals.prompts.promptText',
    ]);
    expect(
      container.querySelector<HTMLTextAreaElement>('#edit-prompt-content')!
        .value,
    ).toBe('Hello {{ source.content }}');
    expect(
      container.querySelector('.prompt-variable-highlight')!.textContent,
    ).toBe('{{ source.content }}');
    expect(menus()).toHaveLength(2);
  });

  it("sits on the page's background", async () => {
    await render();
    for (const label of labels())
      expect(label.className).toContain('bg-background');
    expect(
      container.querySelector('.prompt-variable-highlight')!.parentElement!
        .parentElement!.className,
    ).toContain('bg-background');
  });

  it('shows a prompt to view read-only, without the menus', async () => {
    await render({ isReadOnly: true, showViewOnlyNotice: true });
    expect(container.querySelector('input')!.disabled).toBe(true);
    expect(container.querySelector('textarea')!.readOnly).toBe(true);
    expect(menus()).toHaveLength(0);
    expect(container.textContent).toContain('common.viewOnlyNotice');
  });

  it('shows an open review in place of the text, its choices inline', async () => {
    const onDecide = vi.fn();
    await render({ review: REVIEW, onDecide });
    expect(container.querySelector('textarea')).toBeNull();
    expect(menus()).toHaveLength(0);
    const accept = container.querySelector<HTMLButtonElement>(
      '[data-action="accept"]',
    )!;
    await act(async () => accept.click());
    expect(onDecide).toHaveBeenCalledWith('e1', 'accepted');
  });

  it('marks a drafted field with its undo', async () => {
    const onUndo = vi.fn();
    await render({ draftedContent: { drafted: true, onUndo } });
    const undo = container.querySelector<HTMLButtonElement>(
      '[aria-label="drafter.undoField"]',
    );
    expect(undo).not.toBeNull();
    await act(async () => undo!.click());
    expect(onUndo).toHaveBeenCalled();
  });
});
