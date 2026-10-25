import type { CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';

import { Progress } from '@/components/ui/progress';
import { cn } from '@/lib/utils';

import { EMPTY_VALUE } from '../../utils/dateTimeUtils';
import { formatShare, type BarRow } from './format';

type ShareBarsProps = {
  /** In display order; the caller sorts and puts catch-all rows last. */
  rows: BarRow[];
  /** The list's accessible name (the panel title). */
  ariaLabel: string;
  /** 2: from xl the rows fill a left column, then a right one. */
  columns?: 1 | 2;
};

/**
 * One row per option: its label, a Progress bar to its share and the share
 * as a whole percent. A long label wraps rather than being cut. Each row is
 * one text run for assistive tech ("How-to: 38%"); the drawing is hidden
 * from it.
 */
export default function ShareBars({
  rows,
  ariaLabel,
  columns = 1,
}: ShareBarsProps) {
  const { t } = useTranslation();
  return (
    <ul
      role="list"
      aria-label={ariaLabel}
      className={cn(
        'flex flex-col gap-1.5',
        columns === 2 &&
          'xl:grid xl:grid-flow-col xl:grid-cols-2 xl:grid-rows-[repeat(var(--rows),auto)] xl:gap-x-12',
      )}
      style={
        columns === 2
          ? ({ '--rows': Math.ceil(rows.length / 2) } as CSSProperties)
          : undefined
      }
    >
      {rows.map((row) => {
        const { rate } = row;
        const rowLabel =
          rate !== undefined
            ? t('settings.analytics.insights.panels.barLabel', {
                name: row.label,
                value: formatShare(rate),
                interpolation: { escapeValue: false },
              })
            : t('settings.analytics.insights.panels.barLabelNone', {
                name: row.label,
                interpolation: { escapeValue: false },
              });
        return (
          // Below sm the label takes its own line, so the track keeps
          // the row's width; from sm it is a column beside the track, and
          // a label that wraps grows the row.
          <li
            key={row.key}
            className="flex flex-col gap-1 sm:min-h-7 sm:flex-row sm:items-center sm:gap-3"
          >
            <span className="sr-only">{rowLabel}</span>
            <span
              aria-hidden="true"
              className="text-xs wrap-break-word sm:w-40 sm:shrink-0"
            >
              {row.label}
            </span>
            <span
              aria-hidden="true"
              className="flex h-5 min-w-0 flex-1 items-center gap-3 sm:h-auto"
            >
              <Progress
                value={rate !== undefined ? rate * 100 : 0}
                variant={row.tone ?? 'default'}
                className="min-w-0 flex-1"
              />
              <span className="w-10 shrink-0 text-right text-xs tabular-nums">
                {rate !== undefined ? formatShare(rate) : EMPTY_VALUE}
              </span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}
