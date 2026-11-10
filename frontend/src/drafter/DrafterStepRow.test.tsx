import { CircleCheck, ListChecks } from 'lucide-react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options && 'count' in options ? `${key}:${options.count}` : key,
  }),
}));

import { DrafterStepRow, FilledRow } from './DrafterStepRow';
import { ProposalSummary } from './ProposalSummary';

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
    // The label, then what it now holds, wrapping: touch and keyboard
    // users read all of it, so nothing hides in a title.
    expect(rows[0].textContent).toBe('Name · Shipping help desk');
    expect(rows[0].querySelector('[title]')).toBeNull();
    expect(rows[0].querySelector('.truncate')).toBeNull();
    expect(rows[0].className).toContain('min-h-7');
    expect(rows[0].querySelector('p')!.className).toContain('wrap-break-word');
  });

  // Decision 93: an undone field says so, and the step row counts it.
  it('mutes an undone field and counts it on the step row', async () => {
    await act(async () =>
      root.render(
        <DrafterStepRow icon={ListChecks} label="Filled 2 fields" undone={1}>
          <FilledRow label="Name" value="Desk" undone="empty" />
          <FilledRow label="Tone" value="Warm" undone="previous" />
          <FilledRow label="Description" value="Answers parcel questions" />
        </DrafterStepRow>,
      ),
    );
    expect(container.querySelector('button')!.textContent).toBe(
      'Filled 2 fields · drafter.undone.count:1',
    );
    const rows = container.querySelectorAll('[data-slot="filled-row"]');
    expect(rows[0].textContent).toBe('Name · drafter.undone.empty');
    expect(rows[0].className).toContain('text-muted-foreground');
    expect(rows[1].textContent).toBe('Tone · drafter.undone.previous');
    expect(rows[2].className).not.toContain('text-muted-foreground');
  });

  it('marks the undone rows a proposal summary is given', async () => {
    const rows = [
      { key: 'name', label: 'Name', summary: 'Desk' },
      { key: 'description', label: 'Description', summary: 'Answers' },
    ];
    await act(async () =>
      root.render(
        <ProposalSummary rows={rows} undone={new Map([['name', 'empty']])} />,
      ),
    );
    expect(container.querySelector('button')!.textContent).toBe(
      'drafter.filled:2 · drafter.undone.count:1',
    );
    const filled = container.querySelectorAll('[data-slot="filled-row"]');
    expect(filled[0].textContent).toBe('Name · drafter.undone.empty');
    // A plain set of keys says only that the field went back.
    await act(async () =>
      root.render(<ProposalSummary rows={rows} undone={new Set(['name'])} />),
    );
    expect(
      container.querySelector('[data-slot="filled-row"]')!.textContent,
    ).toBe('Name · drafter.undone.previous');
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
