import { CodeXml } from 'lucide-react';
import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { NodeProps } from 'reactflow';

import { CodeNodeConfig } from '../../types/workflow';
import { BaseNode } from './BaseNode';

// Variable names are the user's own text: React escapes on render.
const NO_ESCAPE = { interpolation: { escapeValue: false } } as const;

type CodeNodeData = {
  title?: string;
  label?: string;
  config?: Partial<CodeNodeConfig>;
};

const CodeNode = ({ data, selected }: NodeProps<CodeNodeData>) => {
  const { t } = useTranslation();
  const title = data.title || data.label || t('agents.workflow.nodes.code');
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
      icon={<CodeXml className="size-4" />}
      handles={{ source: true, target: true }}
    >
      <div className="flex flex-col gap-1">
        {codeHint ? (
          <div
            className="text-muted-foreground truncate font-mono text-xs"
            title={code}
          >
            {codeHint}
          </div>
        ) : (
          <div className="text-muted-foreground text-xs">
            {t('agents.workflow.nodes.noCode')}
          </div>
        )}
        {config.output_variable && (
          <div
            className="text-muted-foreground truncate text-xs"
            title={t('agents.workflow.nodes.output', {
              ...NO_ESCAPE,
              variable: config.output_variable,
            })}
          >
            {t('agents.workflow.nodes.output', {
              ...NO_ESCAPE,
              variable: config.output_variable,
            })}
          </div>
        )}
      </div>
    </BaseNode>
  );
};

export default memo(CodeNode);
