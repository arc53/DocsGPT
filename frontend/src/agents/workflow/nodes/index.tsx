import { Bot, Flag, Play, StickyNote } from 'lucide-react';
import { memo } from 'react';
import { useTranslation } from 'react-i18next';

import { cn } from '@/lib/utils';

import { nodeToneClass } from '../nodeTones';
import { useModelDisplayName } from '../WorkflowModelsContext';
import { BaseNode } from './BaseNode';
import OutputVariableLine from './OutputVariableLine';
import CodeNode from './CodeNode';
import ConditionNode from './ConditionNode';
import SetStateNode from './SetStateNode';

export const StartNode = memo(function StartNode({
  selected,
}: {
  selected: boolean;
}) {
  const { t } = useTranslation();
  return (
    <BaseNode
      title={t('agents.workflow.nodes.start')}
      type="start"
      selected={selected}
      handles={{ target: false, source: true }}
      icon={<Play className="size-4" />}
    >
      <div className="text-muted-foreground text-xs">
        {t('agents.workflow.nodes.startHint')}
      </div>
    </BaseNode>
  );
});

export const EndNode = memo(function EndNode({
  selected,
}: {
  selected: boolean;
}) {
  const { t } = useTranslation();
  return (
    <BaseNode
      title={t('agents.workflow.nodes.end')}
      type="end"
      selected={selected}
      handles={{ target: true, source: false }}
      icon={<Flag className="size-4" />}
    >
      <div className="text-muted-foreground text-xs">
        {t('agents.workflow.nodes.endHint')}
      </div>
    </BaseNode>
  );
});

export const AgentNode = memo(function AgentNode({
  data,
  selected,
}: {
  data: {
    title?: string;
    label?: string;
    config?: {
      agent_type?: string;
      model_id?: string;
      prompt_template?: string;
      output_variable?: string;
    };
  };
  selected: boolean;
}) {
  const { t } = useTranslation();
  const title = data.title || data.label || t('agents.workflow.nodes.agent');
  const config = data.config || {};
  const modelName = useModelDisplayName(config.model_id);
  const agentType =
    config.agent_type === 'research' || config.agent_type === 'classic'
      ? t(`agents.form.agentTypes.${config.agent_type}`)
      : config.agent_type;
  const meta = [agentType, modelName].filter(Boolean).join(' · ');
  return (
    <BaseNode
      title={title}
      type="agent"
      selected={selected}
      icon={<Bot className="size-4" />}
    >
      <div className="flex flex-col gap-1">
        {meta && (
          <div className="text-muted-foreground truncate text-xs" title={meta}>
            {meta}
          </div>
        )}
        {config.output_variable && (
          <OutputVariableLine variable={config.output_variable} />
        )}
      </div>
    </BaseNode>
  );
});

export const NoteNode = memo(function NoteNode({
  data,
  selected,
}: {
  data: { title?: string; label?: string; content?: string };
  selected: boolean;
}) {
  const { t } = useTranslation();
  const title = data.title || data.label || t('agents.workflow.nodes.note');
  const maxContentLength = 120;
  const displayContent =
    data.content && data.content.length > maxContentLength
      ? `${data.content.substring(0, maxContentLength)}...`
      : data.content;

  return (
    <div
      className={cn(
        // Opaque tint: the card colour underneath, the warning wash painted
        // over it as a flat gradient, so the canvas grid doesn't show through.
        'bg-card from-warning/10 to-warning/10 max-w-[250px] rounded-3xl border bg-linear-to-b px-5 py-3 shadow-md transition',
        selected
          ? 'border-warning ring-warning/50 ring-3'
          : 'border-warning/50 hover:shadow-lg',
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className={cn(
            'flex size-10 shrink-0 items-center justify-center rounded-full',
            nodeToneClass('note'),
          )}
        >
          <StickyNote className="size-4.5" />
        </div>
        <div className="min-w-0 flex-1">
          <div
            className="text-foreground truncate text-sm font-semibold"
            title={title}
          >
            {title}
          </div>
          {displayContent && (
            <div
              className="text-muted-foreground mt-1 text-xs wrap-break-word italic"
              title={data.content}
            >
              {displayContent}
            </div>
          )}
        </div>
      </div>
    </div>
  );
});

export { SetStateNode };
export { ConditionNode };
export { CodeNode };
