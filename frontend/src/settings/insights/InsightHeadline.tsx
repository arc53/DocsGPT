import type { CSSProperties } from 'react';
import { ArrowDown, ArrowUp, Equal } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { cn } from '@/lib/utils';

import { formatShare, type MixTone, type PeriodChange } from './format';

export type { MixTone };

const TONE_CLASS: Record<MixTone, string> = {
  success: 'bg-success',
  warning: 'bg-warning',
  destructive: 'bg-destructive',
  info: 'bg-info',
  muted: 'bg-muted-foreground',
};

export type MixPart = {
  key: string;
  label: string;
  /** The part's share of the period, 0–1. */
  share: number;
  tone: MixTone;
};

const CHANGE_ICON = { up: ArrowUp, down: ArrowDown, same: Equal };

/** Under this share a part has no visible width, so the strip leaves it out. */
const MIN_STRIP_SHARE = 0.005;

type InsightHeadlineProps = {
  /** The period's figure, formatted. */
  value: string;
  /** What the figure is ("Fully answered"). */
  label: string;
  /** What it is a share of ("of 52 questions"). */
  sub: string;
  change: PeriodChange | null;
  /**
   * The period's whole mix as a strip and its legend: the legend names the
   * chart's series too, in the same colours, so the chart draws none.
   */
  mix?: MixPart[];
};

/**
 * A chart panel's headline: the period's figure, what it is a share of, how
 * it moved against the previous period of the same length, and optionally
 * the whole mix as one strip.
 */
export default function InsightHeadline({
  value,
  label,
  sub,
  change,
  mix,
}: InsightHeadlineProps) {
  const { t } = useTranslation();
  const ChangeIcon = change ? CHANGE_ICON[change.direction] : null;
  return (
    <div className="flex flex-col gap-3" data-testid="insight-headline">
      <div className="flex flex-wrap items-end gap-x-3 gap-y-1">
        <p className="text-2xl font-bold tabular-nums">{value}</p>
        <div className="flex min-w-0 flex-col pb-0.5">
          <p className="text-sm">{label}</p>
          <p className="text-muted-foreground text-xs">{sub}</p>
        </div>
        {change && ChangeIcon && (
          <p
            className="text-muted-foreground ml-auto flex items-center gap-1 pb-0.5 text-xs tabular-nums"
            data-direction={change.direction}
          >
            <ChangeIcon className="size-3.5" aria-hidden="true" />
            {t('settings.analytics.insights.headline.previous', {
              value: formatShare(change.previous),
              interpolation: { escapeValue: false },
            })}
          </p>
        )}
      </div>
      {mix && (
        <>
          <div
            aria-hidden="true"
            className="flex h-2 gap-0.5 overflow-hidden rounded-full"
          >
            {mix
              .filter((part) => part.share >= MIN_STRIP_SHARE)
              .map((part) => (
                <span
                  key={part.key}
                  className={cn(
                    'h-full grow-(--share) basis-0',
                    TONE_CLASS[part.tone],
                  )}
                  style={{ '--share': part.share } as CSSProperties}
                />
              ))}
          </div>
          <ul
            role="list"
            className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs"
          >
            {mix.map((part) => (
              <li key={part.key} className="flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className={cn('size-2 rounded-full', TONE_CLASS[part.tone])}
                />
                {part.label}
                <span className="text-foreground tabular-nums">
                  {formatShare(part.share)}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
