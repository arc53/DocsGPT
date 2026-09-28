import React, { ReactNode } from 'react';
import { Handle, Position } from 'reactflow';

import { cn } from '@/lib/utils';

import { nodeToneClass, type WorkflowNodeType } from '../nodeTones';

interface BaseNodeProps {
  title: string;
  children?: ReactNode;
  selected?: boolean;
  /** The node type; picks the icon square's tone from the shared map. */
  type: WorkflowNodeType;
  icon?: ReactNode;
  handles?: {
    source?: boolean;
    target?: boolean;
  };
}

/**
 * The pill every canvas node but Note and If / Else is drawn as: a tinted
 * icon, the title, a muted meta block and the handles. Selected is the focus
 * ring look (`border-primary ring-3 ring-ring/50`), with no scale, so the
 * node stays put under the pointer.
 */
export const BaseNode: React.FC<BaseNodeProps> = ({
  title,
  children,
  selected,
  type,
  icon,
  handles = { source: true, target: true },
}) => {
  return (
    <div
      className={cn(
        'bg-card rounded-full border shadow-md transition hover:shadow-lg',
        selected ? 'border-primary ring-ring/50 ring-3' : 'border-border',
        'max-w-[250px] min-w-[180px]',
      )}
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
          className={cn(
            'flex size-10 shrink-0 items-center justify-center rounded-full',
            nodeToneClass(type),
          )}
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
