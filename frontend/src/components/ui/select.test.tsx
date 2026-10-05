import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';

import { Select, SelectContent, SelectItem, SelectTrigger } from './select';

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let host: HTMLDivElement | null = null;

afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  root = null;
  host = null;
});

describe('SelectItem', () => {
  it('fills the highlighted item, so keyboard navigation is visible', () => {
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => {
      root!.render(
        <Select open value="a">
          <SelectTrigger aria-label="Rows">a</SelectTrigger>
          <SelectContent>
            <SelectItem value="a">A</SelectItem>
          </SelectContent>
        </Select>,
      );
    });
    const item = document.querySelector('[data-slot="select-item"]');
    expect(item).not.toBeNull();
    // Radix sets data-highlighted on pointer hover and on arrow-key focus alike.
    expect(item!.className).toContain('data-highlighted:bg-accent');
    expect(item!.className).toContain(
      'data-highlighted:text-accent-foreground',
    );
    expect(item!.className).not.toContain('data-highlighted:bg-muted');
  });
});

describe('SelectTrigger sizes', () => {
  const trigger = (props: Parameters<typeof SelectTrigger>[0]) => {
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => {
      root!.render(
        <Select value="a">
          <SelectTrigger aria-label="Retriever" {...props}>
            a
          </SelectTrigger>
        </Select>,
      );
    });
    return document.querySelector<HTMLElement>('[data-slot="select-trigger"]')!;
  };

  it('exposes its variant as a data attribute', () => {
    expect(trigger({}).dataset.variant).toBe('default');
  });

  it('defaults to field, the 38px form-row height', () => {
    const el = trigger({});
    expect(el.dataset.size).toBe('field');
    const classes = el.className.split(' ');
    expect(classes).toContain('h-9.5');
    expect(classes).not.toContain('h-9');
  });

  it('size="field" is the 38px form-row height, like Button field', () => {
    const el = trigger({ size: 'field' });
    expect(el.dataset.size).toBe('field');
    expect(el.className.split(' ')).toContain('h-9.5');
  });

  it('has no 36px default size', () => {
    // @ts-expect-error size="default" is gone
    const classes = trigger({ size: 'default' }).className.split(' ');
    expect(classes).not.toContain('h-9');
  });

  it('has no ghost variant', () => {
    // @ts-expect-error variant="ghost" is gone
    expect(trigger({ variant: 'ghost' }).className).not.toContain(
      'data-[state=open]:bg-muted',
    );
  });

  it('a field pill starts its text 21px in (px-5)', () => {
    const classes = trigger({ shape: 'pill' }).className.split(' ');
    expect(classes).toContain('rounded-full');
    expect(classes).toContain('px-5');
    expect(classes).not.toContain('px-3');
    expect(classes).not.toContain('px-4');
  });

  it('a small pill keeps px-3', () => {
    const classes = trigger({ size: 'sm', shape: 'pill' }).className.split(' ');
    expect(classes).toContain('px-3');
    expect(classes).not.toContain('px-5');
  });

  it('field text is 16px on phones, 14px from md', () => {
    const classes = trigger({}).className.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining(['text-base', 'md:text-sm']),
    );
  });

  it('sm text stays 14px', () => {
    const classes = trigger({ size: 'sm' }).className.split(' ');
    expect(classes).not.toContain('text-base');
    expect(classes).toContain('text-sm');
  });

  it('shows the not-allowed cursor while disabled', () => {
    const classes = trigger({}).className.split(' ');
    expect(classes).toContain('disabled:cursor-not-allowed');
    expect(classes).toContain('focus-visible:ring-3');
  });
});
