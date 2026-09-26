import * as React from 'react';
import { useTranslation } from 'react-i18next';
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from 'lucide-react';

import { cn } from '@/lib/utils';

import { Button } from './button';
import { IconButton } from './icon-button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './select';

const DEFAULT_PAGE_SIZE_OPTIONS = [5, 10, 20, 50];

type PaginationProps = {
  /** 1-based. */
  page: number;
  pageCount: number;
  onPageChange: (page: number) => void;
  /** Shows the "Rows per page" select. */
  pageSize?: number;
  pageSizeOptions?: number[];
  onPageSizeChange?: (size: number) => void;
  /** A count on the left ("1,024 users"); the row then spreads to both ends. */
  summary?: React.ReactNode;
  /** Four chevron buttons, or Previous / Next text buttons. */
  labels?: 'icons' | 'text';
  className?: string;
};

/** The pager under a table, a tile grid or a list. */
function Pagination({
  page,
  pageCount,
  onPageChange,
  pageSize,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
  onPageSizeChange,
  summary,
  labels = 'icons',
  className,
}: PaginationProps) {
  const { t } = useTranslation();
  const atStart = page <= 1;
  const atEnd = page >= pageCount;
  const goTo = (next: number) =>
    onPageChange(Math.min(Math.max(next, 1), Math.max(pageCount, 1)));

  return (
    <div
      data-slot="pagination"
      className={cn(
        'mt-2 flex items-center gap-4 p-2 text-xs',
        summary ? 'justify-between' : 'justify-end',
        className,
      )}
    >
      {summary ? (
        <p className="text-muted-foreground text-sm">{summary}</p>
      ) : null}
      <div className="flex items-center gap-4">
        {pageSize !== undefined ? (
          <div className="flex items-center gap-2">
            <span className="text-foreground">
              {t('pagination.rowsPerPage')}:
            </span>
            <Select
              value={String(pageSize)}
              onValueChange={(value) => onPageSizeChange?.(Number(value))}
            >
              <SelectTrigger size="sm" aria-label={t('pagination.rowsPerPage')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {pageSizeOptions.map((option) => (
                  <SelectItem key={option} value={String(option)}>
                    {option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ) : null}
        <div className="text-foreground">
          {t('pagination.pageOf', {
            currentPage: page,
            totalPages: Math.max(pageCount, 1),
          })}
        </div>
        {labels === 'text' ? (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={atStart}
              onClick={() => goTo(page - 1)}
            >
              {t('pagination.previousPage')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={atEnd}
              onClick={() => goTo(page + 1)}
            >
              {t('pagination.nextPage')}
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <IconButton
              variant="outline"
              size="icon-xs"
              disabled={atStart}
              onClick={() => goTo(1)}
              label={t('pagination.firstPage')}
              icon={ChevronsLeft}
            />
            <IconButton
              variant="outline"
              size="icon-xs"
              disabled={atStart}
              onClick={() => goTo(page - 1)}
              label={t('pagination.previousPage')}
              icon={ChevronLeft}
            />
            <IconButton
              variant="outline"
              size="icon-xs"
              disabled={atEnd}
              onClick={() => goTo(page + 1)}
              label={t('pagination.nextPage')}
              icon={ChevronRight}
            />
            <IconButton
              variant="outline"
              size="icon-xs"
              disabled={atEnd}
              onClick={() => goTo(pageCount)}
              label={t('pagination.lastPage')}
              icon={ChevronsRight}
            />
          </div>
        )}
      </div>
    </div>
  );
}

export { Pagination };
export type { PaginationProps };
