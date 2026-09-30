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
  it.each(['default', 'destructive', 'warning', 'info'] as const)(
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
        <svg />
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

  it('variant="neutral" is the quiet default box', async () => {
    await render(
      <Alert variant="neutral">
        <AlertDescription>Not evaluated</AlertDescription>
      </Alert>,
    );
    const el = container.firstElementChild as HTMLElement;
    expect(el.dataset.variant).toBe('neutral');
    expect(el.className).toContain('bg-background');
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
