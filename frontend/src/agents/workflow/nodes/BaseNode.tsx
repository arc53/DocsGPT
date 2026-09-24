import React, { ReactNode } from 'react';
import { Handle, Position } from 'reactflow';

interface BaseNodeProps {
  title: string;
  children?: ReactNode;
  selected?: boolean;
  type?: 'start' | 'end' | 'default' | 'state' | 'agent' | 'condition' | 'code';
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
  let bgColor = 'bg-card';
  let borderColor = 'border-border';
  let iconBg = 'bg-muted';
  let iconColor = 'text-muted-foreground';

  if (selected) {
    borderColor = 'border-primary ring-2 ring-primary';
  }

  if (type === 'start') {
    iconBg = 'bg-success/10';
    iconColor = 'text-success';
  } else if (type === 'end') {
    iconBg = 'bg-destructive/10';
    iconColor = 'text-destructive';
  } else if (type === 'state') {
    iconBg = 'bg-muted';
    iconColor = 'text-muted-foreground';
  } else if (type === 'condition') {
    iconBg = 'bg-warning/10';
    iconColor = 'text-warning';
  } else if (type === 'code') {
    iconBg = 'bg-info/10';
    iconColor = 'text-info';
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
          className="hover:bg-primary/90! border-card! bg-muted-foreground! -left-1! h-3! w-3! rounded-full! border-2! transition-colors!"
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
            className="text-foreground truncate text-sm font-semibold"
            title={title}
          >
            {title}
          </div>
          {children && (
            <div className="text-muted-foreground mt-1 truncate text-xs">
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
          className="hover:bg-primary/90! border-card! bg-muted-foreground! -right-1! h-3! w-3! rounded-full! border-2! transition-colors!"
        />
      )}
    </div>
  );
};
