import { Code2 } from 'lucide-react';
import { memo } from 'react';
import { NodeProps } from 'reactflow';

import { CodeNodeConfig } from '../../types/workflow';
import { BaseNode } from './BaseNode';

type CodeNodeData = {
  title?: string;
  label?: string;
  config?: Partial<CodeNodeConfig>;
};

const CodeNode = ({ data, selected }: NodeProps<CodeNodeData>) => {
  const title = data.title || data.label || 'Code';
  const config = data.config || {};
  const code = (config.code || '').trim();
  const firstLine = code.split('\n').find((line) => line.trim() !== '') || '';
  const codeHint =
    firstLine.length > 40 ? `${firstLine.slice(0, 40)}…` : firstLine;

  return (
    <BaseNode
      title={title}
      type="code"
      selected={selected}
      icon={<Code2 size={16} />}
      handles={{ source: true, target: true }}
    >
      <div className="flex flex-col gap-1">
        {codeHint ? (
          <div
            className="truncate font-mono text-xs text-gray-500 dark:text-gray-400"
            title={code}
          >
            {codeHint}
          </div>
        ) : (
          <div className="text-xs text-gray-500 dark:text-gray-400">
            No code yet
          </div>
        )}
        {config.output_variable && (
          <div
            className="truncate text-xs text-gray-500 dark:text-gray-400"
            title={`Output: ${config.output_variable}`}
          >
            Output: {config.output_variable}
          </div>
        )}
      </div>
    </BaseNode>
  );
};

export default memo(CodeNode);
