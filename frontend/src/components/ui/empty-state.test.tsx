import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { Monitor } from 'lucide-react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { EmptyState } from './empty-state';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('EmptyState', () => {
  it('renders both theme illustrations at 128px by default', () => {
    const html = renderToStaticMarkup(<EmptyState title="No sources" />);
    expect(html).toContain('py-12');
    expect(html).toContain('size-32');
    expect(html).toContain('dark:hidden');
    expect(html).toContain('hidden dark:block');
    expect(html).toContain('text-muted-foreground text-lg');
    expect(html).not.toContain('role="alert"');
  });

  it('shrinks the art and padding at sm and xs', () => {
    expect(renderToStaticMarkup(<EmptyState size="sm" title="x" />)).toContain(
      'size-24',
    );
    const xs = renderToStaticMarkup(<EmptyState size="xs" title="x" />);
    expect(xs).toContain('size-16');
    expect(xs).toContain('py-8');
  });

  it('drops the art with illustration="none"', () => {
    const html = renderToStaticMarkup(
      <EmptyState illustration="none" title="No results" />,
    );
    expect(html).not.toContain('<svg');
  });

  it('draws a muted 32px icon in place of the art', () => {
    const html = renderToStaticMarkup(
      <EmptyState icon={Monitor} title="Open on a larger screen" />,
    );
    expect(html).toContain('lucide-monitor');
    expect(html).toContain('text-muted-foreground mb-3 size-8');
    expect(html).not.toContain('size-32');
  });

  // A page whose only content is the empty state needs it as its heading.
  it('draws the title as a heading with titleAs, keeping its look', () => {
    const html = renderToStaticMarkup(
      <EmptyState titleAs="h1" illustration="none" title="Page not found" />,
    );
    expect(html).toContain(
      '<h1 class="text-muted-foreground text-lg">Page not found</h1>',
    );
  });

  it('keeps the red alert icon over a passed icon', () => {
    const html = renderToStaticMarkup(
      <EmptyState tone="destructive" icon={Monitor} title="Failed" />,
    );
    expect(html).toContain('lucide-circle-alert');
    expect(html).not.toContain('lucide-monitor');
  });

  it('turns red and announces itself with tone="destructive"', () => {
    const html = renderToStaticMarkup(
      <EmptyState
        tone="destructive"
        size="sm"
        illustration="none"
        title="Failed to load"
        action={<button type="button">Retry</button>}
      />,
    );
    expect(html).toContain('role="alert"');
    expect(html).toContain('text-destructive mb-3 size-8');
    expect(html).toContain('text-destructive text-base');
    expect(html).not.toContain('text-muted-foreground text-base');
    expect(html).toContain('Retry');
  });

  it('keeps the description in plain muted-foreground', () => {
    const html = renderToStaticMarkup(<EmptyState title="t" description="d" />);
    expect(html).toContain('text-muted-foreground mt-1 max-w-sm text-sm');
    expect(html).not.toContain('/70');
  });

  it('onRetry draws the outline sm pill Retry in the action slot', () => {
    const onRetry = vi.fn();
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => {
      root.render(
        <EmptyState tone="destructive" title="Failed" onRetry={onRetry} />,
      );
    });
    const button = host.querySelector<HTMLButtonElement>('button')!;
    expect(button.textContent).toBe('retry');
    expect(button.type).toBe('button');
    expect(button.dataset.variant).toBe('outline');
    expect(button.dataset.size).toBe('sm');
    expect(button.dataset.shape).toBe('pill');
    expect(button.parentElement!.className).toContain('mt-4');
    act(() => button.click());
    expect(onRetry).toHaveBeenCalledOnce();
    act(() => root.unmount());
    host.remove();
  });

  it('renders an action and onRetry side by side', () => {
    const html = renderToStaticMarkup(
      <EmptyState
        title="Failed"
        action={<a href="/help">Help</a>}
        onRetry={() => undefined}
      />,
    );
    expect(html).toContain('Help');
    expect(html).toContain('>retry</button>');
    expect(html).toContain(
      'mt-4 flex flex-wrap items-center justify-center gap-2',
    );
  });

  it('keeps a lone action in the plain slot', () => {
    const html = renderToStaticMarkup(
      <EmptyState title="t" action={<button type="button">Add</button>} />,
    );
    expect(html).toContain('<div class="mt-4"><button');
  });
});
