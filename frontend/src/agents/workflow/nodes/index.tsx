import React, { memo } from 'react';
import { BaseNode } from './BaseNode';
import SetStateNode from './SetStateNode';
import { Play, Bot, StickyNote, Flag } from 'lucide-react';

export const StartNode = memo(function StartNode({
  selected,
}: {
  selected: boolean;
}) {
  return (
    <BaseNode
      title="Start"
      type="start"
      selected={selected}
      handles={{ target: false, source: true }}
      icon={<Play size={16} />}
    >
      <div className="text-xs text-gray-500">Entry point of the workflow</div>
    </BaseNode>
  );
});

export const EndNode = memo(function EndNode({
  selected,
}: {
  selected: boolean;
}) {
  return (
    <BaseNode
      title="End"
      type="end"
      selected={selected}
      handles={{ target: true, source: false }}
      icon={<Flag size={16} />}
    >
      <div className="text-xs text-gray-500">Workflow completion</div>
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
  const title = data.title || data.label || 'Agent';
  const config = data.config || {};
  return (
    <BaseNode
      title={title}
      type="agent"
      selected={selected}
      icon={<Bot size={16} />}
    >
      <div className="flex flex-col gap-1">
        {config.agent_type && (
          <div
            className="truncate text-[10px] text-gray-500 uppercase"
            title={config.agent_type}
          >
            {config.agent_type}
          </div>
        )}
        {config.model_id && (
          <div
            className="text-purple-30 dark:text-violets-are-blue truncate text-xs"
            title={config.model_id}
          >
            {config.model_id}
          </div>
        )}
        {config.output_variable && (
          <div
            className="truncate text-xs text-green-600 dark:text-green-400"
            title={`Output ➔ ${config.output_variable}`}
          >
            Output ➔ {config.output_variable}
          </div>
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
  const title = data.title || data.label || 'Note';
  const maxContentLength = 120;
  const displayContent =
    data.content && data.content.length > maxContentLength
      ? `${data.content.substring(0, maxContentLength)}...`
      : data.content;

  return (
    <div
      className={`max-w-[250px] rounded-3xl border border-yellow-200 bg-yellow-50 px-5 py-3 shadow-md transition-all dark:border-yellow-800 dark:bg-yellow-900/20 ${
        selected
          ? 'scale-105 ring-2 ring-yellow-300 dark:ring-yellow-700'
          : 'hover:shadow-lg'
      }`}
    >
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-yellow-100 text-yellow-700 dark:bg-yellow-800/30 dark:text-yellow-500">
          <StickyNote size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <div
            className="truncate text-sm font-semibold text-yellow-800 dark:text-yellow-300"
            title={title}
          >
            {title}
          </div>
          {displayContent && (
            <div
              className="mt-1 text-xs wrap-break-word text-yellow-700 italic dark:text-yellow-400"
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
