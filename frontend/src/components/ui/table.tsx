import * as React from 'react';

import { cn } from '@/lib/utils';

type TableProps = React.ComponentProps<'table'> & {
  /** A min-width class; the table scrolls inside TableContainer below it. */
  minWidth?: string;
};

interface TableContainerProps {
  children: React.ReactNode;
  className?: string;
  height?: string;
  bordered?: boolean;
}

// `align` and `width` are the deprecated HTML attributes on th/td; these parts
// take them as a text-alignment choice and a CSS width instead.
type TableCellProps<T extends 'th' | 'td'> = Omit<
  React.ComponentProps<T>,
  'align' | 'width'
> & {
  /** A min-width class for the column. */
  minWidth?: string;
  /** A CSS width that fixes the column (min, max and width). */
  width?: string;
  align?: 'left' | 'right' | 'center';
};

const ALIGN_CLASSES = {
  left: 'text-left',
  right: 'text-right',
  center: 'text-center',
} as const;

const TableContainer = React.forwardRef<HTMLDivElement, TableContainerProps>(
  function TableContainer(
    {
      children,
      className = '',
      height = 'auto',
      bordered = true,
    }: TableContainerProps,
    ref: React.ForwardedRef<HTMLDivElement>,
  ) {
    return (
      <div
        data-slot="table-container"
        className={cn('relative rounded-md', className)}
      >
        <div
          ref={ref}
          className={cn(
            'w-full overflow-x-auto rounded-md bg-transparent',
            bordered && 'border-border border',
            height === 'auto'
              ? 'overflow-y-hidden'
              : 'max-h-(--table-max-height) overflow-y-auto',
          )}
          // The height is a runtime prop; exposed as a custom property so
          // max-height itself stays a class.
          style={
            height === 'auto'
              ? undefined
              : ({ '--table-max-height': height } as React.CSSProperties)
          }
        >
          {children}
        </div>
      </div>
    );
  },
);

function Table({
  className,
  minWidth = 'min-w-[600px]',
  ...props
}: TableProps) {
  return (
    <table
      data-slot="table"
      className={cn(
        'w-full table-auto border-collapse bg-transparent',
        minWidth,
        className,
      )}
      {...props}
    />
  );
}

function TableHead({ className, ...props }: React.ComponentProps<'thead'>) {
  return (
    <thead
      data-slot="table-head"
      className={cn('bg-muted sticky top-0 z-10', className)}
      {...props}
    />
  );
}

function TableBody({ className, ...props }: React.ComponentProps<'tbody'>) {
  return (
    <tbody
      data-slot="table-body"
      className={cn('[&>tr:last-child]:border-b-0', className)}
      {...props}
    />
  );
}

function TableRow({
  className,
  onClick,
  ...props
}: React.ComponentProps<'tr'>) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        'border-border hover:bg-muted border-b',
        onClick && 'cursor-pointer',
        className,
      )}
      onClick={onClick}
      {...props}
    />
  );
}

function TableHeader({
  className,
  minWidth,
  width,
  align = 'left',
  ...props
}: TableCellProps<'th'>) {
  return (
    <th
      data-slot="table-header"
      className={cn(
        'border-border text-muted-foreground relative box-border border-b px-2 py-3 text-sm font-medium lg:px-3',
        ALIGN_CLASSES[align],
        minWidth,
        width && 'w-(--cell-width) max-w-(--cell-width) min-w-(--cell-width)',
        className,
      )}
      style={
        width ? ({ '--cell-width': width } as React.CSSProperties) : undefined
      }
      {...props}
    />
  );
}

function TableCell({
  className,
  minWidth,
  width,
  align = 'left',
  ...props
}: TableCellProps<'td'>) {
  return (
    <td
      data-slot="table-cell"
      className={cn(
        'box-border px-2 py-2 text-sm lg:px-3',
        ALIGN_CLASSES[align],
        minWidth,
        width && 'w-(--cell-width) max-w-(--cell-width) min-w-(--cell-width)',
        className,
      )}
      style={
        width ? ({ '--cell-width': width } as React.CSSProperties) : undefined
      }
      {...props}
    />
  );
}

export {
  Table,
  TableContainer,
  TableHead,
  TableBody,
  TableRow,
  TableHeader,
  TableCell,
};

export default Table;
