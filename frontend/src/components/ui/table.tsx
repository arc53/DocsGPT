import * as React from 'react';

import { cn } from '@/lib/utils';

interface TableProps {
  children: React.ReactNode;
  className?: string;
  minWidth?: string;
}

interface TableContainerProps {
  children: React.ReactNode;
  className?: string;
  height?: string;
  bordered?: boolean;
}

interface TableHeadProps {
  children: React.ReactNode;
  className?: string;
}

interface TableRowProps {
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
}

interface TableCellProps {
  children?: React.ReactNode;
  className?: string;
  minWidth?: string;
  width?: string;
  align?: 'left' | 'right' | 'center';
}

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
          )}
          style={{
            maxHeight: height === 'auto' ? undefined : height,
            overflowY: height === 'auto' ? 'hidden' : 'auto',
          }}
        >
          {children}
        </div>
      </div>
    );
  },
);

const Table: React.FC<TableProps> = ({
  children,
  className = '',
  minWidth = 'min-w-[600px]',
}) => {
  return (
    <table
      data-slot="table"
      className={cn(
        'w-full table-auto border-collapse bg-transparent',
        minWidth,
        className,
      )}
    >
      {children}
    </table>
  );
};

const TableHead: React.FC<TableHeadProps> = ({ children, className = '' }) => {
  return (
    <thead
      data-slot="table-head"
      className={cn('bg-muted sticky top-0 z-10', className)}
    >
      {children}
    </thead>
  );
};

const TableBody: React.FC<TableHeadProps> = ({ children, className = '' }) => {
  return (
    <tbody
      data-slot="table-body"
      className={cn('[&>tr:last-child]:border-b-0', className)}
    >
      {children}
    </tbody>
  );
};

const TableRow: React.FC<TableRowProps> = ({
  children,
  className = '',
  onClick,
}) => {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        'border-border hover:bg-muted border-b',
        onClick && 'cursor-pointer',
        className,
      )}
      onClick={onClick}
    >
      {children}
    </tr>
  );
};

const TableHeader: React.FC<TableCellProps> = ({
  children,
  className = '',
  minWidth,
  width,
  align = 'left',
}) => {
  const alignmentClass =
    align === 'right'
      ? 'text-right'
      : align === 'center'
        ? 'text-center'
        : 'text-left';

  return (
    <th
      data-slot="table-header"
      className={cn(
        'border-border text-muted-foreground relative box-border border-b px-2 py-3 text-sm font-medium lg:px-3',
        alignmentClass,
        minWidth,
        className,
      )}
      style={width ? { width, minWidth: width, maxWidth: width } : {}}
    >
      {children}
    </th>
  );
};

const TableCell: React.FC<TableCellProps> = ({
  children,
  className = '',
  minWidth,
  width,
  align = 'left',
}) => {
  const alignmentClass =
    align === 'right'
      ? 'text-right'
      : align === 'center'
        ? 'text-center'
        : 'text-left';

  return (
    <td
      data-slot="table-cell"
      className={cn(
        'box-border px-2 py-2 text-sm lg:px-3',
        alignmentClass,
        minWidth,
        className,
      )}
      style={width ? { width, minWidth: width, maxWidth: width } : {}}
    >
      {children}
    </td>
  );
};

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
