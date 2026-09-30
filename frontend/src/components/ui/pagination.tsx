import * as React from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, ChevronRight } from 'lucide-react';

import { cn } from '@/lib/utils';
import { formatCount } from '@/utils/dateTimeUtils';

import { Button } from './button';
import { IconButton } from './icon-button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './select';

/** Multiples of 12, so a full page of tiles fills 1, 2, 3 or 4 columns. */
const DEFAULT_PAGE_SIZE_OPTIONS = [12, 24, 48];

/** The 1-based items on the current page, and the list's total. */
type PageRange = { from: number; to: number; total: number };

type PaginationProps = {
  /** 1-based. */
  page: number;
  pageSize: number;
  /** The item count across every page. */
  total: number;
  onPageChange: (page: number) => void;
  /** Shows the page-size select. */
  onPageSizeChange?: (size: number) => void;
  pageSizeOptions?: number[];
  /** Names the size select; "Per page" by default. */
  pageSizeLabel?: string;
  /** The wide summary with the list's noun ("1–12 of 86 sources"). */
  rangeLabel?: (range: PageRange) => React.ReactNode;
  className?: string;
};

type PageSlot = number | 'ellipsis';

/**
 * The page numbers to show: five slots from six pages on, keeping the first,
 * the last and the current page; an ellipsis always hides two pages or more.
 *
 * Args:
 *   page: The current page, 1-based.
 *   count: The number of pages.
 *
 * Returns:
 *   Page numbers and ellipses, in order.
 */
function pageSlots(page: number, count: number): PageSlot[] {
  if (count <= 5) return Array.from({ length: count }, (_, i) => i + 1);
  const middle = Math.min(Math.max(page, 3), count - 2);
  return [
    1,
    middle > 3 ? 'ellipsis' : 2,
    middle,
    middle < count - 2 ? 'ellipsis' : count - 1,
    count,
  ];
}

/**
 * The i18n params for a plural range key: `count` stays numeric so i18next
 * picks the form, and every shown number is formatted.
 *
 * Args:
 *   range: The range Pagination hands to `rangeLabel`.
 *
 * Returns:
 *   `{ count, formatted, from, to }` for keys like `{{from}}–{{to}} of {{formatted}} sources`.
 */
function pageRangeParams({ from, to, total }: PageRange) {
  return {
    count: total,
    formatted: formatCount(total),
    from: formatCount(from),
    to: formatCount(to),
  };
}

/**
 * The pager under a table, a tile grid or a list: a range summary, the
 * optional page-size select and numbered pages; a compact "‹ 2 / 8 ›" row
 * when its own width is under 36rem (a phone, a side panel). Draws nothing
 * while every item fits on the smallest page.
 */
function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
  pageSizeLabel,
  rangeLabel,
  className,
}: PaginationProps) {
  const { t } = useTranslation();
  const withSize = onPageSizeChange !== undefined;
  // With a size select the pager stays while a smaller size would page, so
  // picking a bigger size never hides the way back.
  const smallest = withSize ? Math.min(...pageSizeOptions) : pageSize;
  if (total <= smallest) return null;

  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(Math.max(page, 1), pageCount);
  const range = {
    from: (current - 1) * pageSize + 1,
    to: Math.min(total, current * pageSize),
    total,
  };
  const shortRange = t('pagination.range', {
    from: formatCount(range.from),
    to: formatCount(range.to),
    total: formatCount(total),
  });
  const sizeLabel = pageSizeLabel ?? t('pagination.perPage');
  const goTo = (next: number) =>
    onPageChange(Math.min(Math.max(next, 1), pageCount));

  const step = (direction: -1 | 1, variant: 'ghost' | 'outline') => (
    <IconButton
      variant={variant}
      size="icon-sm"
      disabled={direction < 0 ? current <= 1 : current >= pageCount}
      onClick={() => goTo(current + direction)}
      label={t(
        direction < 0 ? 'pagination.previousPage' : 'pagination.nextPage',
      )}
      icon={direction < 0 ? ChevronLeft : ChevronRight}
    />
  );

  return (
    <nav
      data-slot="pagination"
      aria-label={t('pagination.label')}
      className={cn('@container mt-2 text-sm', className)}
    >
      <div
        data-slot="pagination-full"
        className="hidden items-center justify-between gap-4 p-2 @xl:flex"
      >
        <p className="text-muted-foreground tabular-nums">
          {rangeLabel ? rangeLabel(range) : shortRange}
        </p>
        <div className="flex items-center gap-4">
          {withSize ? (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-foreground">{sizeLabel}</span>
              <Select
                value={String(pageSize)}
                onValueChange={(value) => onPageSizeChange(Number(value))}
              >
                <SelectTrigger size="sm" aria-label={sizeLabel}>
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
          {pageCount > 1 ? (
            <div className="flex items-center gap-1">
              {step(-1, 'ghost')}
              {pageSlots(current, pageCount).map((slot, index) =>
                slot === 'ellipsis' ? (
                  <span
                    key={`ellipsis-${index}`}
                    aria-hidden="true"
                    className="text-muted-foreground inline-flex size-8 items-center justify-center"
                  >
                    …
                  </span>
                ) : (
                  <Button
                    key={slot}
                    variant={slot === current ? 'outline' : 'ghost'}
                    size="icon-sm"
                    className="tabular-nums"
                    aria-current={slot === current ? 'page' : undefined}
                    aria-label={t('pagination.goToPage', { page: slot })}
                    onClick={() => goTo(slot)}
                  >
                    {slot}
                  </Button>
                ),
              )}
              {step(1, 'ghost')}
            </div>
          ) : null}
        </div>
      </div>
      <div
        data-slot="pagination-compact"
        className="flex items-center justify-between gap-4 p-2 @xl:hidden"
      >
        <p className="text-muted-foreground tabular-nums">{shortRange}</p>
        {pageCount > 1 ? (
          <div className="flex items-center gap-2">
            {step(-1, 'outline')}
            <span className="min-w-12 text-center tabular-nums">
              <span aria-hidden="true">
                {current} / {pageCount}
              </span>
              <span className="sr-only">
                {t('pagination.pageOf', {
                  currentPage: current,
                  totalPages: pageCount,
                })}
              </span>
            </span>
            {step(1, 'outline')}
          </div>
        ) : null}
      </div>
    </nav>
  );
}

export { Pagination, pageRangeParams, pageSlots };
export type { PageRange, PaginationProps };
