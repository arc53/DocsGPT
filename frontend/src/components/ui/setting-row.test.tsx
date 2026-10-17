import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Input } from './input';
import { SettingRow, SettingRows } from './setting-row';
import { Switch } from './switch';

function render(element: React.ReactElement): HTMLElement {
  const host = document.createElement('div');
  host.innerHTML = renderToStaticMarkup(element);
  return host;
}

describe('SettingRows / SettingRow', () => {
  it('separates rows with a faint divider', () => {
    const host = render(
      <SettingRows>
        <SettingRow label="Token limiting">
          <Switch />
        </SettingRow>
      </SettingRows>,
    );
    const rows = host.firstElementChild as HTMLElement;
    expect(rows.className).toContain('divide-y');
    expect(rows.className).toContain('divide-border/50');
  });

  it('pads each row 12px, flush at the ends of the group', () => {
    const host = render(
      <SettingRow label="Token limiting">
        <Switch />
      </SettingRow>,
    );
    const row = host.firstElementChild as HTMLElement;
    expect(row.className).toContain('py-3');
    expect(row.className).toContain('first:pt-0');
    expect(row.className).toContain('last:pb-0');
  });

  it('names the control with a clickable Label by default', () => {
    const host = render(
      <SettingRow
        label="Token limiting"
        description="Limit daily total tokens"
        htmlFor="token-limiting"
      >
        <Switch id="token-limiting" />
      </SettingRow>,
    );
    const label = host.querySelector('label')!;
    expect(label.getAttribute('for')).toBe('token-limiting');
    expect(label.className.split(' ')).not.toContain('pointer-events-none');
    const description = host.querySelector('p')!;
    expect(description.className).toContain('text-muted-foreground');
    expect(description.className).toContain('text-xs');
  });

  it('keeps a heading tag when asked', () => {
    const host = render(
      <SettingRow label="Guardrails" as="h3">
        <Switch aria-label="Guardrails" />
      </SettingRow>,
    );
    expect(host.querySelector('h3')?.textContent).toBe('Guardrails');
    expect(host.querySelector('label')).toBeNull();
  });

  it('aligns to the top for multi-line descriptions', () => {
    const top = render(
      <SettingRow label="A" alignStart>
        <Switch />
      </SettingRow>,
    );
    expect(top.innerHTML).toContain('items-start');
    const centred = render(
      <SettingRow label="A">
        <Switch />
      </SettingRow>,
    );
    expect(centred.innerHTML).toContain('items-center');
  });

  it('puts the `after` slot under the row, 8px down', () => {
    const host = render(
      <SettingRow label="Token limiting" after={<input data-testid="limit" />}>
        <Switch />
      </SettingRow>,
    );
    const after = host.querySelector('[data-testid="limit"]')!
      .parentElement as HTMLElement;
    expect(after.className).toContain('mt-2');
  });

  it('stacks a wide control under the label on phones with `stack`', () => {
    const host = render(
      <SettingRow label="Theme" stack>
        <select data-testid="picker" />
      </SettingRow>,
    );
    const line = host.querySelector('[data-slot="setting-row"] > div')!;
    expect(line.className.split(' ')).toEqual(
      expect.arrayContaining(['flex-col', 'sm:flex-row', 'sm:items-center']),
    );
    const slot = host.querySelector('[data-testid="picker"]')!
      .parentElement as HTMLElement;
    expect(slot.className.split(' ')).toEqual(
      expect.arrayContaining(['w-full', 'sm:w-auto']),
    );
    const plain = render(
      <SettingRow label="Theme">
        <select />
      </SettingRow>,
    );
    expect(plain.innerHTML).not.toContain('sm:flex-row');
  });

  it('describes the control with its description (aria-describedby)', () => {
    const host = render(
      <SettingRow
        label="Token limiting"
        description="Limit daily total tokens"
        htmlFor="token-limiting"
      >
        <Switch />
      </SettingRow>,
    );
    const control = host.querySelector('[data-slot="switch"]')!;
    const description = host.querySelector('p')!;
    // The row fills the id, so the label names the Switch without an id.
    expect(control.id).toBe('token-limiting');
    expect(description.id).toBeTruthy();
    expect(control.getAttribute('aria-describedby')).toBe(description.id);
  });

  it('generates the id when no htmlFor is given', () => {
    const host = render(
      <SettingRow label="Theme" description="Pick one">
        <Switch />
      </SettingRow>,
    );
    const control = host.querySelector('[data-slot="switch"]')!;
    expect(control.id).toBeTruthy();
    expect(host.querySelector('label')!.getAttribute('for')).toBe(control.id);
  });

  it('lets the control keep its own id and describedby', () => {
    const host = render(
      <SettingRow label="A" description="B" htmlFor="x">
        <Switch id="x" aria-describedby="elsewhere" />
      </SettingRow>,
    );
    const control = host.querySelector('[data-slot="switch"]')!;
    expect(control.id).toBe('x');
    expect(control.getAttribute('aria-describedby')).toBe('elsewhere');
  });

  it('sets no aria-describedby without a description', () => {
    const host = render(
      <SettingRow label="A" htmlFor="x">
        <Switch />
      </SettingRow>,
    );
    const control = host.querySelector('[data-slot="switch"]')!;
    expect(control.hasAttribute('aria-describedby')).toBe(false);
  });

  it('keeps its wiring off the `after` field', () => {
    const host = render(
      <SettingRow
        label="Token limiting"
        description="Limit daily total tokens"
        htmlFor="token-limiting"
        after={<Input data-testid="limit" />}
      >
        <Switch />
      </SettingRow>,
    );
    const limit = host.querySelector('[data-testid="limit"]')!;
    expect(limit.id).not.toBe('token-limiting');
    expect(limit.hasAttribute('aria-describedby')).toBe(false);
  });
});
