import { ArrowUp, ChevronRight } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { ListRow } from '../components/ui/list-row';
import { cn } from '../lib/utils';

export const suggestionIconClass = 'text-muted-foreground size-4 shrink-0';

export type SuggestionRow = {
  key: string;
  icon: ReactNode;
  text: string;
  /** Sends `text` as a question; otherwise the row opens something. */
  asks: boolean;
  onSelect: () => void;
};

/**
 * The empty chat's suggestion rows (`ListRow size="md"`): a question row
 * shows the send arrow on hover and focus, a row that opens a page ends in
 * a chevron.
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
          interactive
          asChild
          className="group/row"
          leading={icon}
          title={text}
          trailing={
            asks ? (
              <ArrowUp
                className={cn(
                  suggestionIconClass,
                  'opacity-0 transition-opacity group-focus-within/row:opacity-100 group-hover/row:opacity-100',
                )}
              />
            ) : (
              <ChevronRight className={suggestionIconClass} />
            )
          }
        >
          <button type="button" data-suggestion={key} onClick={onSelect} />
        </ListRow>
      ))}
    </ul>
  );
}
