import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { Alert, AlertDescription, AlertTitle } from './alert';

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
