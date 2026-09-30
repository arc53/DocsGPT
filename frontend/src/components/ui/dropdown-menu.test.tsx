import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ChevronDown, Pencil, Trash2 } from 'lucide-react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Button } from './button';
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

  // A page header or toolbar: the trigger matches the icon buttons beside
  // 38px buttons on a plain surface, not a highlighted row.
  it('renders a 36px ghost-muted trigger with size="toolbar"', async () => {
    await render(
      <ActionMenu
        options={options()}
        triggerLabel="More actions"
        size="toolbar"
      />,
    );
    expect(trigger().getAttribute('data-variant')).toBe('ghost-muted');
    expect(trigger().getAttribute('data-size')).toBe('icon');
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

  it('draws a separator before an option that asks for one', async () => {
    await render(
      <ActionMenu
        options={[
          { label: 'Rename', onClick: vi.fn() },
          { label: 'Disconnect', onClick: vi.fn() },
          {
            label: 'Remove',
            onClick: vi.fn(),
            variant: 'destructive',
            separatorBefore: true,
          },
        ]}
        triggerLabel="Menu"
        open
      />,
    );
    const separators = document.querySelectorAll(
      '[data-slot="dropdown-menu-separator"]',
    );
    expect(separators).toHaveLength(1);
    expect(separators[0].nextElementSibling?.textContent).toBe('Remove');
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

describe('ActionMenu trigger', () => {
  it('renders a caller trigger instead of the three-dots button', async () => {
    await render(
      <ActionMenu
        options={options()}
        trigger={
          <Button type="button" shape="pill" data-testid="own">
            Actions
            <ChevronDown />
          </Button>
        }
      />,
    );
    const t = trigger();
    expect(t.getAttribute('data-testid')).toBe('own');
    expect(t.textContent).toBe('Actions');
    expect(t.getAttribute('data-variant')).toBe('default');
    expect(t.getAttribute('aria-haspopup')).toBe('menu');
    expect(t.hasAttribute('aria-label')).toBe(false);
    // No tooltip wraps a labelled trigger.
    expect(t.hasAttribute('data-state') && t.dataset.state).toBe('closed');
    expect(document.querySelector('[data-slot="tooltip-trigger"]')).toBeNull();
  });

  it('lets a trigger click bubble (it is not on a clickable card)', async () => {
    const parent = vi.fn();
    await render(
      <div onClick={parent}>
        <ActionMenu
          options={options()}
          trigger={<Button type="button">Actions</Button>}
        />
      </div>,
    );
    await act(async () => trigger().click());
    expect(parent).toHaveBeenCalled();
  });

  it('takes an element icon (a ConnectorIcon) and a menu width', async () => {
    await render(
      <ActionMenu
        open
        options={[
          {
            label: 'GitHub',
            icon: <svg data-testid="logo" className="size-4" />,
            onClick: vi.fn(),
          },
        ]}
        trigger={<Button type="button">Add</Button>}
        menuWidth="lg"
      />,
    );
    expect(items()[0].querySelector('[data-testid="logo"]')).not.toBeNull();
    const content = document.querySelector<HTMLElement>(
      '[data-slot="dropdown-menu-content"]',
    )!;
    expect(content.className).toContain('min-w-48');
    expect(content.className).not.toContain('min-w-36');
  });
});
