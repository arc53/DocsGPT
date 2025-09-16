import React from 'react';

interface TableProps {
  children: React.ReactNode;
  className?: string;
  minWidth?: string;
}


interface TableContainerProps {
  children: React.ReactNode;
  className?: string;
  ref?: React.Ref<HTMLDivElement>;
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

const TableContainer = React.forwardRef<HTMLDivElement, TableContainerProps>(({
  children,
  className = '',
  height = 'auto',
  bordered = true
}, ref) => {
  return (
    <div className={`relative rounded-[6px] ${className}`}>
      <div
        ref={ref}
        className={`w-full overflow-x-auto rounded-[6px] bg-transparent ${bordered ? 'border border-[#D7D7D7] dark:border-[#6A6A6A]' : ''}`}
        style={{
          maxHeight: height === 'auto' ? undefined : height,
          overflowY: height === 'auto' ? 'hidden' : 'auto'
        }}
      >
        {children}
      </div>
    </div>
  );
});;
const Table: React.FC<TableProps> = ({
  children,
  className = '',
  minWidth = 'min-w-[600px]'
}) => {
  return (
    <table className={`w-full table-auto border-collapse bg-transparent ${minWidth} ${className}`}>
      {children}
    </table>
  );
};
const TableHead: React.FC<TableHeadProps> = ({ children, className = '' }) => {
  return (
    <thead className={`
      sticky top-0 z-10
      bg-gray-100 dark:bg-[#27282D]
      before:content-[''] before:absolute before:top-0 before:left-0 before:right-0 before:h-px before:bg-[#EEE6FF78] dark:before:bg-[#6A6A6A]
      after:content-[''] after:absolute after:bottom-0 after:left-0 after:right-0 after:h-px after:bg-[#EEE6FF78] dark:after:bg-[#6A6A6A]
      ${className}
    `}>
      {children}
    </thead>
  );
};

const TableBody: React.FC<TableHeadProps> = ({ children, className = '' }) => {
  return (
    <tbody className={`[&>tr:last-child]:border-b-0 ${className}`}>
      {children}
    </tbody>
  );
};

const TableRow: React.FC<TableRowProps> = ({ children, className = '', onClick }) => {
  const baseClasses = "border-b border-[#D7D7D7] hover:bg-[#ECEEEF] dark:border-[#6A6A6A] dark:hover:bg-[#27282D]";
  const cursorClass = onClick ? "cursor-pointer" : "";

  return (
    <tr className={`${baseClasses} ${cursorClass} ${className}`} onClick={onClick}>
      {children}
    </tr>
  );
};

const TableHeader: React.FC<TableCellProps> = ({
  children,
  className = '',
  minWidth,
  width,
  align = 'left'
}) => {
  const getAlignmentClass = () => {
    switch (align) {
      case 'right':
        return 'text-right';
      case 'center':
        return 'text-center';
      default:
        return 'text-left';
    }
  };

  const baseClasses = `px-2 py-3 text-sm font-medium text-gray-700 lg:px-3 dark:text-[#59636E] border-t border-b border-[#D7D7D7] dark:border-[#6A6A6A] relative box-border ${getAlignmentClass()}`;
  const widthClasses = minWidth ? minWidth : '';

  return (
    <th
      className={`${baseClasses} ${widthClasses} ${className}`}
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
  align = 'left'
}) => {
  const getAlignmentClass = () => {
    switch (align) {
      case 'right':
        return 'text-right';
      case 'center':
        return 'text-center';
      default:
        return 'text-left';
    }
  };

  const baseClasses = `px-2 py-2 text-sm lg:px-3 dark:text-[#E0E0E0] box-border ${getAlignmentClass()}`;
  const widthClasses = minWidth ? minWidth : '';

  return (
    <td
      className={`${baseClasses} ${widthClasses} ${className}`}
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
