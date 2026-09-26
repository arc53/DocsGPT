import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({
  useSelector: () => 'test-token',
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../api/services/userService', () => ({ default: {} }));
vi.mock('../teams/ShareToTeamModal', () => ({ default: () => null }));
vi.mock('../preferences/PromptsModal', () => ({ default: () => null }));
vi.mock('../modals/ConfirmationModal', () => ({ default: () => null }));

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
    expect(edit?.parentElement).toBe(
      trigger?.closest('[data-slot="form-field"]')?.parentElement,
    );
  });

  it('labels the picker with a floating label on Settings, named by it', () => {
    renderPrompts();
    const trigger = container.querySelector<HTMLButtonElement>(
      'button[role="combobox"]',
    )!;
    const label = container.querySelector<HTMLLabelElement>(
      '[data-slot="form-field-label"]',
    )!;
    expect(label.textContent).toBe('settings.general.prompt');
    expect(label.htmlFor).toBe(trigger.id);
    expect(label.className).toContain('bg-background');
    expect(trigger.hasAttribute('aria-label')).toBe(false);
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

  it('sizes the Add button to the field row', () => {
    renderPrompts();
    const add = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[data-slot="button"]'),
    ).find((b) => b.textContent === 'settings.general.add');
    expect(add?.getAttribute('data-size')).toBe('field');
    expect(add?.getAttribute('data-shape')).toBe('pill');
    expect(add?.getAttribute('data-variant')).toBe('default');
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
});
