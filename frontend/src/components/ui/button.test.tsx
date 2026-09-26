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
    expect(classes).not.toContain('dark:hover:bg-accent/50');
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

  it('size="field" is the 38px form-row height shared with Input and SelectTrigger field', () => {
    const classes = renderedClasses(<Button size="field">Add</Button>).split(
      ' ',
    );
    expect(classes).toContain('h-9.5');
    expect(classes).toContain('px-4');
    expect(classes).not.toContain('h-9');
  });

  it('a field pill starts its text 20px in, like the Input and Select pills', () => {
    const classes = renderedClasses(
      <Button variant="combobox" size="field" shape="pill">
        Select sources
      </Button>,
    ).split(' ');
    expect(classes).toContain('h-9.5');
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

  it('variant="ghost-on-accent" hovers with a foreground tint, not accent', () => {
    // It sits on rows that are already bg-accent, where an accent hover
    // would be invisible.
    const classes = buttonVariants({ variant: 'ghost-on-accent' }).split(' ');
    expect(classes).toContain('text-muted-foreground');
    expect(classes).toContain('hover:text-foreground');
    expect(classes).toContain('hover:bg-foreground/15');
    expect(classes).toContain('dark:hover:bg-foreground/20');
    expect(classes).not.toContain('hover:bg-accent');
  });

  it('variant="ghost-destructive-on-accent" hovers with a destructive tint', () => {
    const classes = buttonVariants({
      variant: 'ghost-destructive-on-accent',
    }).split(' ');
    expect(classes).toContain('text-muted-foreground');
    expect(classes).toContain('hover:text-destructive');
    expect(classes).toContain('hover:bg-destructive/15');
    expect(classes).toContain('dark:hover:bg-destructive/20');
    expect(classes).not.toContain('hover:bg-accent');
  });
});

describe('Button loading', () => {
  const parse = (element: React.ReactElement) => {
    const host = document.createElement('div');
    host.innerHTML = renderToStaticMarkup(element);
    return host.firstElementChild as HTMLButtonElement;
  };

  it('disables the button and marks it busy', () => {
    const button = parse(<Button loading>Save</Button>);
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('aria-busy')).toBe('true');
    expect(button.hasAttribute('data-loading')).toBe(true);
  });

  it('keeps the label in place, hidden, so the width holds', () => {
    const button = parse(
      <Button loading size="lg" shape="pill">
        Create token
      </Button>,
    );
    const label = button.querySelector('span.invisible')!;
    expect(label.textContent).toBe('Create token');
    expect(label.className).toContain('contents');
    expect(button.className).toContain('relative');
  });

  it('centres a 16px spinner over the label', () => {
    const button = parse(<Button loading>Save</Button>);
    const overlay = button.querySelector('span.absolute')!;
    expect(overlay.className).toContain('inset-0');
    const spinner = overlay.querySelector('[data-slot="spinner"]')!;
    expect(spinner.getAttribute('data-size')).toBe('xs');
    expect(spinner.className).toContain('size-4');
    expect(spinner.className).not.toContain('size-5');
  });

  it('renders plainly when not loading', () => {
    const button = parse(<Button loading={false}>Save</Button>);
    expect(button.disabled).toBe(false);
    expect(button.hasAttribute('aria-busy')).toBe(false);
    expect(button.innerHTML).toBe('Save');
  });
});

describe('Button loading with an icon', () => {
  it('keeps the icon padding while the label is wrapped', () => {
    const html = renderToStaticMarkup(
      <Button loading size="lg" shape="pill">
        <svg />
        Download
      </Button>,
    );
    const host = document.createElement('div');
    host.innerHTML = html;
    const button = host.firstElementChild as HTMLButtonElement;
    // The label wrapper is marked, and every icon-padding rule also matches an
    // svg one level down inside it, so the width doesn't grow.
    expect(
      button.querySelector('[data-slot="button-label"]')?.querySelector('svg'),
    ).not.toBeNull();
    const iconRules = button.className
      .split(' ')
      .filter((c) => c.startsWith('has-['));
    expect(iconRules.length).toBeGreaterThan(0);
    for (const rule of iconRules) {
      expect(rule).toContain('>[data-slot=button-label]>svg');
    }
  });
});

describe('Button dark hover', () => {
  it.each(['ghost', 'ghost-muted', 'ghost-destructive'] as const)(
    '%s hovers to solid accent in both themes',
    (variant) => {
      const classes = buttonVariants({ variant }).split(' ');
      expect(classes).toContain('hover:bg-accent');
      expect(classes).not.toContain('dark:hover:bg-accent/50');
    },
  );
});

describe('Button combobox text size', () => {
  it.each(['default', 'field', 'lg'] as const)(
    'combobox %s is 16px on phones, 14px from md',
    (size) => {
      const classes = buttonVariants({ variant: 'combobox', size }).split(' ');
      expect(classes).toEqual(
        expect.arrayContaining(['text-base', 'md:text-sm']),
      );
    },
  );

  it('combobox sm stays 14px', () => {
    const classes = buttonVariants({ variant: 'combobox', size: 'sm' }).split(
      ' ',
    );
    expect(classes).not.toContain('text-base');
  });
});

describe('Button size="icon"', () => {
  it('draws an unsized glyph at 20px in its 36px square', () => {
    const classes = buttonVariants({ size: 'icon' });
    expect(classes).toContain('size-9');
    expect(classes).toContain("[&_svg:not([class*='size-'])]:size-5");
    const html = renderToStaticMarkup(<Button size="icon">x</Button>);
    expect(html).not.toContain(
      '[&amp;_svg:not([class*=&#x27;size-&#x27;])]:size-4',
    );
  });
});
