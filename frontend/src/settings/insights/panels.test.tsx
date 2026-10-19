import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { ConversationInsights } from '../types';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts?.points !== undefined ? `${key}(${opts.points})` : key,
    i18n: { language: 'en' },
  }),
}));

vi.mock('../AnalyticsChart', () => ({
  default: (props: {
    data: { datasets: { label: string; data: number[] }[] };
  }) => (
    <div data-testid="chart">
      {props.data.datasets
        .map((dataset) => `${dataset.label}=${dataset.data.join('+')}`)
        .join(',')}
    </div>
  ),
}));

import ImplicitFeedbackPanel from './ImplicitFeedbackPanel';
import IntervalBars from './IntervalBars';
import TierBadge from './TierBadge';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const insights = (n: number): ConversationInsights => ({
  success: true,
  enabled: true,
  available: true,
  coverage: {
    turns: 10,
    labelled_turns: 10,
    replies: n,
    labelled_replies: n,
    conversations: 5,
    labelled_conversations: 5,
  },
  languages: {},
  language_warnings: [],
  tags: [],
  totals: {
    reaction: {
      tier: 'estimated',
      n,
      options: {
        'thanks or confirmation': {
          expected: 4,
          rate: 0.3,
          low: 0.2,
          high: 0.5,
        },
        complaint: { expected: 1, rate: 0.1, low: 0.02, high: 0.2 },
      },
    },
  },
  series: [
    {
      bucket: '2026-10-18',
      labels: {
        reaction: {
          n: 6,
          options: {
            'thanks or confirmation': 2,
            're-ask': 1,
            'correction or pushback': 0.5,
            complaint: 0.25,
            'new question': 3,
          },
        },
      },
    },
  ],
});

describe('insight panels', () => {
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

  it('draws implicit feedback as three meaningful series, pushback and complaint summed', () => {
    act(() => root.render(<ImplicitFeedbackPanel data={insights(40)} />));
    expect(container.querySelector('[data-testid="chart"]')!.textContent).toBe(
      [
        'settings.analytics.insights.options.reaction.thanks=2',
        'settings.analytics.insights.options.reaction.reAsk=1',
        'settings.analytics.insights.options.reaction.pushbackOrComplaint=0.75',
      ].join(','),
    );
    const badge = container.querySelector<HTMLElement>('button[data-variant]')!;
    expect(badge.dataset.variant).toBe('neutral');
  });

  it('waits for enough replies before drawing implicit feedback', () => {
    act(() => root.render(<ImplicitFeedbackPanel data={insights(4)} />));
    expect(container.querySelector('[data-testid="chart"]')).toBeNull();
    expect(container.textContent).toContain(
      'settings.analytics.insights.notEnoughReplies',
    );
  });

  it('says how wide an estimated range is when the badge gets focus', async () => {
    act(() => root.render(<TierBadge tier="estimated" points={12} />));
    const badge = container.querySelector<HTMLButtonElement>('button')!;
    expect(badge.type).toBe('button');
    expect(badge.className).toContain('focus-visible:ring-3');
    expect(badge.className).toContain('cursor-help');
    await act(async () => badge.focus());
    expect(document.body.textContent).toContain(
      'settings.analytics.insights.tiers.estimatedHint(12)',
    );
  });

  it('marks experimental figures in amber', () => {
    act(() => root.render(<TierBadge tier="experimental" />));
    const badge = container.querySelector<HTMLElement>('button')!;
    expect(badge.dataset.variant).toBe('warning');
    expect(badge.textContent).toBe(
      'settings.analytics.insights.tiers.experimental',
    );
  });

  it('draws each bar to its rate and its whisker over the range, hidden from assistive tech', () => {
    act(() =>
      root.render(
        <IntervalBars
          ariaLabel="Request type"
          rows={[
            {
              key: 'how-to',
              label: 'How-to',
              value: { rate: 0.38, low: 0.31, high: 0.45 },
            },
            { key: 'tag', label: 'Pricing question', ownerText: true },
          ]}
        />,
      ),
    );
    const list = container.querySelector('[role="list"]')!;
    expect(list.getAttribute('aria-label')).toBe('Request type');
    const [howTo, tag] = Array.from(list.querySelectorAll('li'));
    const track = howTo.querySelector<HTMLElement>('.bg-muted')!;
    expect(track.style.getPropertyValue('--rate')).toBe('38%');
    expect(track.style.getPropertyValue('--low')).toBe('31%');
    expect(track.style.getPropertyValue('--high')).toBe('45%');
    expect(track.querySelector('.bg-chart-1')).not.toBeNull();
    expect(track.querySelectorAll('.bg-foreground\\/70')).toHaveLength(3);
    expect(howTo.textContent).toContain('38%');
    expect(howTo.textContent).toContain('31–45%');
    // A row with no figure yet: a dash, no bar, its owner text whole in `title`.
    expect(tag.textContent).toContain('—');
    expect(tag.querySelector('.bg-chart-1')).toBeNull();
    expect(tag.querySelector('[title="Pricing question"]')).not.toBeNull();
  });

  it('puts the label on its own line on a phone and beside the track from sm', () => {
    act(() =>
      root.render(
        <IntervalBars
          ariaLabel="Request type"
          rows={[
            {
              key: 'how-to',
              label: 'How-to',
              value: { rate: 0.38, low: 0.31, high: 0.45 },
            },
          ]}
        />,
      ),
    );
    const row = container.querySelector('li')!;
    expect(row.className.split(' ')).toEqual(
      expect.arrayContaining(['flex-col', 'sm:flex-row', 'sm:h-7']),
    );
    const label = row.firstElementChild as HTMLElement;
    expect(label.className).toContain('truncate');
    expect(label.className).toContain('sm:w-40');
    expect(label.className).not.toMatch(/(^|\s)w-28/);
  });
});
