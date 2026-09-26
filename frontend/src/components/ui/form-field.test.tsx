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

describe('FormField floating label', () => {
  it('floats the label on the field border, after the field', () => {
    const host = render(
      <FormField label="Server name">
        <Input />
      </FormField>,
    );
    const box = host.querySelector('input')!.parentElement!;
    expect(box.className).toContain('relative');
    const label = box.querySelector('label')!;
    expect(box.lastElementChild).toBe(label);
    for (const cls of [
      'absolute',
      '-top-2.5',
      'left-3',
      'text-xs',
      'bg-card',
    ]) {
      expect(label.className.split(' ')).toContain(cls);
    }
    expect(label.className).toContain('text-muted-foreground');
  });

  it('rests the label inside an empty, unfocused Input or Textarea', () => {
    const label = render(
      <FormField label="Server name">
        <Input />
      </FormField>,
    ).querySelector('label')!;
    expect(label.className).toContain(
      'group-has-[>input:placeholder-shown:not(:focus),>*>input:placeholder-shown:not(:focus)]/float:top-2',
    );
    expect(label.className).toContain(
      'group-has-[>textarea:placeholder-shown:not(:focus),>*>textarea:placeholder-shown:not(:focus)]/float:top-2',
    );
  });

  it('gives Input and Textarea a blank placeholder and shows a real one only on focus', () => {
    const blank = render(
      <FormField label="Server name">
        <Input />
      </FormField>,
    ).querySelector('input')!;
    expect(blank.getAttribute('placeholder')).toBe(' ');
    const input = render(
      <FormField label="Member email">
        <Input placeholder="name@example.com" />
      </FormField>,
    ).querySelector('input')!;
    expect(input.getAttribute('placeholder')).toBe('name@example.com');
    expect(input.className).toContain('placeholder:text-transparent');
    expect(input.className).toContain(
      'focus:placeholder:text-muted-foreground',
    );
    const textarea = render(
      <FormField label="Description">
        <Textarea />
      </FormField>,
    ).querySelector('textarea')!;
    expect(textarea.getAttribute('placeholder')).toBe(' ');
    expect(textarea.className).toContain(
      'focus:placeholder:text-muted-foreground',
    );
  });

  it('turns the label red with an error', () => {
    const label = render(
      <FormField label="Server URL" error="Please enter a valid URL">
        <Input />
      </FormField>,
    ).querySelector('label')!;
    expect(label.className).toContain('text-destructive');
    expect(label.className).not.toContain('text-muted-foreground');
  });

  it('matches the notch to labelSurface', () => {
    const label = render(
      <FormField label="Policy" labelSurface="muted">
        <Textarea />
      </FormField>,
    ).querySelector('label')!;
    expect(label.className.split(' ')).toContain('bg-muted');
    expect(label.className.split(' ')).not.toContain('bg-card');
  });

  it('puts the label above the field with float={false}', () => {
    const host = render(
      <FormField label="Resources" float={false}>
        <Input />
      </FormField>,
    );
    const wrapper = host.firstElementChild as HTMLElement;
    expect(wrapper.firstElementChild?.tagName).toBe('LABEL');
    expect(wrapper.firstElementChild?.className).not.toContain('absolute');
    const input = host.querySelector('input')!;
    expect(input.hasAttribute('placeholder')).toBe(false);
    expect(input.className).not.toContain('placeholder:text-transparent');
  });
});

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
