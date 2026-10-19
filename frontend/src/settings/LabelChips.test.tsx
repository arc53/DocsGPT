import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts?.formatted ? `${key}(${opts.formatted})` : key,
    i18n: { language: 'en' },
  }),
}));

import LabelChips, { labelChips } from './LabelChips';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('labelChips', () => {
  const name = (key: string) => key;

  it('orders the model labels and lets a docs gap stand for not answered', () => {
    expect(
      labelChips(
        ['asks_human', 'not_answered', 'frustrated', 'docs_gap'],
        {},
        name,
      ).map((chip) => chip.id),
    ).toEqual(['docs_gap', 'frustrated', 'asks_human']);
    expect(
      labelChips(['not_answered'], {}, name).map((chip) => chip.id),
    ).toEqual(['not_answered']);
  });

  it('names tags from the agent, and leaves out a tag it has no name for', () => {
    expect(
      labelChips(
        ['tag:a1b2c3d4', 'tag:deadbeef', 'frustrated'],
        { a1b2c3d4: 'Pricing question' },
        name,
      ).map((chip) => [chip.id, chip.label]),
    ).toEqual([
      ['frustrated', 'frustrated'],
      ['tag:a1b2c3d4', 'Pricing question'],
    ]);
  });
});

describe('LabelChips', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('draws nothing without labels', () => {
    act(() => root.render(<LabelChips labels={[]} />));
    expect(container.innerHTML).toBe('');
  });

  it('colours each label by meaning, with its icon first', () => {
    act(() =>
      root.render(
        <LabelChips
          labels={['docs_gap', 'frustrated', 'asks_human']}
          tagNames={{}}
        />,
      ),
    );
    const badges = Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="badge"]'),
    );
    expect(badges.map((badge) => badge.dataset.variant)).toEqual([
      'warning',
      'destructive',
      'info',
    ]);
    expect(badges[0].textContent).toBe('settings.logs.labels.docsGap');
    expect(badges[0].querySelector('svg[aria-hidden="true"]')).not.toBeNull();
  });

  it('shows three chips, then +N naming the rest', () => {
    act(() =>
      root.render(
        <LabelChips
          labels={[
            'docs_gap',
            'negative_reaction',
            'frustrated',
            'asks_human',
            'tag:a1b2c3d4',
          ]}
          tagNames={{ a1b2c3d4: 'Pricing question' }}
        />,
      ),
    );
    const badges = Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="badge"]'),
    );
    expect(badges).toHaveLength(4);
    const more = badges[3];
    expect(more.dataset.variant).toBe('neutral');
    expect(more.textContent).toContain('settings.logs.labels.more(2)');
    expect(more.title).toBe(
      'settings.logs.labels.asksHuman and Pricing question',
    );
  });

  it('truncates a long tag name and keeps it whole in its title', () => {
    act(() =>
      root.render(
        <LabelChips
          labels={['tag:a1b2c3d4']}
          tagNames={{ a1b2c3d4: 'A very long owner-written tag name' }}
        />,
      ),
    );
    const badge = container.querySelector<HTMLElement>('[data-slot="badge"]')!;
    expect(badge.dataset.variant).toBe('neutral');
    expect(badge.className).toContain('max-w-48');
    const text = badge.querySelector<HTMLElement>('.truncate')!;
    expect(text.title).toBe('A very long owner-written tag name');
  });
});
