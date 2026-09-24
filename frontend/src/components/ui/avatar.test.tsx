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
      size: 'lg',
      shape: 'circle',
      variant: 'primary',
    });
    expect(classes).toContain('size-9');
    expect(classes).toContain('rounded-full');
    expect(classes).toContain('bg-primary/10');
    expect(classes).toContain('items-center');
  });

  it('renders children instead of the image when given', () => {
    const html = renderToStaticMarkup(
      <Avatar size="sm" shape="square" variant="muted">
        LK
      </Avatar>,
    );
    expect(html).toContain('LK');
    expect(html).not.toContain('<img');
    expect(html).toContain('rounded-md');
  });
});
