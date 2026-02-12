import { Database } from 'lucide-react';
import { memo } from 'react';
import { NodeProps } from 'reactflow';

import { BaseNode } from './BaseNode';

type SetStateNodeData = {
  label?: string;
  title?: string;
  variable?: string;
  value?: string;
};

const SetStateNode = ({ data, selected }: NodeProps<SetStateNodeData>) => {
  const title = data.title || data.label || 'Set State';
  return (
    <BaseNode
      title={title}
      type="state"
      selected={selected}
      icon={<Database size={16} />}
      handles={{ source: true, target: true }}
    >
      <div className="flex flex-col gap-1">
        {data.variable && (
          <div
            className="truncate text-[10px] text-gray-500 uppercase"
            title={`Variable: ${data.variable}`}
          >
            {data.variable}
          </div>
        )}
        {data.value && (
          <div
            className="truncate text-xs text-blue-600 dark:text-blue-400"
            title={`Value: ${data.value}`}
          >
            {data.value}
          </div>
        )}
      </div>
    </BaseNode>
  );
};

export default memo(SetStateNode);
