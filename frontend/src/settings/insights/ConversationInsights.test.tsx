import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

import type { Agent } from '../../agents/types';
import type { ConversationInsights as Insights } from '../types';
import examples from './fixtures/apiExamples.json';

const store = vi.hoisted(() => ({
  state: { preference: { token: 'token', roles: ['admin'] as string[] } },
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) => selector(store.state),
}));

// Keys with their interpolated values, so copy and figures can be checked.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (!opts) return key;
      // The interpolation options and the plural count are not shown.
      const shown = Object.entries(opts)
        .filter(([name]) => name !== 'interpolation' && name !== 'count')
        .map(([, value]) => value)
        .join('|');
      return shown ? `${key}(${shown})` : key;
    },
    i18n: { language: 'en' },
  }),
}));

// Chart.js needs a canvas; the panel around it is what is tested here.
vi.mock('../AnalyticsChart', () => ({
  default: (props: { data: { datasets: { label: string }[] } }) => (
    <div data-testid="chart">
      {props.data.datasets.map((dataset) => dataset.label).join(',')}
    </div>
  ),
}));
vi.mock('../DocsGaps', () => ({
  default: (props: { hasTopics: boolean; agentId?: string }) => (
    <div
      data-testid="docs-gaps-stub"
      data-has-topics={String(props.hasTopics)}
    />
  ),
}));

import ConversationInsights from './ConversationInsights';
import { insightsState, type InsightsState } from './format';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const option = (expected: number, rate: number, low: number, high: number) => ({
  expected,
  rate,
  low,
  high,
});

const data = (overrides: Partial<Insights> = {}): Insights => ({
  success: true,
  enabled: true,
  available: true,
  coverage: {
    turns: 120,
    labelled_turns: 118,
    replies: 40,
    labelled_replies: 40,
    conversations: 70,
    labelled_conversations: 61,
  },
  languages: { en: 100, ru: 12, other: 6 },
  language_warnings: [],
  tags: [],
  totals: {
    answer_status: {
      tier: 'dashboard',
      n: 104,
      options: {
        'fully answered': option(77, 0.741, 0.66, 0.81),
        'partially answered': option(15, 0.14, 0.09, 0.2),
        'not a request': option(14, 0.12, 0.07, 0.18),
      },
    },
    goal_met: {
      tier: 'dashboard',
      n: 61,
      options: { yes: option(49, 0.81, 0.74, 0.87) },
    },
    frustrated: {
      tier: 'dashboard',
      n: 40,
      options: { yes: option(1.2, 0.03, 0.01, 0.06) },
    },
    asks_human: {
      tier: 'dashboard',
      n: 3,
      options: { yes: option(0.3, 0.1, 0, 0.5) },
    },
    gap_type: {
      tier: 'estimated',
      n: 118,
      options: {
        'docs missing': option(12.1, 0.1, 0.07, 0.14),
        'out of scope': option(5.9, 0.05, 0.02, 0.09),
        'not retrieved': option(0, 0, 0, 0),
        none: option(95, 0.8, 0.75, 0.85),
      },
    },
    request_type: {
      tier: 'estimated',
      n: 118,
      options: {
        other: option(4, 0.03, 0.01, 0.07),
        'how-to': option(45, 0.38, 0.31, 0.45),
        troubleshooting: option(28, 0.24, 0.18, 0.31),
      },
    },
    reaction: {
      tier: 'estimated',
      n: 40,
      options: {
        'thanks or confirmation': option(10, 0.25, 0.14, 0.4),
      },
    },
  },
  series: [
    {
      bucket: '2026-10-19',
      labels: {
        answer_status: { n: 12, options: { 'fully answered': 8.7 } },
        reaction: { n: 4, options: { 'thanks or confirmation': 1.1 } },
      },
    },
  ],
  ...overrides,
});

