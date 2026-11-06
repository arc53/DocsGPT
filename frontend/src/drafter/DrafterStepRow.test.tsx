import { CircleCheck, ListChecks } from 'lucide-react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { DrafterStepRow, FilledRow } from './DrafterStepRow';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('DrafterStepRow', () => {
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

  it('opens its rows from a step-row toggle tied to the list', async () => {
    await act(async () =>
      root.render(
        <DrafterStepRow icon={ListChecks} label="Filled 2 fields">
          <FilledRow label="Name" value="Shipping help desk" />
          <FilledRow label="Description" value="Answers parcel questions" />
        </DrafterStepRow>,
      ),
    );
    const toggle = container.querySelector('button')!;
    expect(toggle.textContent).toBe('Filled 2 fields');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    const body = document.getElementById(
      toggle.getAttribute('aria-controls')!,
    )!;
    expect(body.getAttribute('data-state')).toBe('closed');
    expect(body.hasAttribute('inert')).toBe(true);

    await act(async () => toggle.click());
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(body.getAttribute('data-state')).toBe('open');
    const rows = body.querySelectorAll('[data-slot="filled-row"]');
    expect(rows).toHaveLength(2);
    // One line each: the label, then what it now holds, the whole of it
    // as the title of the truncated text.
    expect(rows[0].textContent).toBe('Name · Shipping help desk');
    expect(rows[0].querySelector('[title]')?.getAttribute('title')).toBe(
      'Name · Shipping help desk',
    );
  });

  it('starts open when asked', async () => {
    await act(async () =>
      root.render(
        <DrafterStepRow icon={CircleCheck} label="Basics" defaultOpen>
          <FilledRow label="Name" value="Desk" />
        </DrafterStepRow>,
      ),
    );
    expect(
      container.querySelector('button')!.getAttribute('aria-expanded'),
    ).toBe('true');
  });

  it('is a plain line when there is nothing to open', async () => {
    await act(async () =>
      root.render(
        <DrafterStepRow
          icon={CircleCheck}
          label="Basics: Shipping help desk"
        />,
      ),
    );
    expect(container.querySelector('button')).toBeNull();
    expect(container.textContent).toBe('Basics: Shipping help desk');
  });
});
