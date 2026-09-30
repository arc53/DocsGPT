import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const dispatch = vi.fn();
vi.mock('react-redux', () => ({
  useSelector: () => 'test-token',
  useDispatch: () => dispatch,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const deletePrompt = vi.fn();
const updatePrompt = vi.fn();
const getSinglePrompt = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    deletePrompt: (...args: unknown[]) => deletePrompt(...args),
    updatePrompt: (...args: unknown[]) => updatePrompt(...args),
    getSinglePrompt: (...args: unknown[]) => getSinglePrompt(...args),
  },
}));
vi.mock('../teams/ShareToTeamModal', () => ({ default: () => null }));
const promptsModalProps = vi.fn();
vi.mock('../preferences/PromptsModal', () => ({
  default: (props: unknown) => {
    promptsModalProps(props);
    return null;
  },
}));
const confirm = vi.hoisted(() => ({
  result: undefined as void | Promise<unknown>,
}));
vi.mock('../modals/ConfirmationModal', () => ({
  default: ({
    handleSubmit,
    error,
  }: {
    handleSubmit: () => void | Promise<unknown>;
    error?: string;
  }) => (
    <>
      <button
        type="button"
        data-testid="confirm"
        onClick={() => {
          const result = handleSubmit();
          // Mark it handled; the tests assert on it afterwards.
          if (result) result.catch(() => undefined);
          confirm.result = result;
        }}
      >
        confirm
      </button>
      <p data-testid="confirm-error">{error}</p>
    </>
  ),
}));

import Prompts from './Prompts';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const prompts = [
  { id: 'p1', name: 'Default', type: 'public' },
  { id: 'p2', name: 'Vendor due diligence', type: 'private' },
  { id: 'p3', name: 'Carrier rate summary', type: 'private' },
];

