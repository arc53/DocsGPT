import { ArrowRight, ArrowUp } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { ListRow } from '../components/ui/list-row';
import { cn } from '../lib/utils';

/** A row's icons; `mt-0.5` keeps them on the first line of a wrapped row. */
export const suggestionIconClass =
  'text-muted-foreground mt-0.5 size-4 shrink-0';

/** The end icon waits for hover or focus, but a touch screen has no hover. */
const trailingIconClass = cn(
  suggestionIconClass,
  'opacity-0 transition-opacity group-focus-within/row:opacity-100 group-hover/row:opacity-100 pointer-coarse:opacity-100',
);

export type SuggestionRow = {
  key: string;
  icon: ReactNode;
  text: string;
  /** Sends `text` as a question; otherwise the row opens something. */
  asks: boolean;
  onSelect: () => void;
};

/**
 * The empty chat's suggestion rows (`ListRow size="md" wrap`): on hover and
 * focus a question row shows the send arrow (up), a row that opens a page an
 * arrow right. The text wraps rather than cuts, so it needs no tooltip.
 */
export default function SuggestionRows({
  rows,
  className,
}: {
  rows: SuggestionRow[];
  className?: string;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) return null;
  return (
    <ul
      aria-label={t('hero.suggestions.label')}
      className={cn('flex flex-col', className)}
      data-testid="hero-suggestions"
    >
      {rows.map(({ key, icon, text, asks, onSelect }) => (
        <ListRow
          key={key}
          size="md"
          wrap
          interactive
          asChild
          className="group/row"
          leading={icon}
          title={text}
          trailing={
            asks ? (
              <ArrowUp className={trailingIconClass} />
            ) : (
              <ArrowRight className={trailingIconClass} />
            )
          }
        >
          <button type="button" data-suggestion={key} onClick={onSelect} />
        </ListRow>
      ))}
    </ul>
  );
}
