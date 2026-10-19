import type { CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';

import { EMPTY_VALUE } from '../../utils/dateTimeUtils';
import { formatShare, formatShareRange, type BarRow } from './format';

const percent = (value: number) =>
  `${Math.min(100, Math.max(0, value * 100))}%`;

type IntervalBarsProps = {
  /** In display order; the caller sorts and puts catch-all rows last. */
  rows: BarRow[];
  /** The list's accessible name (the panel title). */
  ariaLabel: string;
};

/**
 * Horizontal bars, each with its 95% range drawn as a whisker over the bar
 * and the track, then the rate and the range as text. Each row is one text
 * run for assistive tech ("How-to: 38%, likely 31% to 45%"); the drawing is
 * hidden from it.
 */
export default function IntervalBars({ rows, ariaLabel }: IntervalBarsProps) {
  const { t } = useTranslation();
  return (
    <ul role="list" aria-label={ariaLabel} className="flex flex-col gap-1.5">
      {rows.map((row) => {
        const { value } = row;
        const rowLabel = value
          ? t('settings.analytics.insights.panels.barLabel', {
              name: row.label,
              value: formatShare(value.rate),
              low: formatShare(value.low),
              high: formatShare(value.high),
              interpolation: { escapeValue: false },
            })
          : t('settings.analytics.insights.panels.barLabelNone', {
              name: row.label,
              interpolation: { escapeValue: false },
            });
        return (
          // Below sm the label takes its own line, so the track keeps
          // the row's width; from sm it is a column beside the track.
          <li
            key={row.key}
            aria-label={rowLabel}
            className="flex flex-col gap-1 sm:h-7 sm:flex-row sm:items-center sm:gap-3"
          >
            <span
              aria-hidden="true"
              className="truncate text-xs sm:w-40 sm:shrink-0"
              title={row.ownerText ? row.label : undefined}
            >
              {row.label}
            </span>
            <span
              aria-hidden="true"
              className="flex h-5 min-w-0 flex-1 items-center gap-3 sm:h-auto"
            >
              <span
                className="bg-muted relative h-2 min-w-0 flex-1 rounded-full"
                style={
                  value
                    ? ({
                        '--rate': percent(value.rate),
                        '--low': percent(value.low),
                        '--high': percent(value.high),
                        '--span': percent(value.high - value.low),
                      } as CSSProperties)
                    : undefined
                }
              >
                {value && (
                  <>
                    <span className="bg-chart-1 absolute inset-y-0 left-0 w-(--rate) rounded-full" />
                    <span className="bg-foreground/70 absolute top-1/2 left-(--low) h-px w-(--span) -translate-y-1/2" />
                    <span className="bg-foreground/70 absolute top-1/2 left-(--low) h-2.5 w-px -translate-1/2" />
                    <span className="bg-foreground/70 absolute top-1/2 left-(--high) h-2.5 w-px -translate-1/2" />
                  </>
                )}
              </span>
              <span className="w-10 shrink-0 text-right text-xs tabular-nums">
                {value ? formatShare(value.rate) : EMPTY_VALUE}
              </span>
              <span className="text-muted-foreground w-16 shrink-0 text-right text-xs tabular-nums">
                {value ? formatShareRange(value.low, value.high) : null}
              </span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}
