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

  it('lets frustration stand for a negative tone', () => {
    expect(
      labelChips(['negative_sentiment', 'frustrated'], {}, name).map(
        (chip) => chip.id,
      ),
    ).toEqual(['frustrated']);
    expect(
      labelChips(['negative_reaction', 'negative_sentiment'], {}, name).map(
        (chip) => chip.id,
      ),
    ).toEqual(['negative_reaction', 'negative_sentiment']);
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

  it('colours each label by meaning, in text only', () => {
    const variants = (labels: string[]) => {
      act(() =>
        root.render(<LabelChips labels={labels} tagNames={{ t: 'Tag' }} />),
      );
      return Array.from(
        container.querySelectorAll<HTMLElement>('[data-slot="badge"]'),
      ).map((badge) => badge.dataset.variant);
    };
    // Needs attention: amber.
    expect(variants(['docs_gap', 'asks_human'])).toEqual([
      'warning',
      'warning',
    ]);
    expect(variants(['not_answered'])).toEqual(['warning']);
    // Upset: red, as the row's thumbs-down is.
    expect(variants(['negative_reaction', 'frustrated'])).toEqual([
      'destructive',
      'destructive',
    ]);
    expect(variants(['negative_sentiment'])).toEqual(['destructive']);
    // The owner's own tags: grey.
    expect(variants(['tag:t'])).toEqual(['neutral']);
    // No icons, on labels or tags.
    act(() =>
      root.render(
        <LabelChips
          labels={['docs_gap', 'frustrated', 'tag:t']}
          tagNames={{ t: 'Tag' }}
        />,
      ),
    );
    expect(container.querySelector('svg')).toBeNull();
    const first = container.querySelector<HTMLElement>('[data-slot="badge"]')!;
    expect(first.textContent).toBe('settings.logs.labels.docsGap');
  });

  it('sets its own UI font, since rows are monospace', () => {
    act(() => root.render(<LabelChips labels={['docs_gap']} />));
    const line = container.querySelector<HTMLElement>(
      '[data-testid="label-chips"]',
    )!;
    expect(line.className.split(' ')).toContain('font-sans');
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
    // The rest is named for screen readers; no title, which is not a tooltip.
    expect(more.hasAttribute('title')).toBe(false);
    expect(more.querySelector('.sr-only')!.textContent).toBe(
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
