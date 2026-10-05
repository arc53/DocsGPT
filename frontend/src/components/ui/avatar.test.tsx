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

describe('Avatar icon tile', () => {
  it('is the muted icon square: bg-muted, muted icon, rounded-md', () => {
    const html = renderToStaticMarkup(
      <Avatar size="sm" shape="square" variant="icon">
        <svg />
      </Avatar>,
    );
    const host = document.createElement('div');
    host.innerHTML = html;
    const tile = host.firstElementChild as HTMLElement;
    expect(tile.className.split(' ')).toEqual(
      expect.arrayContaining([
        'bg-muted',
        'text-muted-foreground',
        'flex',
        'size-8',
        'shrink-0',
        'items-center',
        'justify-center',
        'rounded-md',
      ]),
    );
    expect(tile.getAttribute('data-variant')).toBe('icon');
  });

  it('has an xl size (48px) that rounds rounded-xl when square', () => {
    const html = renderToStaticMarkup(
      <Avatar size="xl" shape="square" variant="icon">
        <svg />
      </Avatar>,
    );
    const host = document.createElement('div');
    host.innerHTML = html;
    const classes = (host.firstElementChild as HTMLElement).className.split(
      ' ',
    );
    expect(classes).toContain('size-12');
    expect(classes).toContain('rounded-xl');
    expect(classes).not.toContain('rounded-md');
  });
});
