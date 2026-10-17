import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { Badge, badgeVariants } from './badge';

describe('Badge', () => {
  it('is a soft brand pill by default', () => {
    const html = renderToStaticMarkup(<Badge>Beta</Badge>);
    expect(html).toContain('rounded-full');
    expect(html).toContain('bg-secondary');
    expect(html).toContain('text-secondary-foreground');
    expect(html).not.toContain('dark:bg-primary/20');
    expect(html).toContain('data-variant="default"');
  });

  it.each([
    ['success', 'text-success'],
    ['warning', 'text-warning'],
    ['destructive', 'text-destructive'],
    ['info', 'text-info'],
    ['neutral', 'text-foreground'],
  ] as const)('variant %s uses its semantic token', (variant, cls) => {
    expect(badgeVariants({ variant })).toContain(cls);
  });

  it('never uses raw palette colours', () => {
    for (const variant of [
      'default',
      'neutral',
      'success',
      'warning',
      'destructive',
      'info',
      'outline',
    ] as const) {
      expect(badgeVariants({ variant })).not.toMatch(
        /\b(bg|text|border)-(red|green|amber|yellow|blue|gray|purple)-\d+/,
      );
    }
  });
});

describe('Badge neutral', () => {
  it('reads foreground on its grey tint (muted text is under 4.5:1 there)', () => {
    const classes = badgeVariants({ variant: 'neutral' }).split(' ');
    expect(classes).toContain('bg-muted-foreground/15');
    expect(classes).toContain('text-foreground');
    expect(classes).not.toContain('text-muted-foreground');
  });
});

describe('Badge status fills', () => {
  it.each(['success', 'warning', 'destructive', 'info'] as const)(
    '%s is /10 in both themes, like Alert',
    (variant) => {
      const classes = badgeVariants({ variant }).split(' ');
      expect(classes).toContain(`bg-${variant}/10`);
      expect(classes.some((c) => c.startsWith('dark:bg-'))).toBe(false);
    },
  );
});

describe('Badge onRemove', () => {
  it('draws a named remove button with a 24px target', async () => {
    const { act } = await import('react');
    const { createRoot } = await import('react-dom/client');
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    const onRemove = vi.fn();
    await act(async () =>
      root.render(
        <Badge onRemove={onRemove} removeLabel="Show all connectors">
          Syncs into Knowledge
        </Badge>,
      ),
    );
    const badge = host.querySelector<HTMLElement>('[data-slot="badge"]')!;
    expect(badge.className.split(' ')).toContain('pr-1.5');
    const button = badge.querySelector<HTMLButtonElement>('button')!;
    expect(button.type).toBe('button');
    expect(button.getAttribute('aria-label')).toBe('Show all connectors');
    expect(button.dataset.slot).toBe('badge-remove');
    const classes = button.className.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining([
        'relative',
        'size-4',
        'rounded-full',
        'after:absolute',
        'after:-inset-1',
        'hover:bg-primary/15',
        'focus-visible:ring-3',
      ]),
    );
    const icon = button.querySelector('svg')!;
    expect(icon.getAttribute('class')).toContain('size-3');
    expect(icon.getAttribute('aria-hidden')).toBe('true');
    await act(async () => button.click());
    expect(onRemove).toHaveBeenCalledTimes(1);
    await act(async () => root.unmount());
    host.remove();
  });

  it('has no button and keeps px-2 without onRemove', () => {
    const html = renderToStaticMarkup(<Badge>Beta</Badge>);
    expect(html).not.toContain('<button');
    expect(html).not.toContain('pr-1.5');
  });
});