describe('Prompts', () => {
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

  const renderPrompts = (
    extra: Partial<React.ComponentProps<typeof Prompts>> = {},
  ) =>
    act(() => {
      root.render(
        <Prompts
          prompts={prompts}
          selectedPrompt={prompts[1]}
          onSelectPrompt={() => undefined}
          setPrompts={() => undefined}
          {...extra}
        />,
      );
    });

  it('renders the prompt picker as a 38px combobox field pill', () => {
    renderPrompts();
    const trigger = container.querySelector<HTMLButtonElement>(
      'button[role="combobox"]',
    );
    expect(trigger?.getAttribute('data-variant')).toBe('combobox');
    expect(trigger?.getAttribute('data-size')).toBe('field');
    expect(trigger?.getAttribute('data-shape')).toBe('pill');
    expect(trigger?.className).toMatch(/(^|\s)h-9\.5(\s|$)/);
    expect(trigger?.className).not.toMatch(/(^|\s)h-10\.5(\s|$)/);
  });

  it('puts the edit pencil beside the picker, not inside it', () => {
    renderPrompts();
    const trigger = container.querySelector<HTMLButtonElement>(
      'button[role="combobox"]',
    );
    expect(trigger?.querySelector('[role="button"], button')).toBeNull();
    const edit = container.querySelector<HTMLButtonElement>(
      'button[aria-label="settings.general.promptActions.edit"]',
    );
    expect(edit).not.toBeNull();
    expect(edit?.getAttribute('data-variant')).toBe('ghost-muted');
    expect(edit?.getAttribute('data-size')).toBe('icon-xs');
    expect(edit?.parentElement).toBe(trigger?.parentElement);
  });

  it('renders a SettingRow on Settings whose label names the picker', () => {
    renderPrompts({ description: 'Used without an agent.' });
    const trigger = container.querySelector<HTMLButtonElement>(
      'button[role="combobox"]',
    )!;
    expect(
      container.querySelector('[data-slot="form-field-label"]'),
    ).toBeNull();
    const row = container.querySelector('[data-slot="setting-row"]')!;
    const label = row.querySelector<HTMLLabelElement>('label')!;
    expect(label.textContent).toBe('settings.general.prompt');
    expect(trigger.id).toBeTruthy();
    expect(label.htmlFor).toBe(trigger.id);
    expect(row.textContent).toContain('Used without an agent.');
    expect(trigger.hasAttribute('aria-label')).toBe(false);
    // 224px from sm, full width when the row stacks on a phone.
    expect(trigger.className.split(' ')).toEqual(
      expect.arrayContaining(['w-full', 'sm:w-56']),
    );
  });

  it('keeps a section heading above the picker with titleAs="heading"', () => {
    renderPrompts({
      titleAs: 'heading',
      title: 'Prompt',
    });
    expect(
      container.querySelector('[data-slot="form-field-label"]'),
    ).toBeNull();
    const heading = container.querySelector(
      '[data-slot="section-header"] > h2',
    )!;
    expect(heading.textContent).toBe('Prompt');
    expect(heading.className.split(' ')).toEqual(
      expect.arrayContaining(['text-lg', 'font-semibold']),
    );
    expect(
      container
        .querySelector('button[role="combobox"]')
        ?.getAttribute('aria-label'),
    ).toBe('Prompt');
  });

  it('labels the picker with a floating FormField label with titleAs="field"', () => {
    renderPrompts({
      titleAs: 'field',
      title: 'Prompt',
      labelSurface: 'background',
      showAddButton: false,
    });
    expect(container.querySelector('[data-slot="section-header"]')).toBeNull();
    const label = container.querySelector<HTMLLabelElement>(
      '[data-slot="form-field-label"]',
    )!;
    expect(label.textContent).toBe('Prompt');
    expect(label.className).toContain('bg-background');
    const trigger = container.querySelector<HTMLButtonElement>(
      'button[role="combobox"]',
    )!;
    expect(trigger.id).toBeTruthy();
    expect(label.htmlFor).toBe(trigger.id);
    expect(trigger.hasAttribute('aria-label')).toBe(false);
    expect(trigger.className).toContain('w-full');
  });

  it('makes Add a neutral outline pill sized to the field row', () => {
    renderPrompts();
    const add = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[data-slot="button"]'),
    ).find((b) => b.textContent === 'settings.general.add');
    expect(add?.getAttribute('data-size')).toBe('field');
    expect(add?.getAttribute('data-shape')).toBe('pill');
    expect(add?.getAttribute('data-variant')).toBe('outline');
    expect(add?.className).not.toMatch(/(^|\s)h-11\.5(\s|$)/);
  });

  it('marks only the active prompt as checked in the list', () => {
    act(() => {
      root.render(
        <Prompts
          prompts={prompts}
          selectedPrompt={prompts[1]}
          onSelectPrompt={() => undefined}
          setPrompts={() => undefined}
        />,
      );
    });

    const trigger = container.querySelector<HTMLButtonElement>(
      'button[role="combobox"]',
    );
    expect(trigger).not.toBeNull();
    act(() => {
      trigger!.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      trigger!.click();
    });

    const items = Array.from(
      document.body.querySelectorAll<HTMLElement>('[data-slot="command-item"]'),
    );
    expect(items).toHaveLength(3);

    const byName = (name: string) =>
      items.find((item) => item.textContent?.includes(name));
    expect(byName('Vendor due diligence')?.dataset.checked).toBe('true');
    expect(byName('Default')?.dataset.checked).toBeUndefined();
    expect(byName('Carrier rate summary')?.dataset.checked).toBeUndefined();
    // The fill comes from the checked API, not from page classes.
    expect(byName('Vendor due diligence')?.className).not.toMatch(
      /(^|\s)(bg-accent|font-medium)(\s|$)/,
    );
    // Row actions are IconButtons: named, with a tooltip instead of `title`.
    const actions = Array.from(
      byName('Vendor due diligence')!.querySelectorAll('button'),
    );
    expect(actions.length).toBeGreaterThan(0);
    for (const action of actions) {
      expect(action.getAttribute('aria-label')).toBeTruthy();
      expect(action.hasAttribute('title')).toBe(false);
      expect(action.dataset.slot).toBe('tooltip-trigger');
    }
  });

  describe('access', () => {
    const json = (body: unknown, ok = true, status = 200) =>
      Promise.resolve({ ok, status, json: () => Promise.resolve(body) });
    const own = {
      id: 'own',
      name: 'Own prompt',
      type: 'private',
      access: 'owner' as const,
      allowed_actions: [
        'delete',
        'duplicate',
        'edit',
        'manage_settings',
        'share',
        'use',
      ],
    };
    const editor = {
      id: 'ed',
      name: 'Editor prompt',
      type: 'team',
      access: 'editor' as const,
      allowed_actions: ['duplicate', 'edit', 'use'],
    };
    const viewer = {
      id: 'vw',
      name: 'Viewer prompt',
      type: 'team',
      access: 'viewer' as const,
      allowed_actions: ['duplicate', 'use'],
    };
    const viewerNoCopy = {
      id: 'vn',
      name: 'Locked prompt',
      type: 'team',
      access: 'viewer' as const,
      allowed_actions: ['use'],
    };
    const all = [prompts[0], own, editor, viewer, viewerNoCopy];

    beforeEach(() => {
      dispatch.mockReset();
      deletePrompt.mockReset();
      updatePrompt.mockReset();
      getSinglePrompt.mockReset();
      promptsModalProps.mockReset();
    });

    const openPicker = () =>
      act(() => {
        const trigger = container.querySelector<HTMLButtonElement>(
          'button[role="combobox"]',
        )!;
        trigger.dispatchEvent(
          new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
        );
        trigger.click();
      });
    const row = (name: string) =>
      Array.from(
        document.body.querySelectorAll<HTMLElement>(
          '[data-slot="command-item"]',
        ),
      ).find((item) => item.textContent?.includes(name))!;
    const actionsOf = (name: string) =>
      Array.from(row(name).querySelectorAll('button')).map((b) =>
        b.getAttribute('aria-label'),
      );
    const lastModalProps = () =>
      promptsModalProps.mock.calls.at(-1)![0] as {
        readOnly?: boolean;
        handleEditPrompt: (id: string, type: string) => void;
        onDuplicate?: () => void;
      };

    it('gives the owner Edit, Duplicate, Share and Delete', () => {
      renderPrompts({ prompts: all, selectedPrompt: own });
      openPicker();
      expect(actionsOf('Own prompt')).toEqual([
        'settings.general.promptActions.edit',
        'settings.general.promptActions.duplicate',
        'agents.shareWithTeam',
        'settings.general.promptActions.delete',
      ]);
    });

    it('gives an editor Edit and Duplicate', () => {
      renderPrompts({ prompts: all, selectedPrompt: own });
      openPicker();
      expect(actionsOf('Editor prompt')).toEqual([
        'settings.general.promptActions.edit',
        'settings.general.promptActions.duplicate',
      ]);
    });

    it('gives a viewer View, and Duplicate only when allowed', () => {
      renderPrompts({ prompts: all, selectedPrompt: own });
      openPicker();
      expect(actionsOf('Viewer prompt')).toEqual([
        'settings.general.promptActions.view',
        'settings.general.promptActions.duplicate',
      ]);
      expect(actionsOf('Locked prompt')).toEqual([
        'settings.general.promptActions.view',
      ]);
    });

    it("opens a viewer's prompt read-only", async () => {
      getSinglePrompt.mockReturnValue(json({ content: 'Hello' }));
      renderPrompts({ prompts: all, selectedPrompt: own });
      openPicker();
      await act(async () => {
        (row('Viewer prompt').querySelector('button') as HTMLElement).click();
      });
      expect(lastModalProps().readOnly).toBe(true);
    });

    it("keeps the server's actions for a selected prompt missing from the list", async () => {
      getSinglePrompt.mockReturnValue(json({ content: 'Hello' }));
      const unlisted = {
        id: 'ul',
        name: 'Unlisted prompt',
        type: 'team',
        access: 'editor' as const,
        allowed_actions: ['edit', 'use'],
      };
      renderPrompts({ prompts: all, selectedPrompt: unlisted });
      await act(async () => {
        container
          .querySelector<HTMLButtonElement>(
            'button[aria-label="settings.general.promptActions.edit"]',
          )!
          .click();
      });
      expect(lastModalProps().onDuplicate).toBeUndefined();
    });

    it('keeps the row and the error in the dialog when the delete fails', async () => {
      deletePrompt.mockReturnValue(json({ success: false }, false, 403));
      const setPrompts = vi.fn();
      renderPrompts({ prompts: all, selectedPrompt: own, setPrompts });
      openPicker();
      await act(async () => {
        (
          row('Own prompt').querySelector(
            'button[aria-label="settings.general.promptActions.delete"]',
          ) as HTMLElement
        ).click();
      });
      await act(async () => {
        (
          document.body.querySelector('[data-testid="confirm"]') as HTMLElement
        ).click();
      });
      await expect(confirm.result).rejects.toThrow();
      expect(setPrompts).not.toHaveBeenCalled();
      expect(
        document.body.querySelector('[data-testid="confirm-error"]')!
          .textContent,
      ).toBe('settings.general.promptActions.deleteFailed');
      expect(dispatch).not.toHaveBeenCalledWith(
        expect.objectContaining({
          payload: expect.objectContaining({ variant: 'destructive' }),
        }),
      );
    });

    it('removes the row once the delete succeeds', async () => {
      deletePrompt.mockReturnValue(json({ success: true }));
      const setPrompts = vi.fn();
      renderPrompts({ prompts: all, selectedPrompt: own, setPrompts });
      openPicker();
      await act(async () => {
        (
          row('Own prompt').querySelector(
            'button[aria-label="settings.general.promptActions.delete"]',
          ) as HTMLElement
        ).click();
      });
      await act(async () => {
        (
          document.body.querySelector('[data-testid="confirm"]') as HTMLElement
        ).click();
      });
      await expect(confirm.result).resolves.toBeUndefined();
      expect(setPrompts).toHaveBeenCalledWith(
        all.filter((p) => p.id !== 'own'),
      );
    });

    it('sends the loaded updated_at and reports a 409 as an edit conflict', async () => {
      getSinglePrompt.mockReturnValue(
        json({ content: 'Hello', updated_at: '2026-09-01T10:00:00Z' }),
      );
      updatePrompt.mockReturnValue(
        json({ success: false, code: 'stale_write' }, false, 409),
      );
      renderPrompts({ prompts: all, selectedPrompt: own });
      openPicker();
      await act(async () => {
        (row('Editor prompt').querySelector('button') as HTMLElement).click();
      });
      expect(lastModalProps().readOnly).toBe(false);
      await act(async () => lastModalProps().handleEditPrompt('ed', 'team'));
      expect(updatePrompt).toHaveBeenCalledWith(
        expect.objectContaining({
          id: 'ed',
          expected_updated_at: '2026-09-01T10:00:00Z',
        }),
        'test-token',
      );
      expect(dispatch).toHaveBeenCalledWith(
        expect.objectContaining({
          payload: {
            variant: 'destructive',
            message: 'settings.general.promptActions.editConflict',
          },
        }),
      );
    });
  });
});
