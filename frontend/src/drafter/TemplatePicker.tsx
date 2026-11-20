import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import SearchInput from '../components/SearchInput';
import { Button } from '../components/ui/button';
import { EmptyState } from '../components/ui/empty-state';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import SuggestionRows, { suggestionIconClass } from '../hero/SuggestionRows';
import { shownFilters } from '../hooks/useUrlFilter';
import {
  DRAFTER_STARTERS,
  type DrafterStarter,
  type TemplateCategory,
} from './starters';

/** How many rows show before Show more, and how many more it adds. */
const PAGE = 12;

type CategoryFilter = 'all' | TemplateCategory;

/**
 * Every template the drafter can start from, for the Templates step: a
 * search over titles and descriptions, a category track (drawn only while a
 * category would narrow the list) and the rows, two columns from `sm`, the
 * first twelve then Show more.
 *
 * Args:
 *   onPick: Starts the picked template.
 *   asks: The rows send (the drawer's arrow up) rather than open a page.
 */
export function TemplatePicker({
  onPick,
  asks = false,
}: {
  onPick: (key: DrafterStarter) => void;
  asks?: boolean;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<CategoryFilter>('all');
  const [shown, setShown] = useState(PAGE);

  const needle = query.trim().toLowerCase();
  const matching = DRAFTER_STARTERS.filter(
    ({ key }) =>
      !needle ||
      [
        t(`drafter.starters.${key}.title`),
        t(`drafter.starters.${key}.description`),
      ].some((text) => text.toLowerCase().includes(needle)),
  );
  // Each category counts with the search applied.
  const categories: CategoryFilter[] = [
    'all',
    ...new Set(DRAFTER_STARTERS.map((entry) => entry.category)),
  ];
  const counts = Object.fromEntries(
    categories.map((value) => [
      value,
      value === 'all'
        ? matching.length
        : matching.filter((entry) => entry.category === value).length,
    ]),
  ) as Record<CategoryFilter, number>;
  const filters = shownFilters(categories, category, counts);
  const listed = matching.filter(
    (entry) => category === 'all' || entry.category === category,
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <SearchInput
          placeholder={t('drafter.templates.search')}
          labelSurface="card"
          className="sm:w-64"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setShown(PAGE);
          }}
        />
        {filters.length > 0 && (
          <ToggleGroup
            type="single"
            value={category}
            onValueChange={(next) => {
              if (!next) return;
              setCategory(next as CategoryFilter);
              setShown(PAGE);
            }}
            aria-label={t('drafter.templates.categoriesLabel')}
          >
            {filters.map((value) => (
              <ToggleGroupItem key={value} value={value}>
                {t(`drafter.templates.categories.${value}`)}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )}
      </div>
      {listed.length === 0 ? (
        <EmptyState
          size="xs"
          illustration="none"
          title={t('drafter.templates.empty')}
        />
      ) : (
        <SuggestionRows
          label={t('drafter.templates.title')}
          className="-mx-3 grid grid-cols-1 sm:grid-cols-2"
          rows={listed.slice(0, shown).map(({ key, Icon }) => ({
            key,
            icon: <Icon className={suggestionIconClass} aria-hidden="true" />,
            text: t(`drafter.starters.${key}.title`),
            description: t(`drafter.starters.${key}.description`),
            asks,
            onSelect: () => onPick(key),
          }))}
        />
      )}
      {listed.length > shown && (
        <Button
          type="button"
          variant="link"
          size="inline"
          className="self-start"
          onClick={() => setShown((count) => count + PAGE)}
        >
          {t('drafter.templates.showMore')}
        </Button>
      )}
    </div>
  );
}
