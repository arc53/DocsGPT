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

  const renderPrompts = () =>
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

  it('gives the prompt pill the 42px form-row height', () => {
    renderPrompts();
    const trigger = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Toggle prompt list"]',
    );
    expect(trigger?.className).toMatch(/(^|\s)h-10\.5(\s|$)/);
    expect(trigger?.className).toMatch(/(^|\s)items-stretch(\s|$)/);
    // The label no longer pads itself to height; it centres in the fixed pill.
    const label = trigger?.firstElementChild as HTMLElement | null;
    expect(label?.className).not.toMatch(/(^|\s)py-3(\s|$)/);
    expect(label?.className).toMatch(/(^|\s)pl-5(\s|$)/);
    expect(label?.className).toMatch(/(^|\s)items-center(\s|$)/);
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
      'button[aria-label="Toggle prompt list"]',
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
  });
});
