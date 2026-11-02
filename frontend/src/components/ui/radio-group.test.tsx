import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { RadioGroup, RadioGroupItem } from './radio-group';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function render(element: React.ReactElement): HTMLElement {
  const host = document.createElement('div');
  host.innerHTML = renderToStaticMarkup(element);
  return host;
}

const classesOf = (el: Element | null) =>
  (el?.getAttribute('class') ?? '').split(/\s+/);

const prompts = (value?: string, size?: 'default' | 'sm') => (
  <RadioGroup value={value} aria-label="Prompt for chats">
    <RadioGroupItem value="default" size={size} aria-label="Use default" />
    <RadioGroupItem value="strict" size={size} aria-label="Use strict" />
  </RadioGroup>
);

describe('RadioGroup', () => {
  it('is a named radiogroup of radios', () => {
    const host = render(prompts('strict'));
    const group = host.querySelector('[data-slot="radio-group"]')!;
    expect(group.getAttribute('role')).toBe('radiogroup');
    expect(group.getAttribute('aria-label')).toBe('Prompt for chats');
    const radios = host.querySelectorAll('[role="radio"]');
    expect(radios).toHaveLength(2);
    expect(radios[1].getAttribute('aria-checked')).toBe('true');
    expect(radios[0].getAttribute('aria-checked')).toBe('false');
  });

  it('takes layout classes over its default grid, keeping its gap', () => {
    const host = render(
      <RadioGroup className="flex flex-col" aria-label="Prompts">
        <RadioGroupItem value="a" aria-label="A" />
      </RadioGroup>,
    );
    const classes = classesOf(host.querySelector('[data-slot="radio-group"]'));
    expect(classes).toEqual(expect.arrayContaining(['flex', 'gap-3']));
    expect(classes).not.toContain('grid');
  });
});

describe('RadioGroupItem', () => {
  it('is a 16px circle whose empty ring is muted-foreground, not border-input', () => {
    const host = render(prompts());
    const radio = host.querySelector('[role="radio"]')!;
    const classes = classesOf(radio);
    expect(radio.getAttribute('data-slot')).toBe('radio-group-item');
    expect(classes).toEqual(
      expect.arrayContaining([
        'size-4',
        'rounded-full',
        'border',
        'border-muted-foreground',
      ]),
    );
    // border-input is about 1.3:1 on a filled card: the ring disappears.
    expect(classes).not.toContain('border-input');
  });

  it('marks checked with the lighter primary, 3:1 or more on a filled card in dark', () => {
    const classes = classesOf(
      render(prompts()).querySelector('[role="radio"]'),
    );
    expect(classes).toContain(
      'data-[state=checked]:border-secondary-foreground',
    );
    // primary is 2.65:1 on bg-muted in dark.
    expect(
      classes.some((c) => /^data-\[state=checked\]:border-primary$/.test(c)),
    ).toBe(false);
  });

  it('has the shared focus ring and a 24px hit area', () => {
    const classes = classesOf(
      render(prompts()).querySelector('[role="radio"]'),
    );
    expect(classes).toEqual(
      expect.arrayContaining([
        'focus-visible:ring-3',
        'focus-visible:ring-ring/50',
        'focus-visible:border-ring',
        'relative',
        'after:absolute',
        'after:-inset-1',
      ]),
    );
  });

  it('draws the dot only on the checked item', () => {
    const host = render(prompts('strict'));
    const dots = host.querySelectorAll('[data-slot="radio-group-indicator"]');
    expect(dots).toHaveLength(1);
    const checked = host.querySelector('[aria-checked="true"]')!;
    expect(checked.contains(dots[0])).toBe(true);
    const dot = dots[0].firstElementChild!;
    expect(classesOf(dot)).toEqual(
      expect.arrayContaining([
        'size-2',
        'rounded-full',
        'bg-secondary-foreground',
      ]),
    );
  });

  it('size="sm" is 14px with a 6px dot, like Checkbox sm', () => {
    const host = render(prompts('default', 'sm'));
    const radio = host.querySelector('[role="radio"]')!;
    expect(classesOf(radio)).toContain('size-3.5');
    expect(classesOf(radio)).not.toContain('size-4');
    expect(radio.getAttribute('data-size')).toBe('sm');
    const dot = host.querySelector(
      '[data-slot="radio-group-indicator"]',
    )!.firstElementChild!;
    expect(classesOf(dot)).toContain('size-1.5');
  });

  it('fades while disabled', () => {
    const host = render(
      <RadioGroup aria-label="P">
        <RadioGroupItem value="a" disabled aria-label="A" />
      </RadioGroup>,
    );
    const radio = host.querySelector('[role="radio"]') as HTMLButtonElement;
    expect(radio.disabled).toBe(true);
    expect(classesOf(radio)).toEqual(
      expect.arrayContaining([
        'disabled:cursor-not-allowed',
        'disabled:opacity-50',
      ]),
    );
  });
});

describe('RadioGroup interaction', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it('keeps items in a nested card grid as one group', async () => {
    const onValueChange = vi.fn();
    await act(async () =>
      root.render(
        <RadioGroup onValueChange={onValueChange} aria-label="Prompt">
          <div className="grid gap-4 md:grid-cols-3">
            <div>
              <RadioGroupItem value="default" aria-label="Use default" />
            </div>
            <div>
              <RadioGroupItem value="strict" aria-label="Use strict" />
            </div>
          </div>
        </RadioGroup>,
      ),
    );
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[aria-label="Use strict"]')!
        .click(),
    );
    expect(onValueChange).toHaveBeenCalledWith('strict');
    expect(
      container
        .querySelector('[aria-label="Use strict"]')!
        .getAttribute('aria-checked'),
    ).toBe('true');
  });

  it('picks the clicked item', async () => {
    const onValueChange = vi.fn();
    await act(async () =>
      root.render(
        <RadioGroup
          value="default"
          onValueChange={onValueChange}
          aria-label="Prompt"
        >
          <RadioGroupItem value="default" aria-label="Use default" />
          <RadioGroupItem value="strict" aria-label="Use strict" />
        </RadioGroup>,
      ),
    );
    const strict = container.querySelector<HTMLButtonElement>(
      '[aria-label="Use strict"]',
    )!;
    await act(async () => strict.click());
    expect(onValueChange).toHaveBeenCalledWith('strict');
  });
});
