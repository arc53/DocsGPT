import { Globe } from 'lucide-react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('./starters', () => {
  const entries = [
    ['website', 'customerSupport'],
    ['helpdesk', 'internal'],
    ['research', 'research'],
    ['orders', 'customerSupport'],
    ['returns', 'customerSupport'],
    ['ittriage', 'internal'],
    ['onboarding', 'internal'],
    ['contracts', 'research'],
    ['rfp', 'research'],
    ['incident', 'internal'],
    ['weekly', 'internal'],
    ['pricing', 'customerSupport'],
    ['legal', 'research'],
    ['payroll', 'internal'],
  ].map(([key, category]) => ({ key, category, Icon: Globe }));
  return { DRAFTER_STARTERS: entries };
});

import { TemplatePicker } from './TemplatePicker';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('TemplatePicker', () => {
  let container: HTMLDivElement;
  let root: Root;
  const onPick = vi.fn();

  beforeEach(() => {
    onPick.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async () => {
    await act(async () => {
      root.render(<TemplatePicker onPick={onPick} />);
    });
  };
  const rows = () =>
    Array.from(
      container.querySelectorAll<HTMLButtonElement>('[data-suggestion]'),
    ).map((row) => row.dataset.suggestion);
  const button = (text: string) =>
    Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent === text,
    );
  const search = async (value: string) => {
    const input = container.querySelector<HTMLInputElement>('input')!;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!;
    await act(async () => {
      setter.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };

  it('shows twelve templates, then the rest on Show more', async () => {
    await render();
    expect(rows()).toHaveLength(12);
    await act(async () => button('drafter.templates.showMore')!.click());
    expect(rows()).toHaveLength(14);
    expect(button('drafter.templates.showMore')).toBeUndefined();
  });

  it('searches titles and descriptions, ignoring case', async () => {
    await render();
    await search('RETURNS.TITLE');
    expect(rows()).toEqual(['returns']);
    await search('legal.description');
    expect(rows()).toEqual(['legal']);
  });

  it('filters by category, with All first', async () => {
    await render();
    const radios = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[role="radio"]'),
    );
    expect(radios.map((radio) => radio.textContent)).toEqual([
      expect.stringContaining('drafter.templates.categories.all'),
      expect.stringContaining('drafter.templates.categories.customerSupport'),
      expect.stringContaining('drafter.templates.categories.internal'),
      expect.stringContaining('drafter.templates.categories.research'),
    ]);
    await act(async () => radios[3].click());
    expect(rows()).toEqual(['research', 'contracts', 'rfp', 'legal']);
  });

  it('hides the categories when a search leaves only one', async () => {
    await render();
    await search('orders.title');
    expect(container.querySelector('[role="radiogroup"]')).toBeNull();
  });

  it('says so when nothing matches', async () => {
    await render();
    await search('nothing like this');
    expect(rows()).toHaveLength(0);
    expect(container.textContent).toContain('drafter.templates.empty');
  });

  it('hands the picked template over', async () => {
    await render();
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[data-suggestion="rfp"]')!
        .click(),
    );
    expect(onPick).toHaveBeenCalledWith('rfp');
  });
});
