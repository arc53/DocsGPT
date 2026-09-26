import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  Command,
  CommandDialog,
  CommandInput,
  CommandItem,
  CommandList,
} from './command';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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

const render = async (element: React.ReactElement) => {
  await act(async () => root.render(element));
};

describe('Command', () => {
  it('is a plain command surface by default', async () => {
    await render(<Command />);
    const cmd = document.querySelector('[data-slot="command"]')!;
    expect(cmd.getAttribute('data-variant')).toBe('default');
    expect(cmd.className).not.toContain('[[cmdk-item]]:py-3');
  });

  it('variant="palette" carries the palette spacing for input and rows', async () => {
    await render(<Command variant="palette" />);
    const cmd = document.querySelector('[data-slot="command"]')!;
    expect(cmd.getAttribute('data-variant')).toBe('palette');
    expect(cmd.className).toContain(
      '**:data-[slot=command-input-wrapper]:h-12',
    );
    expect(cmd.className).toContain('**:[[cmdk-item]]:py-3');
    expect(cmd.className).toContain('**:[[cmdk-item]]:px-2');
  });
});

describe('CommandDialog', () => {
  it('renders one palette Command and forwards commandProps to it', async () => {
    await render(
      <CommandDialog
        open
        showCloseButton={false}
        commandProps={{ shouldFilter: false, label: 'Search' }}
      >
        <CommandInput
          placeholder="Search"
          value="zzz"
          onValueChange={() => {}}
        />
        <CommandList>
          <CommandItem value="a">Fuel surcharge policy</CommandItem>
        </CommandList>
      </CommandDialog>,
    );
    const commands = document.querySelectorAll('[data-slot="command"]');
    expect(commands).toHaveLength(1);
    expect(commands[0].getAttribute('data-variant')).toBe('palette');
    // shouldFilter={false} reached cmdk: an item that doesn't match the query
    // stays rendered.
    expect(document.body.textContent).toContain('Fuel surcharge policy');
  });

  it('CommandItem checked marks the chosen item apart from the hover highlight', async () => {
    await render(
      <Command>
        <CommandList>
          <CommandItem value="a" checked>
            Default
          </CommandItem>
          <CommandItem value="b">Strict</CommandItem>
        </CommandList>
      </Command>,
    );
    const items = document.querySelectorAll('[data-slot="command-item"]');
    expect(items[0].getAttribute('data-checked')).toBe('true');
    expect(items[0].className).toContain('data-[checked=true]:bg-secondary');
    expect(items[1].hasAttribute('data-checked')).toBe(false);
    expect(items[1].hasAttribute('checked')).toBe(false);
  });

  it('keeps the checked tint while highlighted and rings it in primary', async () => {
    await render(
      <Command>
        <CommandList>
          <CommandItem value="a" checked>
            Default
          </CommandItem>
        </CommandList>
      </Command>,
    );
    const classes = document
      .querySelector('[data-slot="command-item"]')!
      .className.split(' ');
    // Stacked data attributes out-rank the plain data-[selected=true] accent.
    for (const cls of [
      'data-[checked=true]:data-[selected=true]:bg-secondary',
      'data-[checked=true]:data-[selected=true]:text-secondary-foreground',
      'data-[checked=true]:data-[selected=true]:ring-1',
      'data-[checked=true]:data-[selected=true]:ring-inset',
      'data-[checked=true]:data-[selected=true]:ring-primary',
    ]) {
      expect(classes).toContain(cls);
    }
    // The ordinary highlight is still there for unchecked rows.
    expect(classes).toContain('data-[selected=true]:bg-accent');
  });
});

describe('CommandInput', () => {
  it('is 16px on phones, fills its wrapper and selects in brand', async () => {
    await render(
      <Command>
        <CommandInput placeholder="Search" />
        <CommandList>
          <CommandItem>One</CommandItem>
        </CommandList>
      </Command>,
    );
    const classes = document
      .querySelector('[data-slot="command-input"]')!
      .className.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining([
        'text-base',
        'md:text-sm',
        'h-full',
        'selection:bg-primary',
      ]),
    );
    expect(classes).not.toContain('h-10');
  });
});
