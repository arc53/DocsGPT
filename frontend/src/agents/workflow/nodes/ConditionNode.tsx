import { GitBranch } from 'lucide-react';
import { memo } from 'react';
import { Handle, NodeProps, Position } from 'reactflow';

import { ConditionCase } from '../../types/workflow';

type ConditionNodeData = {
  label?: string;
  title?: string;
  config?: {
    mode?: 'simple' | 'advanced';
    cases?: ConditionCase[];
  };
};

const ROW_HEIGHT = 18;
const HEADER_HEIGHT = 52;
const PADDING_BOTTOM = 8;

function getNodeHeight(caseCount: number): number {
  return (
    HEADER_HEIGHT + Math.max(caseCount + 1, 2) * ROW_HEIGHT + PADDING_BOTTOM
  );
}

function getHandleTop(index: number, total: number): string {
  const offset = HEADER_HEIGHT;
  return `${offset + ROW_HEIGHT * index + ROW_HEIGHT / 2}px`;
}

const ConditionNode = ({ data, selected }: NodeProps<ConditionNodeData>) => {
  const title = data.title || data.label || 'If / Else';
  const cases = data.config?.cases || [];
  const totalOutputs = cases.length + 1;
  const height = getNodeHeight(cases.length);

  return (
    <div
      className={`bg-card relative rounded-2xl border shadow-md transition-all ${
        selected
          ? 'border-primary dark:ring-primary scale-105 ring-2 ring-purple-300'
          : 'border-border hover:shadow-lg'
      }`}
      style={{ minWidth: 180, maxWidth: 220, height }}
    >
      <Handle
        type="target"
        position={Position.Left}
        isConnectable
        className="hover:bg-primary/90! border-card! top-1/2! -left-1! h-3! w-3! rounded-full! border-2! bg-gray-400! transition-colors!"
      />

      <div className="flex items-center gap-3 px-3 py-2">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-orange-100 text-orange-600 dark:bg-orange-900/30 dark:text-orange-400">
          <GitBranch size={14} />
        </div>
        <div className="min-w-0 flex-1 pr-2">
          <div
            className="truncate text-sm font-semibold text-gray-900 dark:text-white"
            title={title}
          >
            {title}
          </div>
          <div className="text-[10px] text-gray-500 uppercase">
            {data.config?.mode || 'simple'}
          </div>
        </div>
      </div>

      <div className="flex flex-col px-3">
        {cases.map((c, i) => (
          <div
            key={c.sourceHandle}
            className="flex items-center gap-1"
            style={{ height: ROW_HEIGHT }}
          >
            <span className="shrink-0 text-xs font-medium text-orange-600 dark:text-orange-400">
              {i === 0 ? 'If' : 'Else if'}
            </span>
            {c.name && (
              <span
                className="truncate text-xs text-gray-600 dark:text-gray-400"
                title={c.name}
              >
                {c.name}
              </span>
            )}
          </div>
        ))}
        <div className="flex items-center gap-1" style={{ height: ROW_HEIGHT }}>
          <span className="text-xs font-medium text-gray-500">Else</span>
        </div>
      </div>

      {cases.map((c, i) => (
        <Handle
          key={c.sourceHandle}
          type="source"
          position={Position.Right}
          id={c.sourceHandle}
          isConnectable
          style={{ top: getHandleTop(i, totalOutputs) }}
          className="hover:bg-primary/90! dark:border-border! -right-1! h-3! w-3! rounded-full! border-2! border-white! bg-orange-400! transition-colors"
        />
      ))}
      <Handle
        type="source"
        position={Position.Right}
        id="else"
        isConnectable
        style={{ top: getHandleTop(cases.length, totalOutputs) }}
        className="hover:bg-primary/90! border-card! -right-1! h-3! w-3! rounded-full! border-2! bg-gray-400! transition-colors!"
      />
    </div>
  );
};

export default memo(ConditionNode);
