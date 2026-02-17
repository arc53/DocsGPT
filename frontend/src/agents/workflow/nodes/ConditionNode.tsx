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
      className={`relative rounded-2xl border bg-white shadow-md transition-all dark:bg-[#2C2C2C] ${
        selected
          ? 'border-violets-are-blue dark:ring-violets-are-blue scale-105 ring-2 ring-purple-300'
          : 'border-gray-200 hover:shadow-lg dark:border-[#3A3A3A]'
      }`}
      style={{ minWidth: 180, maxWidth: 220, height }}
    >
      <Handle
        type="target"
        position={Position.Left}
        isConnectable
        className="hover:bg-violets-are-blue! top-1/2! -left-1! h-3! w-3! rounded-full! border-2! border-white! bg-gray-400! transition-colors dark:border-[#2C2C2C]!"
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
          className="hover:bg-violets-are-blue! -right-1! h-3! w-3! rounded-full! border-2! border-white! bg-orange-400! transition-colors dark:border-[#2C2C2C]!"
        />
      ))}
      <Handle
        type="source"
        position={Position.Right}
        id="else"
        isConnectable
        style={{ top: getHandleTop(cases.length, totalOutputs) }}
        className="hover:bg-violets-are-blue! -right-1! h-3! w-3! rounded-full! border-2! border-white! bg-gray-400! transition-colors dark:border-[#2C2C2C]!"
      />
    </div>
  );
};

export default memo(ConditionNode);
