/**
 * Pure helpers for conversation insights: the section's state, the model's
 * option keys mapped to translation keys, and how a rate or an expected
 * count reads. Every figure the model produces is a rate or a rounded
 * expected count, never a thresholded tally; the API also sends each rate's
 * range, which only the CSV export carries.
 */
import {
  EMPTY_VALUE,
  formatCount,
  intlLocale,
} from '../../utils/dateTimeUtils';
import type { ConversationInsights, InsightLabelTotals } from '../types';

/**
 * Below this many labelled items a figure is not shown: its 95% range spans
 * most of 0–100%, so any number would read as a finding when it is noise.
 */
export const MIN_SAMPLE = 10;

export type InsightsFetchStatus = 'loading' | 'error' | 'ready';

export type InsightsState =
  | 'loading'
  | 'error'
  | 'serverOff'
  | 'agentOff'
  | 'noTraffic'
  | 'starting'
  | 'partial'
  | 'ready';

/** What the insights section shows, from the fetch and its response. */
export function insightsState(
  status: InsightsFetchStatus,
  data: ConversationInsights | null,
): InsightsState {
  if (status === 'loading') return 'loading';
  if (status === 'error' || !data?.success) return 'error';
  if (!data.available) return 'serverOff';
  if (!data.enabled) return 'agentOff';
  const { turns, labelled_turns } = data.coverage;
  if (turns === 0) return 'noTraffic';
  if (labelled_turns === 0) return 'starting';
  return labelled_turns < turns ? 'partial' : 'ready';
}

/** States with figures: the tiles, the panels and the docs-gap report. */
export function showsFigures(state: InsightsState): boolean {
  return state === 'partial' || state === 'ready';
}

/** The catch-all option of the topic question. */
export const NONE_OF_THESE = 'none of these';

/**
 * Model option (a fixed English key from the API) to its key under
 * `settings.analytics.insights.options`. An option missing here (a newer
 * model) reads as its raw key.
 */
export const OPTION_KEYS: Record<string, Record<string, string>> = {
  answer_status: {
    'fully answered': 'answerStatus.fullyAnswered',
    'partially answered': 'answerStatus.partiallyAnswered',
    'declined, no information': 'answerStatus.declined',
    'asked a clarifying question': 'answerStatus.clarifying',
  },
  gap_type: {
    'docs missing': 'gapType.docsMissing',
    'not retrieved': 'gapType.notRetrieved',
    'answer missed': 'gapType.answerMissed',
    'out of scope': 'gapType.outOfScope',
    'feature not supported': 'gapType.featureNotSupported',
    'needs account data': 'gapType.needsAccountData',
    'ambiguous question': 'gapType.ambiguous',
    'confidently ungrounded': 'gapType.confidentlyUngrounded',
    other: 'gapType.other',
  },
  reaction: {
    'thanks or confirmation': 'reaction.thanks',
    're-ask': 'reaction.reAsk',
    'correction or pushback': 'reaction.pushbackOrComplaint',
    complaint: 'reaction.pushbackOrComplaint',
  },
  request_type: {
    troubleshooting: 'requestType.troubleshooting',
    'how-to': 'requestType.howTo',
    lookup: 'requestType.lookup',
    concept: 'requestType.concept',
    comparison: 'requestType.comparison',
    'feature request': 'requestType.featureRequest',
    'account or billing': 'requestType.accountBilling',
    'chit-chat': 'requestType.chitChat',
    other: 'requestType.other',
  },
  sentiment: {
    positive: 'sentiment.positive',
    neutral: 'sentiment.neutral',
    negative: 'sentiment.negative',
  },
};

/** The four answer outcomes drawn over time, in order; greetings are left out. */
export const ANSWER_STATUS_SERIES = [
  'fully answered',
  'partially answered',
  'declined, no information',
  'asked a clarifying question',
] as const;

/** Sentiment drawn over time, in order: green, grey, red from the bottom. */
export const SENTIMENT_SERIES = ['positive', 'neutral', 'negative'] as const;

/** Implicit feedback's three series and the reaction options each sums. */
export const REACTION_SERIES = {
  thanks: ['thanks or confirmation'],
  reAsk: ['re-ask'],
  pushbackOrComplaint: ['correction or pushback', 'complaint'],
} as const;

type Translate = (key: string, options?: Record<string, unknown>) => string;

