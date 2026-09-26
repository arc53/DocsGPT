import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Input, inputVariants } from './input';

describe('Input variants', () => {
  it('keeps the 38px form-row rectangular field by default', () => {
    const classes = inputVariants();
    expect(classes).toContain('h-9.5');
    expect(classes).toContain('rounded-md');
  });

  it('size="sm" is a compact field', () => {
    const classes = inputVariants({ size: 'sm' });
    expect(classes).toContain('h-8');
    expect(classes).toContain('px-2');
    expect(classes).not.toMatch(/\bh-9\.5\b/);
  });

  it('shape="pill" with size="lg" is the chat-style field', () => {
    const classes = inputVariants({ size: 'lg', shape: 'pill' });
    expect(classes).toContain('rounded-full');
    expect(classes).toContain('h-12');
    expect(classes).toContain('px-5');
  });

  it('a default-size pill starts its text 20px in, like the Select pill', () => {
    const html = renderToStaticMarkup(<Input shape="pill" />);
    const classes = (/class="([^"]*)"/.exec(html)?.[1] ?? '').split(' ');
    expect(classes).toContain('h-9.5');
    expect(classes).toContain('px-5');
    expect(classes).not.toContain('px-3');
  });

  it('an inset icon still pads the left of a default pill', () => {
    const html = renderToStaticMarkup(
      <Input shape="pill" leftIcon={<svg />} placeholder="Search" />,
    );
    const classes = (/<input[^>]*class="([^"]*)"/.exec(html)?.[1] ?? '').split(
      ' ',
    );
    expect(classes).toContain('pl-10');
    expect(classes).toContain('px-5');
  });

  it('moves the floating label to match the field height', () => {
    const small = renderToStaticMarkup(<Input size="sm" label="Name" />);
    expect(small).toContain('peer-placeholder-shown:top-1.5');
    const large = renderToStaticMarkup(<Input size="lg" label="Name" />);
    expect(large).toContain('peer-placeholder-shown:top-3.5');
  });

  it('does not leak the variant props onto the DOM element', () => {
    const html = renderToStaticMarkup(<Input size="sm" shape="pill" />);
    expect(html).toContain('data-size="sm"');
    expect(html).not.toMatch(/\ssize="sm"/);
    expect(html).not.toMatch(/\sshape="pill"/);
  });

  it('paints the floating label notch on the card surface by default', () => {
    const html = renderToStaticMarkup(<Input label="Name" />);
    expect(html).toMatch(/<label[^>]*class="[^"]*\bbg-card\b/);
  });

  it('labelSurface matches the notch to the surface behind the field', () => {
    const page = renderToStaticMarkup(
      <Input label="Search" labelSurface="background" />,
    );
    expect(page).toMatch(/<label[^>]*class="[^"]*\bbg-background\b/);
    expect(page).not.toMatch(/<label[^>]*class="[^"]*\bbg-card\b/);
    const muted = renderToStaticMarkup(
      <Input label="Search" labelSurface="muted" />,
    );
    expect(muted).toMatch(/<label[^>]*class="[^"]*\bbg-muted\b/);
    expect(muted).not.toMatch(/\slabelSurface=/i);
  });

  it('variant="filled" gives the field a card fill on a muted panel', () => {
    const html = renderToStaticMarkup(<Input variant="filled" />);
    const classes = (html.match(/class="([^"]*)"/)?.[1] ?? '').split(' ');
    expect(classes).toContain('bg-card');
    expect(classes).not.toContain('bg-transparent');
    expect(html).toContain('data-variant="filled"');
  });

  it('variant="bare" drops the field chrome so the host frames it', () => {
    const html = renderToStaticMarkup(<Input variant="bare" />);
    const classes = /class="([^"]*)"/.exec(html)?.[1].split(' ') ?? [];
    for (const cls of [
      'border-0',
      'rounded-none',
      'p-0',
      'h-auto',
      'shadow-none',
      'bg-transparent',
      'text-sm',
      'focus-visible:ring-0',
    ]) {
      expect(classes).toContain(cls);
    }
    for (const cls of ['h-9.5', 'px-3', 'shadow-xs', 'rounded-md', 'border']) {
      expect(classes).not.toContain(cls);
    }
    expect(html).toContain('data-variant="bare"');
  });

  it('renders leftIcon inside the field without a floating label', () => {
    const html = renderToStaticMarkup(
      <Input leftIcon={<svg data-testid="icon" />} placeholder="Search" />,
    );
    expect(html).toContain('data-testid="icon"');
    expect(html).toMatch(/<input[^>]*class="[^"]*\bpl-10\b/);
    expect(html).not.toContain('<label');
    // No label, so the real placeholder stays visible.
    expect(html).toContain('placeholder="Search"');
    expect(html).not.toContain('placeholder:text-transparent');
  });

  it('keeps the bare input when there is neither a label nor an icon', () => {
    const html = renderToStaticMarkup(<Input />);
    expect(html.startsWith('<input')).toBe(true);
  });

  it('keeps the bordered field by default', () => {
    const html = renderToStaticMarkup(<Input />);
    expect(html).toContain('data-variant="default"');
    expect(html).toContain('shadow-xs');
  });
});

describe('Input field size and disabled state', () => {
  it('size="field" is the 38px form-row height, like Button field', () => {
    const classes = inputVariants({ size: 'field' });
    expect(classes).toContain('h-9.5');
    expect(classes).toBe(inputVariants({ size: 'default' }));
  });

  it('a field pill pads px-5 like the default pill', () => {
    const html = renderToStaticMarkup(<Input size="field" shape="pill" />);
    const classes = (/class="([^"]*)"/.exec(html)?.[1] ?? '').split(' ');
    expect(classes).toContain('px-5');
    expect(html).toContain('data-size="field"');
  });

  it('shows the not-allowed cursor while disabled', () => {
    const classes = inputVariants().split(' ');
    expect(classes).toContain('disabled:cursor-not-allowed');
    // pointer-events-none would hide the cursor behind the field.
    expect(classes).not.toContain('disabled:pointer-events-none');
  });
});