const agent = (actions: string[]): Agent =>
  ({
    id: 'a1',
    name: 'Fintech bot',
    agent_type: 'classic',
    status: 'published',
    allowed_actions: actions,
  }) as unknown as Agent;

describe('ConversationInsights', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    store.state.preference.roles = ['admin'];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = (
    response: Insights | null,
    {
      status = 'ready',
      agentProp,
      onRetry = () => undefined,
    }: {
      status?: 'loading' | 'error' | 'ready';
      agentProp?: Agent;
      onRetry?: () => void;
    } = {},
  ) => {
    const state: InsightsState = insightsState(status, response);
    act(() =>
      root.render(
        <MemoryRouter>
          <ConversationInsights
            state={state}
            data={response}
            agentId={agentProp?.id}
            agent={agentProp}
            filterOption="last_30_days"
            onRetry={onRetry}
          />
        </MemoryRouter>,
      ),
    );
  };

  const section = () => container.querySelector('[data-testid="insights"]');
  const tile = (key: string) =>
    container.querySelector<HTMLElement>(`[data-testid="insight-${key}"]`)!;

  it('tells an administrator how to turn insights on, and nothing else', () => {
    render(data({ available: false, enabled: false }));
    const note = section()!.querySelector('[role="note"]')!;
    expect(note.textContent).toBe('settings.analytics.insights.serverOff');
    expect(container.querySelector('[data-testid="insight-tiles"]')).toBeNull();
    expect(
      container.querySelector('[data-testid="docs-gaps-stub"]'),
    ).toBeNull();
  });

  it('shows no section to anyone else while the server has it off', () => {
    store.state.preference.roles = [];
    render(data({ available: false, enabled: false }));
    expect(section()).toBeNull();
  });

  it("links an agent's editors to its settings when the agent has it off", () => {
    render(data({ enabled: false }), { agentProp: agent(['view', 'edit']) });
    const note = section()!.querySelector('[role="note"]')!;
    expect(note.textContent).toContain('settings.analytics.insights.agentOff');
    const link = note.querySelector('a')!;
    expect(link.getAttribute('href')).toBe('/agents/manage/edit/a1');
  });

  it("shows nothing about the agent's switch to someone who can't change it", () => {
    render(data({ enabled: false }), { agentProp: agent(['view']) });
    expect(section()).toBeNull();
  });

  it('says when there was no traffic, and when labelling has only started', () => {
    render(
      data({
        coverage: { ...data().coverage, turns: 0, labelled_turns: 0 },
      }),
    );
    expect(section()!.textContent).toContain(
      'settings.analytics.insights.noTraffic',
    );
    render(
      data({
        coverage: { ...data().coverage, turns: 12, labelled_turns: 0 },
      }),
    );
    expect(section()!.textContent).toContain(
      'settings.analytics.insights.startingDescription',
    );
    expect(container.querySelector('[data-testid="insight-tiles"]')).toBeNull();
  });

  it('shows the error with Retry instead of an empty message', () => {
    const onRetry = vi.fn();
    render(null, { status: 'error', onRetry });
    const alert = section()!.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain(
      'settings.analytics.insights.loadError',
    );
    const retry = Array.from(alert.querySelectorAll('button')).find(
      (button) => button.textContent === 'retry',
    )!;
    act(() => retry.click());
    expect(onRetry).toHaveBeenCalled();
  });

  it('shows tile skeletons while loading', () => {
    render(null, { status: 'loading' });
    // Five figure-sized bars in the tiles, then the panels' bars.
    expect(
      section()!.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThanOrEqual(5);
    expect(section()!.textContent).toContain(
      'settings.analytics.insights.stats.fullyAnswered',
    );
  });

  it('counts labelled answers beside the title while some are still waiting', () => {
    render(data());
    const count = section()!.querySelector('[data-slot="count"]')!;
    expect(count.textContent).toBe(
      'settings.analytics.insights.coverage(118|120)',
    );
    render(
      data({
        coverage: { ...data().coverage, turns: 118, labelled_turns: 118 },
      }),
    );
    expect(section()!.querySelector('[data-slot="count"]')).toBeNull();
  });

  it('gives every headline tile a rate, its range and its own denominator', () => {
    render(data());
    expect(tile('fullyAnswered').textContent).toContain('74%');
    expect(tile('fullyAnswered').textContent).toContain(
      'settings.analytics.insights.sub.ofQuestions(104|66–81%)',
    );
    expect(tile('goalMet').textContent).toContain(
      'settings.analytics.insights.sub.ofConversations(61|74–87%)',
    );
    expect(tile('frustrated').textContent).toContain(
      'settings.analytics.insights.sub.ofReplies(40|1–6%)',
    );
    // Docs gaps: an expected count, never decimals, with its range.
    expect(tile('docsGaps').textContent).toContain('12');
    expect(tile('docsGaps').textContent).toContain(
      'settings.analytics.insights.sub.inAnswers(118|8–17)',
    );
    // A hint on each tile, and no badge on any.
    expect(tile('goalMet').title).toBe(
      'settings.analytics.insights.stats.goalMetHint',
    );
    expect(
      container
        .querySelector('[data-testid="insight-tiles"]')!
        .querySelector('[data-slot="badge"]'),
    ).toBeNull();
  });

  it('shows no figure for a tiny sample, only how many so far', () => {
    render(data());
    expect(tile('asksHuman').textContent).toContain('—');
    expect(tile('asksHuman').textContent).toContain(
      'settings.analytics.insights.notEnough(3)',
    );
    expect(tile('asksHuman').textContent).not.toContain('10%');
  });

  it('draws the estimated panels with their badge, and the docs-gap report', () => {
    render(data());
    const badges = Array.from(
      section()!.querySelectorAll<HTMLElement>('button[data-variant]'),
    );
    expect(badges.map((badge) => badge.textContent)).toEqual([
      'settings.analytics.insights.tiers.estimated',
      'settings.analytics.insights.tiers.estimated',
    ]);
    expect(badges.every((badge) => badge.dataset.variant === 'neutral')).toBe(
      true,
    );
    const lists = section()!.querySelectorAll('[role="list"]');
    // Request type sits beside the chart, then why not fully answered.
    expect(lists[0].getAttribute('aria-label')).toBe(
      'settings.analytics.insights.panels.requestType',
    );
    const whyNot = lists[1];
    expect(whyNot.getAttribute('aria-label')).toBe(
      'settings.analytics.insights.panels.whyNot',
    );
    // "none" and zero-mass deferred types are not drawn; docs missing reads
    // as "or not found" while search misses carry no mass.
    expect(
      Array.from(whyNot.querySelectorAll('li')).map((li) =>
        li.getAttribute('aria-label'),
      ),
    ).toEqual([
      'settings.analytics.insights.panels.barLabel(settings.analytics.insights.options.gapType.docsMissing|10%|7%|14%)',
      'settings.analytics.insights.panels.barLabel(settings.analytics.insights.options.gapType.outOfScope|5%|2%|9%)',
    ]);
    const requests = Array.from(lists[0].querySelectorAll('li')).map((li) =>
      li.getAttribute('aria-label'),
    );
    expect(requests[0]).toContain('requestType.howTo');
    expect(requests[2]).toContain('requestType.other');
    expect(
      container.querySelector('[data-testid="docs-gaps-stub"]'),
    ).not.toBeNull();
  });

  it('draws answer status as four outcomes, greetings left out', () => {
    render(data());
    expect(
      container
        .querySelector('[data-testid="insight-answer-status"]')!
        .querySelector('[data-testid="chart"]')!.textContent,
    ).toBe(
      [
        'settings.analytics.insights.options.answerStatus.fullyAnswered',
        'settings.analytics.insights.options.answerStatus.partiallyAnswered',
        'settings.analytics.insights.options.answerStatus.declined',
        'settings.analytics.insights.options.answerStatus.clarifying',
      ].join(','),
    );
  });

  it("marks topics experimental and lists an agent's tags, a new one without a figure", () => {
    const response = data({
      tags: [
        { id: 'a1b2c3d4', name: 'Pricing question' },
        { id: 'deadbeef', name: 'Wants a refund' },
      ],
    });
    response.totals.topic_effective = {
      tier: 'experimental',
      n: 118,
      options: {
        'none of these': option(13, 0.11, 0.06, 0.18),
        installation: option(36, 0.31, 0.23, 0.39),
      },
    };
    response.totals['tag:a1b2c3d4'] = {
      tier: 'dashboard',
      n: 61,
      options: { yes: option(13, 0.22, 0.13, 0.33) },
    };
    render(response, { agentProp: agent(['view', 'edit']) });
    const experimental = Array.from(
      section()!.querySelectorAll<HTMLElement>('button[data-variant]'),
    ).filter((badge) => badge.dataset.variant === 'warning');
    expect(experimental.map((badge) => badge.textContent)).toEqual([
      'settings.analytics.insights.tiers.experimental',
    ]);
    const lists = Array.from(section()!.querySelectorAll('[role="list"]'));
    const topics = lists.find(
      (list) =>
        list.getAttribute('aria-label') ===
        'settings.analytics.insights.panels.topic',
    )!;
    const topicRows = Array.from(topics.querySelectorAll('li'));
    expect(topicRows[0].textContent).toContain('installation');
    expect(topicRows[0].querySelector('[title="installation"]')).not.toBeNull();
    expect(topicRows[1].textContent).toContain(
      'settings.analytics.insights.panels.noneOfThese',
    );
    const tags = lists.find(
      (list) =>
        list.getAttribute('aria-label') ===
        'settings.analytics.insights.panels.tags',
    )!;
    const tagRows = Array.from(tags.querySelectorAll('li'));
    expect(tagRows[0].textContent).toContain('22%');
    expect(tagRows[1].textContent).toContain('—');
    expect(tagRows[1].getAttribute('aria-label')).toBe(
      'settings.analytics.insights.panels.barLabelNone(Wants a refund)',
    );
    expect(
      container
        .querySelector('[data-testid="docs-gaps-stub"]')!
        .getAttribute('data-has-topics'),
    ).toBe('true');
  });

  it('says once when weaker languages make some labels less reliable', () => {
    render(data({ language_warnings: ['answer_status', 'topic_effective'] }));
    const notes = section()!.querySelectorAll('[role="note"]');
    expect(notes).toHaveLength(1);
    expect(notes[0].textContent).toBe(
      'settings.analytics.insights.languageNote(15%|Russian and settings.analytics.insights.otherLanguages|Settings.analytics.insights.labelNamesInline.answer_status and settings.analytics.insights.labelNamesInline.topic_effective)',
    );
    render(data());
    expect(section()!.querySelector('[role="note"]')).toBeNull();
  });

  it("reads the server's own response: small samples show no figure yet", () => {
    render(examples.insights as unknown as Insights, {
      agentProp: agent(['view', 'edit']),
    });
    expect(tile('fullyAnswered').textContent).toContain(
      'settings.analytics.insights.notEnough(3)',
    );
    expect(tile('docsGaps').textContent).toContain(
      'settings.analytics.insights.notEnough(4)',
    );
    // Only the tags panel lists rows under the floor: each tag says "—".
    const lists = section()!.querySelectorAll('[role="list"]');
    expect(lists).toHaveLength(1);
    expect(lists[0].textContent).toContain('Pricing question');
    expect(lists[0].textContent).toContain('—');
    expect(
      section()!.textContent!.match(
        /settings\.analytics\.insights\.notEnoughShort/g,
      )!.length,
    ).toBe(4);
    expect(section()!.querySelector('[role="note"]')!.textContent).toContain(
      'Russian',
    );
  });
});