/** A model option's display name, or its raw key when it has none. */
export function optionName(t: Translate, label: string, option: string) {
  const key = OPTION_KEYS[label]?.[option];
  return key ? t(`settings.analytics.insights.options.${key}`) : option;
}

const percentFormat = (locale: string) =>
  new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 });

/** A rate as a whole percent; under half a percent reads "<1%". */
export function formatShare(rate: number, locale = intlLocale()): string {
  if (!Number.isFinite(rate)) return EMPTY_VALUE;
  const format = percentFormat(locale);
  if (rate > 0 && rate < 0.005) return `<${format.format(0.01)}`;
  return format.format(rate);
}

/**
 * An expected count (a sum of probabilities) as a whole number: "6.2 gaps"
 * would claim a precision the estimate does not have. Under one half reads
 * "<1", so a small but real mass is not shown as nothing.
 */
export function formatEstimate(value: number, locale = intlLocale()): string {
  if (!Number.isFinite(value)) return EMPTY_VALUE;
  if (value > 0 && value < 0.5) return `<${formatCount(1, locale)}`;
  return formatCount(Math.round(value), locale);
}

/** A row of a share-bar panel; no `rate` draws "—" and an empty track. */
export type BarRow = {
  key: string;
  label: string;
  rate?: number;
};

/**
 * One bar per option, largest rate first, catch-all options last. Options
 * whose expected count rounds to zero are left out: they add rows, not
 * information.
 */
export function optionBars(
  totals: InsightLabelTotals | undefined,
  name: (option: string) => string,
  { skip = [], last = [] }: { skip?: string[]; last?: string[] } = {},
): BarRow[] {
  if (!totals) return [];
  const rows = Object.entries(totals.options)
    .filter(
      ([option, value]) =>
        !skip.includes(option) && Math.round(value.expected) > 0,
    )
    .sort(([a, x], [b, y]) => {
      const lastA = last.includes(a);
      const lastB = last.includes(b);
      if (lastA !== lastB) return lastA ? 1 : -1;
      return y.rate - x.rate;
    });
  return rows.map(([option, value]) => ({
    key: option,
    label: name(option),
    rate: value.rate,
  }));
}

/** Languages the model reads as well as English. */
const STRONG_LANGUAGES = new Set(['en', 'es']);

/**
 * The share of messages in languages the model reads less accurately, and
 * those languages by message count. Chinese counts only while the reaction
 * label is warned about: the other labels read it well.
 */
export function weakLanguages(
  languages: Record<string, number>,
  warnings: string[],
): { share: number; codes: string[] } {
  const total = Object.values(languages).reduce((sum, n) => sum + n, 0);
  const weak = Object.entries(languages).filter(
    ([code, n]) =>
      n > 0 &&
      !STRONG_LANGUAGES.has(code) &&
      (code !== 'zh' || warnings.includes('reaction')),
  );
  const codes = weak
    .sort(([a, x], [b, y]) => {
      if (a === 'other' || b === 'other') return a === 'other' ? 1 : -1;
      return y - x;
    })
    .map(([code]) => code);
  const count = weak.reduce((sum, [, n]) => sum + n, 0);
  return { share: total > 0 ? count / total : 0, codes };
}

/** A language code's name in the UI language; `other` reads as `other`, an unknown code as itself. */
export function languageName(
  code: string,
  locale: string,
  other: string,
): string {
  if (code === 'other') return other;
  try {
    return new Intl.DisplayNames(locale, { type: 'language' }).of(code) ?? code;
  } catch {
    return code;
  }
}

/** Names joined as the locale writes a list ("A, B and C"). */
export function joinList(items: string[], locale = intlLocale()): string {
  return new Intl.ListFormat(locale, { type: 'conjunction' }).format(items);
}

/** The text with its first letter upper-cased, for a list that opens a sentence. */
export function capitalize(text: string, locale = intlLocale()): string {
  return text ? text.charAt(0).toLocaleUpperCase(locale) + text.slice(1) : text;
}

export type GapChange =
  { kind: 'new' } | { kind: 'none' } | { kind: 'up' | 'down'; delta: number };

/** How a docs-gap group moved against the previous period of the same length. */
export function gapChange(expected: number, previous: number): GapChange {
  if (Math.round(previous) === 0 && Math.round(expected) >= 1)
    return { kind: 'new' };
  const delta = Math.round(expected - previous);
  if (delta === 0) return { kind: 'none' };
  return { kind: delta > 0 ? 'up' : 'down', delta: Math.abs(delta) };
}
