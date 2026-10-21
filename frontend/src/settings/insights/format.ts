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
  | 'analyzing'
  | 'olderOnly'
  | 'failedOnly'
  | 'partial'
  | 'ready';

/**
 * What the insights section shows, from the fetch and its response.
 *
 * The sweep labels only answers inside its window (`backfill_days` back), so
 * an unlabelled answer is either still to come or never labelled; an answer
 * whose labelling failed for good is neither, and is not waited on. While
 * some are still to come and too few are labelled for any figure, the section
 * is `analyzing`; with none labelled and none to come, `failedOnly` when some
 * failed, else `olderOnly`. With figures it is `partial` while some are still
 * to come, else `ready`.
 */
export function insightsState(
  status: InsightsFetchStatus,
  data: ConversationInsights | null,
): InsightsState {
  if (status === 'loading') return 'loading';
  if (status === 'error' || !data?.success) return 'error';
  if (!data.available) return 'serverOff';
  if (!data.enabled) return 'agentOff';
  const { turns, labelled_turns, unlabelled_recent_turns } = data.coverage;
  if (turns === 0) return 'noTraffic';
  if (unlabelled_recent_turns > 0 && labelled_turns < MIN_SAMPLE)
    return 'analyzing';
  if (labelled_turns === 0)
    return (data.coverage.failed_turns ?? 0) > 0 ? 'failedOnly' : 'olderOnly';
  // Complete once nothing inside the labelling window is left: older
  // answers are never labelled, so they never count against it.
  return unlabelled_recent_turns > 0 ? 'partial' : 'ready';
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

/** Replies to answers (the reaction label): three series and the options each sums. */
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
 * A day's expected count as its share of the day's total, for a 100%
 * stacked chart: a column reads as a mix, never as "1.8 replies". A day with
 * nothing to share out is 0, so its column stays empty.
 */
export function shareOfDay(value: number, total: number): number {
  return total > 0 ? Math.min(1, value / total) : 0;
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
  | { kind: 'noEarlier' }
  | { kind: 'new' }
  | { kind: 'none' }
  | { kind: 'up' | 'down'; delta: number };

/**
 * How a docs-gap group moved against the previous period of the same length.
 * While that period has no labelled answers there is nothing to compare
 * with (`noEarlier`), so no group reads as new.
 */
export function gapChange(
  expected: number,
  previous: number,
  previousLabelled = true,
): GapChange {
  if (!previousLabelled) return { kind: 'noEarlier' };
  if (Math.round(previous) === 0 && Math.round(expected) >= 1)
    return { kind: 'new' };
  const delta = Math.round(expected - previous);
  if (delta === 0) return { kind: 'none' };
  return { kind: delta > 0 ? 'up' : 'down', delta: Math.abs(delta) };
}

/** What a page title's site tail starts with ("Install | DocsGPT Docs"). */
const TAIL_SEPARATORS = [' | ', ' – ', ' — ', ' · '];

/**
 * The longest separator-led tail every name ends with, leaving each name
 * some text; '' for fewer than two names or none shared.
 */
function sharedTail(names: string[]): string {
  if (names.length < 2) return '';
  const [first] = names;
  let best = '';
  for (const separator of TAIL_SEPARATORS) {
    for (
      let at = first.indexOf(separator);
      at > 0;
      at = first.indexOf(separator, at + 1)
    ) {
      const tail = first.slice(at);
      if (
        tail.length > best.length &&
        names.every((name) => name.length > tail.length && name.endsWith(tail))
      )
        best = tail;
    }
  }
  return best;
}

type PageRow = {
  key: string | null;
  name: string | null;
  source: string | null;
};

/**
 * Docs-gap page names without the site tail they all repeat
 * (" | DocsGPT Docs"): the tail every titled row shares, else the tail the
 * titled rows of each source share. A page named by its URL (no title) is
 * left as it is and does not count.
 */
export function pageNames(rows: PageRow[]): (string | null)[] {
  const titled = (row: PageRow) => Boolean(row.name) && row.name !== row.key;
  const names = rows.map((row) => row.name);
  const strip = (indexes: number[]) => {
    const tail = sharedTail(indexes.map((index) => names[index] as string));
    if (!tail) return false;
    for (const index of indexes)
      names[index] = (names[index] as string).slice(0, -tail.length);
    return true;
  };
  const all = rows.flatMap((row, index) => (titled(row) ? [index] : []));
  if (strip(all)) return names;
  const bySource = new Map<string | null, number[]>();
  for (const index of all) {
    const source = rows[index].source;
    bySource.set(source, [...(bySource.get(source) ?? []), index]);
  }
  for (const indexes of bySource.values()) strip(indexes);
  return names;
}
