import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Pencil, Trash2 } from 'lucide-react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ActionMenu, type MenuOption } from './dropdown-menu';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

const render = async (element: React.ReactElement) => {
  await act(async () => root.render(element));
};

const options = (onEdit = vi.fn(), onDelete = vi.fn()): MenuOption[] => [
  { icon: Pencil, label: 'Edit', onClick: onEdit },
  { icon: Trash2, label: 'Delete', variant: 'destructive', onClick: onDelete },
];

const trigger = () =>
  document.querySelector<HTMLButtonElement>(
    '[data-slot="dropdown-menu-trigger"]',
  )!;
const items = () =>
  Array.from(
    document.querySelectorAll<HTMLElement>('[data-slot="dropdown-menu-item"]'),
  );

describe('ActionMenu', () => {
  it('renders a labelled ghost-on-accent icon trigger', async () => {
    await render(
      <ActionMenu options={options()} triggerLabel="Agent actions" />,
    );
    expect(trigger().getAttribute('aria-label')).toBe('Agent actions');
    expect(trigger().getAttribute('data-variant')).toBe('ghost-on-accent');
    expect(trigger().getAttribute('data-size')).toBe('icon-xs');
    expect(trigger().querySelector('svg')).not.toBeNull();
  });

  it('passes layout classes, disabled and a test id to the trigger', async () => {
    await render(
      <ActionMenu
        options={options()}
        triggerLabel="Menu"
        className="absolute top-3 right-3"
        triggerTestId="menu-button-1"
        disabled
      />,
    );
    expect(trigger().className).toContain('top-3');
    expect(trigger().disabled).toBe(true);
    expect(trigger().getAttribute('data-testid')).toBe('menu-button-1');
  });

  it('keeps a trigger click from reaching a clickable parent', async () => {
    const onCard = vi.fn();
    await render(
      <div onClick={onCard}>
        <ActionMenu options={options()} triggerLabel="Menu" />
      </div>,
    );
    await act(async () => trigger().click());
    expect(onCard).not.toHaveBeenCalled();
  });

  it('renders one item per option with its icon and variant', async () => {
    await render(<ActionMenu options={options()} triggerLabel="Menu" open />);
    const [edit, del] = items();
    expect(items()).toHaveLength(2);
    expect(edit.textContent).toBe('Edit');
    expect(edit.querySelector('svg')).not.toBeNull();
    expect(del.getAttribute('data-variant')).toBe('destructive');
  });

  it('calls onClick on select without the click reaching the parent', async () => {
    const onCard = vi.fn();
    const onEdit = vi.fn();
    await render(
      <div onClick={onCard}>
        <ActionMenu options={options(onEdit)} triggerLabel="Menu" open />
      </div>,
    );
    await act(async () => items()[0].click());
    expect(onEdit).toHaveBeenCalledTimes(1);
    expect(onCard).not.toHaveBeenCalled();
  });

  it('marks a disabled option', async () => {
    await render(
      <ActionMenu
        options={[{ label: 'Export', onClick: vi.fn(), disabled: true }]}
        triggerLabel="Menu"
        open
      />,
    );
    expect(items()[0].hasAttribute('data-disabled')).toBe(true);
  });
});
