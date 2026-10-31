import { Repeat } from 'lucide-react';
import { memo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Handle,
  NodeProps,
  NodeResizer,
  Position,
  type ReactFlowState,
  useStore,
} from 'reactflow';

import { cn } from '@/lib/utils';

import { LoopNodeConfig } from '../../types/workflow';
import { LOOP_MIN_SIZE } from '../loopNodeConfig';
import { nodeToneClass } from '../nodeTones';
import { NO_ESCAPE } from '../workflowHelpers';
import OutputVariableLine from './OutputVariableLine';

type LoopNodeData = {
  title?: string;
  label?: string;
  config?: Partial<LoopNodeConfig>;
};

const HANDLE_CLASS =
  'hover:bg-primary/90! border-card! bg-muted-foreground! top-7! h-3! w-3! rounded-full! border-2! transition-colors!';

/**
 * A loop on the canvas: a resizable container whose header says what it
 * loops over, and whose body holds the nodes run once per item. Edges reach
 * the loop itself; the nodes inside connect only to each other.
 */
const LoopNode = ({ id, data, selected }: NodeProps<LoopNodeData>) => {
  const { t } = useTranslation();
  const hasBody = useStore(
    useCallback(
      (state: ReactFlowState) =>
        Array.from(state.nodeInternals.values()).some(
          (node) => node.parentNode === id,
        ),
      [id],
    ),
  );
  const title = data.title || data.label || t('agents.workflow.nodes.loop');
  const config = data.config || {};
  const items = (config.items || '').trim();

  return (
    <div
      className={cn(
        'bg-card/60 relative h-full w-full rounded-2xl border-2 border-dashed transition',
        selected ? 'border-primary ring-ring/50 ring-3' : 'border-border',
      )}
    >
      <NodeResizer
        isVisible={selected}
        minWidth={LOOP_MIN_SIZE.width}
        minHeight={LOOP_MIN_SIZE.height}
        lineClassName="border-primary!"
        handleClassName="bg-primary! border-card! h-2.5! w-2.5! rounded-full!"
      />
      <Handle
        type="target"
        position={Position.Left}
        isConnectable
        className={cn(HANDLE_CLASS, '-left-1.5!')}
      />
      <div className="border-border bg-card flex items-center gap-3 rounded-t-2xl border-b px-4 py-2.5">
        <div
          className={cn(
            'flex size-9 shrink-0 items-center justify-center rounded-full',
            nodeToneClass('loop'),
          )}
        >
          <Repeat className="size-4" />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <div
            className="text-foreground truncate text-sm font-semibold"
            title={title}
          >
            {title}
          </div>
          <div className="text-muted-foreground truncate text-xs">
            {items
              ? t('agents.workflow.nodes.loopSummary', {
                  ...NO_ESCAPE,
                  variable: config.item_variable || 'item',
                  items,
                })
              : t('agents.workflow.nodes.loopNoItems')}
          </div>
        </div>
        {config.output_variable && (
          <div className="max-w-[40%] shrink-0">
            <OutputVariableLine variable={config.output_variable} />
          </div>
        )}
      </div>
      {!hasBody && (
        <div className="text-muted-foreground pointer-events-none absolute inset-x-0 top-16 bottom-0 flex items-center justify-center px-6 text-center text-xs">
          {t('agents.workflow.nodes.loopEmpty')}
        </div>
      )}
      <Handle
        type="source"
        position={Position.Right}
        isConnectable
        className={cn(HANDLE_CLASS, '-right-1.5!')}
      />
    </div>
  );
};

export default memo(LoopNode);
