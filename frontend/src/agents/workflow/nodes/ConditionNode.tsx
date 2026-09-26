import { GitBranch } from 'lucide-react';
import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Handle, NodeProps, Position } from 'reactflow';

import { cn } from '@/lib/utils';

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
  const { t } = useTranslation();
  const title =
    data.title || data.label || t('agents.workflow.nodes.condition');
  const cases = data.config?.cases || [];
  const totalOutputs = cases.length + 1;
  const height = getNodeHeight(cases.length);

  return (
    <div
      className={cn(
        'bg-card relative rounded-2xl border shadow-md transition',
        selected
          ? 'border-primary ring-primary scale-105 ring-2'
          : 'border-border hover:shadow-lg',
      )}
      style={{ minWidth: 180, maxWidth: 220, height }}
    >
      <Handle
        type="target"
        position={Position.Left}
        isConnectable
        className="hover:bg-primary/90! border-card! bg-muted-foreground! top-1/2! -left-1! h-3! w-3! rounded-full! border-2! transition-colors!"
      />

      <div className="flex items-center gap-3 px-3 py-2">
        <div className="bg-warning/10 text-warning flex size-9 shrink-0 items-center justify-center rounded-full">
          <GitBranch className="size-3.5" />
        </div>
        <div className="min-w-0 flex-1 pr-2">
          <div
            className="text-foreground truncate text-sm font-semibold"
            title={title}
          >
            {title}
          </div>
          <div className="text-muted-foreground text-xs">
            {data.config?.mode === 'advanced'
              ? t('agents.workflow.nodes.modeAdvanced')
              : t('agents.workflow.nodes.modeSimple')}
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
            <span className="text-warning shrink-0 text-xs font-medium">
              {i === 0
                ? t('agents.workflow.nodes.if')
                : t('agents.workflow.nodes.elseIf')}
            </span>
            {c.name && (
              <span
                className="text-muted-foreground truncate text-xs"
                title={c.name}
              >
                {c.name}
              </span>
            )}
          </div>
        ))}
        <div className="flex items-center gap-1" style={{ height: ROW_HEIGHT }}>
          <span className="text-muted-foreground text-xs font-medium">
            {t('agents.workflow.nodes.else')}
          </span>
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
          className="hover:bg-primary/90! border-card! bg-warning! -right-1! h-3! w-3! rounded-full! border-2! transition-colors"
        />
      ))}
      <Handle
        type="source"
        position={Position.Right}
        id="else"
        isConnectable
        style={{ top: getHandleTop(cases.length, totalOutputs) }}
        className="hover:bg-primary/90! border-card! bg-muted-foreground! -right-1! h-3! w-3! rounded-full! border-2! transition-colors!"
      />
    </div>
  );
};

export default memo(ConditionNode);
