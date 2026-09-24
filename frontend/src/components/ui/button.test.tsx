import type React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Button, buttonVariants } from './button';

/** The class attribute of the rendered root element. */
function renderedClasses(element: React.ReactElement): string {
  const html = renderToStaticMarkup(element);
  return /class="([^"]*)"/.exec(html)?.[1] ?? '';
}

describe('Button variants', () => {
  it('renders a rectangular medium button by default', () => {
    const html = renderToStaticMarkup(<Button>Save</Button>);
    expect(html).toContain('rounded-md');
    expect(html).toContain('h-9');
    expect(html).toContain('data-shape="default"');
  });

  it('shape="pill" swaps the radius and widens the padding', () => {
    // Rendered classes go through cn(), which resolves the compound
    // variant's px-5 against the default size's px-4.
    const classes = renderedClasses(<Button shape="pill">Save</Button>);
    expect(classes).toContain('rounded-full');
    expect(classes).not.toContain('rounded-md');
    expect(classes).toContain('px-5');
    expect(classes).not.toMatch(/(^|\s)px-4(\s|$)/);
  });

  it('large pills get the widest padding', () => {
    const classes = buttonVariants({ shape: 'pill', size: 'lg' });
    expect(classes).toContain('px-6');
    expect(classes).toContain('h-10');
  });

  it('size="xs" is a compact text-xs button', () => {
    const classes = renderedClasses(<Button size="xs">Save</Button>);
    expect(classes).toContain('h-7');
    expect(classes).toContain('text-xs');
    expect(classes).not.toMatch(/(^|\s)text-sm(\s|$)/);
  });

  it('exposes muted and brand-outline variants', () => {
    expect(buttonVariants({ variant: 'ghost-muted' })).toContain(
      'text-muted-foreground',
    );
    expect(buttonVariants({ variant: 'outline-primary' })).toContain(
      'border-primary',
    );
  });

  it('variant="ghost-destructive" is a muted icon that warns red on hover', () => {
    const classes = buttonVariants({ variant: 'ghost-destructive' }).split(' ');
    expect(classes).toContain('text-muted-foreground');
    expect(classes).toContain('hover:text-destructive');
    expect(classes).toContain('hover:bg-accent');
    expect(classes).toContain('dark:hover:bg-accent/50');
  });

  it('size="inline" adds no height or padding, so a link sits mid-sentence', () => {
    const classes = buttonVariants({ variant: 'link', size: 'inline' }).split(
      ' ',
    );
    expect(classes).toContain('h-auto');
    expect(classes).toContain('p-0');
    expect(classes.some((c) => /^h-\d/.test(c))).toBe(false);
    expect(classes.some((c) => /^px-\d/.test(c))).toBe(false);
  });

  it('lets callers pass layout classes through', () => {
    const html = renderToStaticMarkup(
      <Button className="mt-4 w-full">Save</Button>,
    );
    expect(html).toContain('mt-4');
    expect(html).toContain('w-full');
  });

  it('variant="sidebar-item" is a full-width nav row, not a centred button', () => {
    const classes = renderedClasses(
      <Button variant="sidebar-item" aria-current="page">
        Settings
      </Button>,
    ).split(' ');
    for (const cls of [
      'hover:bg-sidebar-accent',
      'aria-[current=page]:bg-sidebar-accent',
      'justify-start',
      'gap-2.5',
      'pl-3',
      'pr-0',
      'rounded-full',
      'font-normal',
    ]) {
      expect(classes).toContain(cls);
    }
    // The default radius, centring and weight must not survive the merge.
    // (The size's px-4 may remain; pl-3/pr-0 are emitted after padding-inline
    // in Tailwind v4, so they win in CSS.)
    for (const cls of ['rounded-md', 'justify-center', 'font-medium']) {
      expect(classes).not.toContain(cls);
    }
  });

  it('variant="tab" is an underline tab: square, muted, with the active state on data-active', () => {
    const classes = renderedClasses(<Button variant="tab">My Files</Button>);
    expect(classes).toContain('rounded-none');
    expect(classes).not.toContain('rounded-md');
    expect(classes).toContain('border-b-2');
    expect(classes).toContain('border-transparent');
    expect(classes).toContain('text-muted-foreground');
    expect(classes).toContain('data-[active=true]:border-primary');
    expect(classes).toContain('data-[active=true]:text-foreground');
    expect(classes).not.toContain('hover:bg-accent');
  });

  it('variant="tab" size="inline" keeps a 4px gap above the underline', () => {
    const classes = renderedClasses(
      <Button variant="tab" size="inline">
        Logs
      </Button>,
    );
    expect(classes).toContain('h-auto');
    expect(classes).toContain('pb-1');
  });

  it('size="field" is the 42px form-row height shared with Input and SelectTrigger lg', () => {
    const classes = renderedClasses(<Button size="field">Add</Button>).split(
      ' ',
    );
    expect(classes).toContain('h-10.5');
    expect(classes).toContain('px-4');
    expect(classes).not.toContain('h-9');
  });

  it('a field pill starts its text 20px in, like the Input and Select pills', () => {
    const classes = renderedClasses(
      <Button variant="combobox" size="field" shape="pill">
        Select sources
      </Button>,
    ).split(' ');
    expect(classes).toContain('h-10.5');
    expect(classes).toContain('rounded-full');
    expect(classes).toContain('px-5');
    expect(classes).not.toContain('px-4');
  });

  it('variant="section-toggle" is a foreground title with a primary chevron and no ring of its own', () => {
    const classes = renderedClasses(
      <Button variant="section-toggle" size="sm">
        Advanced
      </Button>,
    ).split(' ');
    expect(classes).toContain('text-foreground');
    expect(classes).toContain('decoration-primary');
    expect(classes).toContain('hover:underline');
    // Rendered HTML escapes `&>`, so read this one off the variant string.
    expect(buttonVariants({ variant: 'section-toggle' }).split(' ')).toContain(
      '[&>svg]:text-primary',
    );
    // The host panel draws the focus ring, so the button's own is off.
    expect(classes).toContain('focus-visible:ring-0');
    expect(classes).not.toContain('focus-visible:ring-3');
    expect(classes).not.toContain('text-primary');
  });
});
