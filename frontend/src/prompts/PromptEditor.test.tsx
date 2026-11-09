import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { PromptReview } from '../drafter/usePromptDrafter';

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const { interpolation: _i, ...rest } = opts ?? {};
      void _i;
      return Object.keys(rest).length ? `${key}:${JSON.stringify(rest)}` : key;
    },
  }),
}));
const checks = vi.hoisted(() => ({
  check: vi.fn(),
}));
vi.mock('./promptChecks', () => ({ checkPrompt: checks.check }));
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
    edits: [{ id: 'e1', find: 'Be brief.', replace: 'Be short.', reason: 'x' }],
  },
  original: 'Be brief.',
  decisions: {},
  current: null,
};

describe('PromptEditor', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    checks.check.mockReset();
    checks.check.mockResolvedValue([]);
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
      '[aria-label^="drafter.undoField"]',
    );
    expect(undo).not.toBeNull();
    await act(async () => undo!.click());
    expect(onUndo).toHaveBeenCalled();
  });

  it("says when the text is a template that won't parse", async () => {
    await render({ content: '{{ source.content }}{% if x %}Hi' });
    expect(container.textContent).toContain('modals.prompts.templateBroken');
    expect(
      container.querySelector('textarea')!.getAttribute('aria-invalid'),
    ).toBe('true');
    await render({ content: '{{ source.content }}{% if x %}Hi{% endif %}' });
    expect(container.textContent).not.toContain(
      'modals.prompts.templateBroken',
    );
  });

  // The review of a running draft is built from the text it was sent with:
  // nothing may change the text until it lands.
  it('changes nothing while a draft runs: no menus, no undo', async () => {
    const onUndo = vi.fn();
    await render({
      locked: true,
      draftedName: { drafted: true, onUndo },
      draftedContent: { drafted: true, onUndo },
    });
    expect(container.querySelector('input')!.readOnly).toBe(true);
    expect(container.querySelector('textarea')!.readOnly).toBe(true);
    for (const menu of menus())
      expect((menu as HTMLButtonElement).disabled).toBe(true);
    const undos = container.querySelectorAll<HTMLButtonElement>(
      '[aria-label^="drafter.undoField"]',
    );
    expect(undos).toHaveLength(2);
    for (const undo of undos) {
      expect(undo.disabled).toBe(true);
      await act(async () => undo.click());
    }
    expect(onUndo).not.toHaveBeenCalled();
  });

  // ---- The checks hint (no model) ----

  const PLACEHOLDER = { code: 'placeholder', text: '[support email]', line: 4 };
  const DATE = { code: 'repeats_builtin', topic: 'date', line: 3 };
  const hint = () =>
    container.querySelector<HTMLElement>('[data-slot="prompt-checks"]');
  const settle = () =>
    act(async () => {
      vi.advanceTimersByTime(400);
    });

  describe('checks hint', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('checks the text once typing pauses, and folds what it found', async () => {
      checks.check.mockResolvedValue([
        PLACEHOLDER,
        DATE,
        // The field's own error says this one.
        { code: 'template_invalid' },
        { code: 'from_a_newer_server' },
      ]);
      await render({ content: 'Hello' });
      await render({ content: 'Hello there' });
      expect(checks.check).not.toHaveBeenCalled();
      await settle();
      // Only the text it rested on is checked, the older one was dropped.
      expect(checks.check).toHaveBeenCalledTimes(1);
      expect(checks.check.mock.calls[0][0]).toBe('Hello there');
      const toggle = hint()!.querySelector<HTMLButtonElement>('button')!;
      expect(toggle.textContent).toBe('prompts.checksHint.count:{"count":2}');
      expect(toggle.getAttribute('aria-expanded')).toBe('false');
      await act(async () => toggle.click());
      expect(toggle.getAttribute('aria-expanded')).toBe('true');
      expect(
        Array.from(hint()!.querySelectorAll('li')).map((li) => li.textContent),
      ).toEqual([
        'prompts.checks.placeholder:{"text":"[support email]"}',
        'prompts.checks.onLine:{"check":"prompts.checks.repeatsBuiltin.date","line":3}',
      ]);
      // No review link unless the host can send one.
      expect(hint()!.querySelectorAll('button')).toHaveLength(1);
    });

    it('aborts the request a newer text replaced', async () => {
      const signals: AbortSignal[] = [];
      checks.check.mockImplementation(
        (_content: string, _token: string, signal: AbortSignal) => {
          signals.push(signal);
          return new Promise(() => undefined);
        },
      );
      await render({ content: 'One' });
      await settle();
      await render({ content: 'Two' });
      expect(signals[0].aborted).toBe(true);
    });

    it('shows nothing when nothing is found or the check fails', async () => {
      await render({ content: 'Hello' });
      await settle();
      expect(hint()).toBeNull();
      checks.check.mockResolvedValue(null);
      await render({ content: 'Hello again' });
      await settle();
      expect(hint()).toBeNull();
    });

    it('offers a full review with the drafter, except while a draft runs', async () => {
      checks.check.mockResolvedValue([PLACEHOLDER]);
      const onReview = vi.fn();
      await render({ onReview });
      await settle();
      const link = Array.from(
        hint()!.querySelectorAll<HTMLButtonElement>('button'),
      ).find((b) => b.textContent === 'prompts.checksHint.review')!;
      await act(async () => link.click());
      expect(onReview).toHaveBeenCalled();
      await render({ onReview, locked: true });
      expect(hint()!.textContent).not.toContain('prompts.checksHint.review');
    });

    it('checks nothing on a prompt to view or under review', async () => {
      checks.check.mockResolvedValue([PLACEHOLDER]);
      await render({ isReadOnly: true });
      await settle();
      await render({ review: REVIEW, onDecide: () => undefined });
      await settle();
      expect(checks.check).not.toHaveBeenCalled();
      expect(hint()).toBeNull();
    });
  });
});
