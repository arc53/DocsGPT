import React, { ReactNode } from 'react';
import { Handle, Position } from 'reactflow';

interface BaseNodeProps {
  title: string;
  children?: ReactNode;
  selected?: boolean;
  type?: 'start' | 'end' | 'default' | 'state' | 'agent';
  icon?: ReactNode;
  handles?: {
    source?: boolean;
    target?: boolean;
  };
}

export const BaseNode: React.FC<BaseNodeProps> = ({
  title,
  children,
  selected,
  type = 'default',
  icon,
  handles = { source: true, target: true },
}) => {
  let bgColor = 'bg-white dark:bg-[#2C2C2C]';
  let borderColor = 'border-gray-200 dark:border-[#3A3A3A]';
  let iconBg = 'bg-gray-100 dark:bg-gray-800';
  let iconColor = 'text-gray-600 dark:text-gray-400';

  if (selected) {
    borderColor =
      'border-violets-are-blue ring-2 ring-purple-300 dark:ring-violets-are-blue';
  }

  if (type === 'start') {
    iconBg = 'bg-green-100 dark:bg-green-900/30';
    iconColor = 'text-green-600 dark:text-green-400';
  } else if (type === 'end') {
    iconBg = 'bg-red-100 dark:bg-red-900/30';
    iconColor = 'text-red-600 dark:text-red-400';
  } else if (type === 'state') {
    iconBg = 'bg-gray-100 dark:bg-gray-800';
    iconColor = 'text-gray-600 dark:text-gray-400';
  }

  return (
    <div
      className={`rounded-full border ${bgColor} ${borderColor} shadow-md transition-all hover:shadow-lg ${
        selected ? 'scale-105' : ''
      } max-w-[250px] min-w-[180px]`}
    >
      {handles.target && (
        <Handle
          type="target"
          position={Position.Left}
          isConnectable={true}
          className="hover:bg-violets-are-blue! -left-1! h-3! w-3! rounded-full! border-2! border-white! bg-gray-400! transition-colors dark:border-[#2C2C2C]!"
        />
      )}

      <div className="flex items-center gap-3 px-4 py-3">
        <div
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${iconBg} ${iconColor}`}
        >
          {icon}
        </div>
        <div className="min-w-0 flex-1 pr-3">
          <div
            className="truncate text-sm font-semibold text-gray-900 dark:text-white"
            title={title}
          >
            {title}
          </div>
          {children && (
            <div className="mt-1 truncate text-xs text-gray-600 dark:text-gray-400">
              {children}
            </div>
          )}
        </div>
      </div>

      {handles.source && (
        <Handle
          type="source"
          position={Position.Right}
          isConnectable={true}
          className="hover:bg-violets-are-blue! -right-1! h-3! w-3! rounded-full! border-2! border-white! bg-gray-400! transition-colors dark:border-[#2C2C2C]!"
        />
      )}
    </div>
  );
};
