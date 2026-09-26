import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

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
    ['neutral', 'text-muted-foreground'],
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
