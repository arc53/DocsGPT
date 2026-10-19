/**
 * Pure helpers for conversation insights: the section's state, the model's
 * option keys mapped to translation keys, and how a rate, a range or an
 * expected count reads. Every figure the model produces is a rate with its
 * range or a rounded expected count, never a thresholded tally.
 */
import {
  EMPTY_VALUE,
  formatCount,
  intlLocale,
} from '../../utils/dateTimeUtils';
import type {
  ConversationInsights,
  InsightLabelTotals,
  InsightOption,
} from '../types';

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

/** States in which the implicit-feedback panel sits beside the thumbs. */
export function showsImplicitFeedback(state: InsightsState): boolean {
  return showsFigures(state) || state === 'noTraffic';
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
};

/** The four answer outcomes drawn over time, in order; greetings are left out. */
export const ANSWER_STATUS_SERIES = [
  'fully answered',
  'partially answered',
  'declined, no information',
  'asked a clarifying question',
] as const;

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

const NUMBER_PARTS = new Set(['integer', 'group', 'decimal', 'fraction']);

/**
 * A rate's range as whole percents with one sign, as the locale places it
 * ("66–81%", "66–81 %", "%66–81"); one value when both ends round the same.
 * Built from the formatter's parts rather than `formatRange`, whose output
 * differs between engines ("66–81%" or "66% – 81%").
 */
export function formatShareRange(
  low: number,
  high: number,
  locale = intlLocale(),
): string {
  if (!Number.isFinite(low) || !Number.isFinite(high)) return EMPTY_VALUE;
  const lowPct = Math.round(low * 100);
  const highPct = Math.round(high * 100);
  if (lowPct === highPct) return formatShare(low, locale);
  const span = `${formatCount(lowPct, locale)}–${formatCount(highPct, locale)}`;
  let placed = false;
  return percentFormat(locale)
    .formatToParts(highPct / 100)
    .map((part) => {
      if (!NUMBER_PARTS.has(part.type)) return part.value;
      if (placed) return '';
      placed = true;
      return span;
    })
    .join('');
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

/** An expected count's range as whole numbers ("3–10"). */
export function formatEstimateRange(
  low: number,
  high: number,
  locale = intlLocale(),
): string {
  if (!Number.isFinite(low) || !Number.isFinite(high)) return EMPTY_VALUE;
  const lowCount = Math.round(low);
  const highCount = Math.round(high);
  if (lowCount === highCount) return formatCount(lowCount, locale);
  return `${formatCount(lowCount, locale)}–${formatCount(highCount, locale)}`;
}

/**
 * Half the widest drawn range, in percentage points: what an `Estimated`
 * badge says its figures are good to. Undefined with nothing drawn.
 */
export function rangePoints(options: InsightOption[]): number | undefined {
  if (!options.length) return undefined;
  return Math.round(
    Math.max(...options.map((option) => (option.high - option.low) / 2)) * 100,
  );
}

/** A row of an interval-bar panel; no `value` draws "—" and no bar. */
export type BarRow = {
  key: string;
  label: string;
  value?: { rate: number; low: number; high: number };
  /** The label is the owner's text (a topic, a tag), so it carries `title`. */
  ownerText?: boolean;
};

/**
 * One bar per option, largest rate first, catch-all options last. Options
 * whose expected count rounds to zero are left out: they add rows, not
 * information.
 */
export function optionBars(
  totals: InsightLabelTotals | undefined,
  name: (option: string) => string,
  {
    skip = [],
    last = [],
    ownerText = false,
  }: { skip?: string[]; last?: string[]; ownerText?: boolean } = {},
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
    value: { rate: value.rate, low: value.low, high: value.high },
    ownerText: ownerText && !last.includes(option),
  }));
}

/** The drawn options of a bar panel, for its badge's range width. */
export function drawnOptions(
  totals: InsightLabelTotals | undefined,
  rows: BarRow[],
): InsightOption[] {
  if (!totals) return [];
  return rows
    .map((row) => totals.options[row.key])
    .filter((option): option is InsightOption => Boolean(option));
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
