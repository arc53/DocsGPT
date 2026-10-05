import { Database } from 'lucide-react';
import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { NodeProps } from 'reactflow';

import { StateOperationConfig } from '../../types/workflow';
import { BaseNode } from './BaseNode';

// Variable names are the user's own text: React escapes on render.
const NO_ESCAPE = { interpolation: { escapeValue: false } } as const;

type SetStateNodeData = {
  label?: string;
  title?: string;
  variable?: string;
  value?: string;
  config?: {
    operations?: StateOperationConfig[];
  };
};

const SetStateNode = ({ data, selected }: NodeProps<SetStateNodeData>) => {
  const { t } = useTranslation();
  const title = data.title || data.label || t('agents.workflow.nodes.setState');
  const operations = data.config?.operations || [];
  const hasLegacy = !operations.length && data.variable;

  return (
    <BaseNode
      title={title}
      type="state"
      selected={selected}
      icon={<Database className="size-4" />}
      handles={{ source: true, target: true }}
    >
      <div className="flex flex-col gap-1">
        {operations.length > 0 ? (
          <div
            className="text-muted-foreground truncate text-xs"
            title={t('agents.workflow.nodes.operationCount', {
              count: operations.length,
            })}
          >
            {t('agents.workflow.nodes.variableCount', {
              count: operations.length,
            })}
          </div>
        ) : hasLegacy ? (
          <>
            <div
              className="text-muted-foreground truncate text-xs"
              title={t('agents.workflow.nodes.variableTitle', {
                ...NO_ESCAPE,
                name: data.variable,
              })}
            >
              {data.variable}
            </div>
            {data.value && (
              <div
                className="text-info truncate text-xs"
                title={t('agents.workflow.nodes.valueTitle', {
                  ...NO_ESCAPE,
                  value: data.value,
                })}
              >
                {data.value}
              </div>
            )}
          </>
        ) : null}
      </div>
    </BaseNode>
  );
};

export default memo(SetStateNode);
