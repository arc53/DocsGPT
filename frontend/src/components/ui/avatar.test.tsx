import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Avatar, avatarVariants } from './avatar';

describe('Avatar variants', () => {
  it('adds no sizing or radius unless asked, so image avatars are unchanged', () => {
    const html = renderToStaticMarkup(<Avatar src="/a.png" />);
    expect(html).toContain('class="shrink-0"');
  });

  it('sizes and shapes the initials box', () => {
    const classes = avatarVariants({
      size: 'default',
      shape: 'circle',
      variant: 'primary',
    });
    expect(classes).toContain('size-9');
    expect(classes).toContain('rounded-full');
    expect(classes).toContain('bg-secondary');
    expect(classes).toContain('text-secondary-foreground');
    expect(classes).not.toContain('dark:bg-primary/20');
    expect(classes).toContain('items-center');
  });

  it('renders children instead of the image when given', () => {
    const html = renderToStaticMarkup(
      <Avatar size="xs" shape="square" variant="muted">
        LK
      </Avatar>,
    );
    expect(html).toContain('LK');
    expect(html).not.toContain('<img');
    expect(html).toContain('rounded-md');
  });
});

describe('Avatar sizes', () => {
  it("shares Button's size names at the same pixels", () => {
    expect(avatarVariants({ size: 'xs' })).toContain('size-7');
    expect(avatarVariants({ size: 'sm' })).toContain('size-8');
    expect(avatarVariants({ size: 'default' })).toContain('size-9');
    expect(avatarVariants({ size: 'lg' })).toContain('size-10');
  });
});
