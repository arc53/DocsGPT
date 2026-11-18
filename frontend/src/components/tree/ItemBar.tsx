import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Card } from '../ui/card';
import { ActionMenu, type MenuOption } from '../ui/dropdown-menu';
import { ListRow, ListRows } from '../ui/list-row';

/**
 * The open file or page of a source view, as a bar above its chunks: the
 * same name, address or size, counts and ⋯ as its table row, so the item
 * keeps its own actions once its row is gone. The source's actions stay in
 * the title row above.
 *
 * @param icon The item's icon (File, or FileText for a page).
 * @param name The item's name (a page's title).
 * @param description The line under the name: a page's address, a file's size.
 * @param meta The counts ("3 chunks · 4,629 tokens · fetched …").
 * @param options The item's actions; none draws no ⋯.
 */
export default function ItemBar({
  icon: Icon,
  name,
  description,
  meta,
  options,
}: {
  icon: LucideIcon;
  name: string;
  description?: ReactNode;
  meta?: string;
  options: MenuOption[];
}) {
  const { t } = useTranslation();
  return (
    <Card variant="subtle" padding="none" data-testid="item-bar">
      <ListRows>
        <ListRow
          leading={
            <Icon
              aria-hidden="true"
              className="text-muted-foreground size-4 shrink-0"
            />
          }
          title={name}
          description={
            description || meta ? (
              <>
                {description}
                {/* On a phone the counts join the line under the name. */}
                {meta ? (
                  <span className="sm:hidden">
                    {description ? ' · ' : ''}
                    {meta}
                  </span>
                ) : null}
              </>
            ) : undefined
          }
          trailing={
            <>
              {meta ? (
                <span className="text-muted-foreground hidden shrink-0 text-xs whitespace-nowrap sm:inline">
                  {meta}
                </span>
              ) : null}
              {options.length > 0 ? (
                <ActionMenu
                  options={options}
                  triggerLabel={t('settings.sources.menuAlt')}
                  className="shrink-0"
                />
              ) : null}
            </>
          }
        />
      </ListRows>
    </Card>
  );
}
