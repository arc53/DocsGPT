import {
  Brain,
  Coins,
  Search,
  Timer,
  TriangleAlert,
  Wrench,
} from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';

import { TraceCounts } from '../types';
import { formatDurationMs, formatTokens } from './traceUtils';

type TraceChipsProps = {
  durationMs?: number;
  counts: TraceCounts;
};

/** Compact stat chips for a trace: duration, LLM calls, tokens, tools, RAG time, errors. */
export default function TraceChips({ durationMs, counts }: TraceChipsProps) {
  const { t } = useTranslation();
  const chips: {
    key: string;
    icon: React.ReactNode;
    label: string;
    tone?: 'danger';
  }[] = [];
  if (durationMs !== undefined)
    chips.push({
      key: 'duration',
      icon: <Timer className="size-3" />,
      label: formatDurationMs(durationMs),
    });
  if (counts.llm_calls)
    chips.push({
      key: 'llm',
      icon: <Brain className="size-3" />,
      label: t('settings.logs.trace.chips.llmCalls', {
        count: counts.llm_calls,
      }),
    });
  if (counts.input_tokens || counts.output_tokens)
    chips.push({
      key: 'tokens',
      icon: <Coins className="size-3" />,
      label: t('settings.logs.trace.chips.tokens', {
        input: formatTokens(counts.input_tokens),
        output: formatTokens(counts.output_tokens),
      }),
    });
  if (counts.tool_calls)
    chips.push({
      key: 'tools',
      icon: <Wrench className="size-3" />,
      label: t('settings.logs.trace.chips.toolCalls', {
        count: counts.tool_calls,
      }),
    });
  if (counts.retrieval_calls)
    chips.push({
      key: 'retrieval',
      icon: <Search className="size-3" />,
      label: t('settings.logs.trace.chips.retrieval', {
        duration: formatDurationMs(counts.retrieval_ms),
      }),
    });
  if (counts.errors)
    chips.push({
      key: 'errors',
      icon: <TriangleAlert className="size-3" />,
      label: t('settings.logs.trace.chips.errors', { count: counts.errors }),
      tone: 'danger',
    });
  if (!chips.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {chips.map((chip) => (
        <span
          key={chip.key}
          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs tabular-nums ${
            chip.tone === 'danger'
              ? 'bg-destructive/10 text-destructive'
              : 'bg-muted text-foreground'
          }`}
        >
          {chip.icon}
          {chip.label}
        </span>
      ))}
    </div>
  );
}
