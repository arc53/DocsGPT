import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { FormField, FormFieldBoundary } from './form-field';
import { Input } from './input';
import { MultiSelect } from './multi-select';
import { Select, SelectTrigger, SelectValue } from './select';
import { Textarea } from './textarea';

/** Parses rendered markup so tests can query it like the DOM. */
function render(element: React.ReactElement): HTMLElement {
  const host = document.createElement('div');
  host.innerHTML = renderToStaticMarkup(element);
  return host;
}

describe('FormField', () => {
  it('stacks label, field, hint and error 6px apart', () => {
    const host = render(
      <FormField label="Server name" hint="Shown in the tool list">
        <Input />
      </FormField>,
    );
    const wrapper = host.firstElementChild as HTMLElement;
    expect(wrapper.className).toContain('flex-col');
    expect(wrapper.className).toContain('gap-1.5');
    expect(host.querySelector('p')?.className).toContain(
      'text-muted-foreground',
    );
  });

  it('points the label at the field and describes it with the hint', () => {
    const host = render(
      <FormField label="Server name" hint="Shown in the tool list">
        <Input />
      </FormField>,
    );
    const label = host.querySelector('label')!;
    const input = host.querySelector('input')!;
    expect(input.id).not.toBe('');
    expect(label.getAttribute('for')).toBe(input.id);
    const hint = host.querySelector('p')!;
    expect(input.getAttribute('aria-describedby')).toBe(hint.id);
  });

  it('keeps an id the field already has', () => {
    const host = render(
      <FormField label="Server name">
        <Input id="mcp-name" />
      </FormField>,
    );
    expect(host.querySelector('input')!.id).toBe('mcp-name');
    expect(host.querySelector('label')!.getAttribute('for')).toBe('mcp-name');
  });

  it('marks the field invalid and announces the error', () => {
    const host = render(
      <FormField
        label="Server name"
        hint="Shown"
        error="Server name is required"
      >
        <Input />
      </FormField>,
    );
    const input = host.querySelector('input')!;
    const error = host.querySelector('[role="alert"]')!;
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect(error.className).toContain('text-destructive');
    expect(error.textContent).toBe('Server name is required');
    expect(input.getAttribute('aria-describedby')?.split(' ')).toContain(
      error.id,
    );
  });

  it('draws a tight, decorative star and sets aria-required', () => {
    const host = render(
      <FormField label="Server name" required>
        <Input />
      </FormField>,
    );
    const label = host.querySelector('label')!;
    expect(label.className).toContain('gap-1');
    const star = label.querySelector('span')!;
    expect(star.getAttribute('aria-hidden')).toBe('true');
    expect(star.className).toContain('text-destructive');
    expect(host.querySelector('input')!.getAttribute('aria-required')).toBe(
      'true',
    );
    // No native `required`: forms keep their own validation.
    expect(host.querySelector('input')!.hasAttribute('required')).toBe(false);
  });

  it('wires Textarea and a SelectTrigger nested inside Select', () => {
    const textarea = render(
      <FormField label="Schema" error="Invalid">
        <Textarea />
      </FormField>,
    );
    expect(
      textarea.querySelector('textarea')!.getAttribute('aria-invalid'),
    ).toBe('true');

    const select = render(
      <FormField label="Authentication type">
        <Select>
          <SelectTrigger>
            <SelectValue placeholder="None" />
          </SelectTrigger>
        </Select>
      </FormField>,
    );
    const trigger = select.querySelector('[data-slot="select-trigger"]')!;
    expect(select.querySelector('label')!.getAttribute('for')).toBe(trigger.id);
  });

  it('wires a MultiSelect trigger', () => {
    const host = render(
      <FormField label="Agents" error="Pick one">
        <MultiSelect options={[]} selected={[]} onChange={() => undefined} />
      </FormField>,
    );
    const trigger = host.querySelector('[role="combobox"]')!;
    expect(host.querySelector('label')!.getAttribute('for')).toBe(trigger.id);
    expect(trigger.getAttribute('aria-invalid')).toBe('true');
  });

  it('dims the label and disables the field when disabled', () => {
    const host = render(
      <FormField label="Server name" disabled>
        <Input />
      </FormField>,
    );
    const wrapper = host.firstElementChild as HTMLElement;
    expect(wrapper.className).toContain('group');
    expect(wrapper.getAttribute('data-disabled')).toBe('true');
    expect(host.querySelector('input')!.disabled).toBe(true);
  });

  it('does not reach fields past a FormFieldBoundary', () => {
    const host = render(
      <FormField label="Prompt" id="prompt">
        <Textarea />
        <FormFieldBoundary>
          <Input aria-label="Search variables" />
        </FormFieldBoundary>
      </FormField>,
    );
    expect(host.querySelector('textarea')!.id).toBe('prompt');
    expect(host.querySelector('input')!.hasAttribute('id')).toBe(false);
  });

  it('leaves fields outside a FormField untouched', () => {
    const host = render(<Input />);
    const input = host.querySelector('input')!;
    expect(input.hasAttribute('id')).toBe(false);
    expect(input.hasAttribute('aria-invalid')).toBe(false);
  });
});
