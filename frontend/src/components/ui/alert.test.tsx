import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { Alert, AlertDescription, AlertTitle } from './alert';
import { TooltipProvider } from './tooltip';

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

const alertRole = () => container.firstElementChild!.getAttribute('role');

describe('Alert', () => {
  it.each(['destructive', 'warning', 'info'] as const)(
    'announces %s assertively',
    async (variant) => {
      await render(
        <Alert variant={variant}>
          <AlertDescription>Notice</AlertDescription>
        </Alert>,
      );
      expect(alertRole()).toBe('alert');
    },
  );

  it('announces success politely', async () => {
    await render(
      <Alert variant="success">
        <AlertDescription>Done</AlertDescription>
      </Alert>,
    );
    expect(alertRole()).toBe('status');
  });

  it('lets the caller override the role', async () => {
    await render(<Alert variant="destructive" role="status" />);
    expect(alertRole()).toBe('status');
  });

  it('marks its parts with data-slot and the variant', async () => {
    await render(
      <Alert variant="warning">
        <AlertTitle>Heads up</AlertTitle>
        <AlertDescription>Notice</AlertDescription>
      </Alert>,
    );
    const alert = document.querySelector('[data-slot="alert"]')!;
    expect(alert.getAttribute('data-variant')).toBe('warning');
    expect(alert.querySelector('[data-slot="alert-title"]')).not.toBeNull();
    expect(
      alert.querySelector('[data-slot="alert-description"]'),
    ).not.toBeNull();
  });
});

describe('Alert layout', () => {
  const classesOf = async (element: React.ReactElement) => {
    await render(element);
    return container.firstElementChild!.className.split(' ');
  };

  it('puts the icon in its own column, centred on the text block', async () => {
    const classes = await classesOf(
      <Alert variant="destructive">
        <AlertDescription>Failed</AlertDescription>
      </Alert>,
    );
    expect(classes).toEqual(
      expect.arrayContaining([
        'grid',
        'has-[>svg]:grid-cols-[calc(var(--spacing)*4)_1fr]',
        '[&>svg]:self-center',
        '[&>:not(svg)]:col-start-2',
      ]),
    );
    expect(classes).not.toContain('[&>svg]:absolute');
  });

  it('takes the icon colour from the text, so it always matches', async () => {
    const classes = await classesOf(<Alert variant="destructive" />);
    expect(classes).toContain('[&>svg]:text-current');
    expect(classes.some((c) => c.startsWith('[&>svg]:text-destructive'))).toBe(
      false,
    );
  });

  it('spans the icon across a title and its description', async () => {
    const classes = await classesOf(<Alert variant="warning" />);
    expect(classes).toContain(
      'has-[>[data-slot=alert-title]]:[&>svg]:row-span-2',
    );
  });
});

describe('Alert surface', () => {
  it('has 14px corners, like a popover', async () => {
    await render(
      <Alert variant="warning">
        <AlertDescription>Notice</AlertDescription>
      </Alert>,
    );
    const classes = container.firstElementChild!.className.split(' ');
    expect(classes).toContain('rounded-xl');
    expect(classes).not.toContain('rounded-lg');
  });
});

describe('Alert onClose', () => {
  const closeButton = () =>
    container.querySelector<HTMLButtonElement>('button[aria-label="close"]');

  it('draws no close button unless onClose is passed', async () => {
    await render(
      <Alert variant="destructive">
        <AlertTitle>Unable to save</AlertTitle>
      </Alert>,
    );
    expect(closeButton()).toBeNull();
    expect(container.firstElementChild!.className.split(' ')).not.toContain(
      'pr-10',
    );
  });

  it('puts a ghost X in the top-right corner and pads the text clear of it', async () => {
    const onClose = vi.fn();
    await render(
      <TooltipProvider>
        <Alert variant="destructive" onClose={onClose}>
          <AlertTitle>Unable to save</AlertTitle>
          <AlertDescription>Two nodes have no model.</AlertDescription>
        </Alert>
      </TooltipProvider>,
    );
    const alert = container.querySelector<HTMLElement>('[data-slot="alert"]')!;
    expect(alert.className.split(' ')).toContain('pr-10');
    const button = closeButton()!;
    expect(button).not.toBeNull();
    expect(alert.contains(button)).toBe(true);
    expect(button.dataset.variant).toBe('ghost');
    expect(button.dataset.size).toBe('icon-xs');
    const corner = button.closest('[data-slot="alert-close"]')!;
    expect(corner.className.split(' ')).toEqual(
      expect.arrayContaining(['absolute', 'top-2.5', 'right-2.5']),
    );
    await act(async () => button.click());
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('Alert icon', () => {
  const icons = () =>
    Array.from(container.firstElementChild!.querySelectorAll(':scope > svg'));
  const defaultIcon = () =>
    container.firstElementChild!.querySelector<SVGElement>(
      ':scope > [data-slot="alert-icon"]',
    );

  it.each([
    ['destructive', 'lucide-circle-alert'],
    ['warning', 'lucide-triangle-alert'],
    ['success', 'lucide-circle-check'],
    ['info', 'lucide-info'],
  ] as const)('draws %s with its default icon', async (variant, cls) => {
    await render(
      <Alert variant={variant}>
        <AlertDescription>Notice</AlertDescription>
      </Alert>,
    );
    const icon = defaultIcon();
    expect(icon).not.toBeNull();
    expect(icon!.getAttribute('class')).toContain(cls);
    expect(icon!.getAttribute('aria-hidden')).toBe('true');
    // First child, so the grid puts it in the icon column.
    expect(container.firstElementChild!.firstElementChild).toBe(icon);
  });

  it('has only status variants, and one is required', () => {
    // Type-level: tsc fails if default or neutral come back, or if variant
    // turns optional again. Nothing renders.
    const removed = [
      // @ts-expect-error default was removed (no app use)
      <Alert key="default" variant="default" />,
      // @ts-expect-error neutral was removed (no app use)
      <Alert key="neutral" variant="neutral" />,
      // @ts-expect-error variant is required
      <Alert key="none" />,
    ];
    expect(removed).toHaveLength(3);
  });

  it('icon overrides the default', async () => {
    const Shield = (props: React.SVGProps<SVGSVGElement>) => (
      <svg data-testid="shield" {...props} />
    );
    await render(
      <Alert variant="destructive" icon={Shield}>
        <AlertDescription>Full access</AlertDescription>
      </Alert>,
    );
    expect(icons()).toHaveLength(1);
    expect(icons()[0].getAttribute('data-testid')).toBe('shield');
    expect(icons()[0].getAttribute('data-slot')).toBe('alert-icon');
    expect(icons()[0].getAttribute('aria-hidden')).toBe('true');
  });

  it('icon replaces the info icon', async () => {
    const Lock = (props: React.SVGProps<SVGSVGElement>) => (
      <svg data-testid="lock" {...props} />
    );
    await render(
      <Alert variant="info" icon={Lock}>
        <AlertDescription>View only</AlertDescription>
      </Alert>,
    );
    expect(defaultIcon()?.getAttribute('data-testid')).toBe('lock');
  });

  it('icon={null} drops it', async () => {
    await render(
      <Alert variant="destructive" icon={null}>
        <AlertDescription>TimeoutError</AlertDescription>
      </Alert>,
    );
    expect(icons()).toEqual([]);
  });

  it('always shows its icon: no fallback that hides it beside another svg', async () => {
    await render(
      <Alert variant="destructive">
        <AlertDescription>Failed</AlertDescription>
      </Alert>,
    );
    const icon = defaultIcon()!;
    expect(icon.getAttribute('class')).not.toContain('hidden');
  });
});
